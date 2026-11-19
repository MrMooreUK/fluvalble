"""Explicit AquaSky Wi-Fi provisioning over HA's existing BLE connection."""

import asyncio
import logging

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant

from .core.device import Device
from .core.mqtt_client import MqttClient
from .core.mqtt_provisioning import PROVISION_UUID, provisioning_wifi_mac

_LOGGER = logging.getLogger(__name__)
BLE_SETUP_TIMEOUT = 45


async def provision(hass: HomeAssistant, device: Device, wifi: bytes, broker: bytes) -> str:
    """Return the Wi-Fi address only after a fresh local broker read."""
    if device.product_id != 532 or not mqtt.is_connected(hass):
        raise ValueError("AquaSky 3.0 and a connected local broker are required")
    async with device.command_transaction(), asyncio.timeout(BLE_SETUP_TIMEOUT):
        if not await device._async_prepare_command() or device.client is None or isinstance(device.client, MqttClient):
            raise ConnectionError("Fixture is not reachable over Bluetooth")
        ble = device.client
        gatt = await ble._ensure_client()
        characteristic = gatt.services.get_characteristic(PROVISION_UUID)
        if characteristic is None:
            raise ConnectionError("Fixture does not expose Wi-Fi setup")
        identity = await asyncio.wait_for(gatt.read_gatt_char(characteristic), 10)
        mac = provisioning_wifi_mac(identity.decode("ascii"))
        if mac is None:
            raise ValueError("Fixture did not report a Wi-Fi identity")

        buffer = bytearray()
        reports: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)

        def receive(_sender, data):
            buffer.extend(data)
            if len(buffer) > 4096:
                buffer.clear()
                return
            while b";;" in buffer:
                end = buffer.index(b";;") + 2
                if not reports.full():
                    reports.put_nowait(bytes(buffer[:end]))
                del buffer[:end]

        async def exchange(frame: bytes, expected: bytes) -> None:
            buffer.clear()
            while not reports.empty():
                reports.get_nowait()
            response = "write-without-response" not in characteristic.properties
            # Use a conservative chunk size across local adapters and proxies.
            for offset in range(0, len(frame), 20):
                await gatt.write_gatt_char(characteristic, frame[offset : offset + 20], response=response)
                await asyncio.sleep(0.005)
            while True:
                report = await reports.get()
                if report.startswith(b"err:"):
                    raise ConnectionError("Fixture rejected Wi-Fi or broker settings")
                if report.startswith(expected):
                    return

        # Keep the client's idle timer from disconnecting a provisioning write.
        async with ble._command_lock:
            restore_state_notify = PROVISION_UUID in ble.notify_uuids
            try:
                if restore_state_notify:
                    await asyncio.wait_for(gatt.stop_notify(characteristic), 5)
                await asyncio.wait_for(gatt.start_notify(characteristic, receive), 10)
                await exchange(wifi, b"ip:")
                await exchange(broker, b"mqtt:connected;;")
            finally:
                try:
                    if gatt.is_connected:
                        async with asyncio.timeout(5):
                            await gatt.stop_notify(characteristic)
                            if restore_state_notify:
                                await gatt.start_notify(characteristic, ble.notify_callback)
                except asyncio.CancelledError:
                    await asyncio.shield(ble._safe_disconnect())
                    raise
                except Exception:
                    # Never keep a session that might no longer deliver state.
                    _LOGGER.debug("Reconnecting BLE after provisioning notification cleanup failed")
                    await ble._safe_disconnect()

    probe = MqttClient(hass, mac, lambda _: None, lambda _: True, device._initial_state_complete)
    try:
        if not await probe.ensure_connected():
            raise ConnectionError("Fixture did not respond through Home Assistant's MQTT broker")
    finally:
        await probe.stop()
    return mac
