"""Native AquaSky 3 MQTT transport (not a Wi-Fi to BLE bridge).

Envelope and topics: FluvalConnect 1.0.15 LightInstructionsKxtKt,
LightDetailActivity.initWifiMqtt and firmware Fluval532 V10.
Only the configured Home Assistant broker is used; no vendor credentials.
"""

import asyncio
from collections.abc import Callable
import contextlib
import re
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from . import protocol
from .client import Client

CONF_TRANSPORT = "transport"
TRANSPORT_MQTT = "local_mqtt"
CONF_WIFI_MAC = "wifi_mac"
NATIVE_MQTT_PRODUCT_ID = 532
MAX_MESSAGE_BYTES = 16384
STATE_TIMEOUT = 5.0


def native_topic(wifi_mac: str) -> str:
    """Build the exact product-532 topic, rejecting wildcard injection."""
    mac = wifi_mac.replace(":", "").upper()
    if not re.fullmatch(r"[0-9A-F]{12}", mac):
        raise ValueError("A valid fixture Wi-Fi MAC address is required")
    return f"cyd/dev/Fluval/Fluval-532/{mac}"


def decode_uplink(payload: str | bytes) -> bytes | None:
    """Decode the firmware's bounded id:type:param semicolon envelope.

    Firmware uses id:%lu;type:%s;%s;; with param:%s (hex CBOR).
    Heartbeats/version events are not lighting state or command confirmation.
    """
    if len(payload) > MAX_MESSAGE_BYTES:
        return None
    try:
        text = payload.decode("ascii") if isinstance(payload, bytes) else payload
        if not text.endswith(";;"):
            return None
        fields = {}
        for field in text[:-2].split(";"):
            key, value = field.split(":", 1)
            if key in fields or key not in {"id", "type", "param", "version"}:
                return None
            fields[key] = value
        if not re.fullmatch(r"[0-9]+", fields.get("id", "")):
            return None
        if fields.get("type") not in {"property_post", "property_get", "property_set"}:
            return None
        raw = fields.get("param", "")
        if not raw or len(raw) % 2 or not re.fullmatch(r"[0-9A-Fa-f]+", raw):
            return None
        packet = bytes.fromhex(raw)
        state = protocol.decode_cbor_map(packet)
        if not state or any(type(key) is not int for key in state):
            return None
        return packet
    except (UnicodeError, ValueError):
        return None


class MqttClient(Client):
    """Device-compatible client without BLE initialization or GATT calls.

    Client inheritance reuses only its pure state decoder/comparison helpers.
    All I/O, lifecycle and request serialization are implemented here.
    """

    def __init__(
        self, hass: Any, wifi_mac: str, status_callback: Callable, update_callback: Callable, state_validator: Callable
    ) -> None:
        # Deliberately do not invoke Client.__init__: it starts a BLE connection.
        self.hass = hass
        self.topic = native_topic(wifi_mac)
        self.status_callback = status_callback
        self.update_callback = update_callback
        self.state_validator = state_validator
        self.device = None
        self.raw_facebd = self.wifi_facebd = True
        self.spp_transport = False
        self.profile = "native_local_mqtt"
        self.command_write_uuid = None
        self.notify_uuids = []
        self.last_error = None
        self.last_write_targets = []
        self.last_write_verified = False
        self.last_expected_state = {}
        self.last_confirmed_state = {}
        self.last_verification_mismatches = {}
        self._observed_state = {}
        self._state_update_event = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self._read_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._unsubscribers: list[Callable] = []
        self._monitor: asyncio.Task | None = None
        self._stopping = False
        self._online = False
        self._request_id = 0

    async def start(self) -> None:
        """Subscribe before sending a read; HA owns broker reconnection."""
        from homeassistant.components import mqtt

        if self._unsubscribers:
            return
        self._unsubscribers.append(
            await mqtt.async_subscribe(self.hass, self.topic + "/uplink", self._message, qos=0, encoding=None)
        )
        self._unsubscribers.append(mqtt.async_subscribe_connection_status(self.hass, self._broker_status))
        self._monitor = asyncio.create_task(self._poll())

    @callback
    def _broker_status(self, connected: bool) -> None:
        if not connected:
            self._online = False
            self._observed_state.clear()
            if self.status_callback:
                self.status_callback(False)
            self._state_update_event.set()

    def _broker_connected(self) -> bool:
        """Broker unload/reload can temporarily remove HA's MQTT runtime."""
        from homeassistant.components import mqtt

        try:
            return mqtt.is_connected(self.hass)
        except KeyError:
            return False

    @callback
    def _message(self, message: Any) -> None:
        # Retained state cannot prove a fixture is currently online.
        if self._stopping or getattr(message, "retain", False):
            return
        packet = decode_uplink(message.payload)
        if packet is not None:
            self._dispatch_update(packet)

    async def _publish(self, kind: str, packet: bytes | None = None) -> None:
        from homeassistant.components import mqtt

        if self._stopping or not self._broker_connected():
            raise ConnectionError("Home Assistant MQTT broker is disconnected")
        self._request_id = (self._request_id + 1) % 2147483647
        payload = f"id:{self._request_id};type:{kind}"
        if packet is not None:
            payload += f";param:{packet.hex()}"
        try:
            await asyncio.wait_for(
                mqtt.async_publish(self.hass, self.topic + "/downlink", payload + ";;", qos=0, retain=False),
                timeout=STATE_TIMEOUT,
            )
        except HomeAssistantError as err:
            raise ConnectionError("Unable to publish to Home Assistant's MQTT broker") from err

    async def ensure_connected(self) -> bool:
        async with self._connect_lock:
            if self._stopping:
                return False
            if self._online:
                return True
            await self.start()
            # Retry only a read, never a potentially non-idempotent command.
            for _ in range(2):
                if await self.request_state(state_validator=self.state_validator):
                    return True
            return False

    async def request_state(self, expected_state=None, *, state_validator=None, timeout=None) -> bool:
        """Require fresh state, accumulating split maps within this read only."""
        async with self._read_lock:
            self._observed_state = {}
            self._state_update_event.clear()
            try:
                await self._publish("property_get")
                async with asyncio.timeout(STATE_TIMEOUT if timeout is None else timeout):
                    while not (
                        self._observed_state
                        and self._state_matches(expected_state)
                        and (state_validator is None or state_validator(self.observed_state))
                    ):
                        await self._state_update_event.wait()
                        self._state_update_event.clear()
                        if self._stopping:
                            return False
                        if not self._broker_connected():
                            raise ConnectionError("Home Assistant MQTT broker is disconnected")
                if self._stopping:
                    return False
                self.last_error = None
                self._online = True
                if self.status_callback:
                    self.status_callback(True)
                return True
            except (TimeoutError, ConnectionError) as err:
                self.last_error = str(err) or "No fresh fixture state received over local MQTT"
                self._online = False
                if self.status_callback:
                    self.status_callback(False)
                return False

    async def send_now(self, data, *, expected_state=None, verify=True) -> bool:
        async with self._command_lock:
            self.last_write_verified = False
            self.last_write_targets = []
            self.last_expected_state = dict(expected_state or {})
            if not await self.ensure_connected():
                return False
            try:
                await self._publish("property_set", bytes(data))
                # Keep the Wi-Fi MAC out of otherwise shareable command logs.
                self.last_write_targets = ["native_mqtt_downlink"]
                if verify and expected_state:
                    self.last_write_verified = await self.request_state(expected_state)
                    if not self.last_write_verified:
                        return False
                self.last_error = None
                return True
            except (ConnectionError, TimeoutError) as err:
                self.last_error = str(err) or "Timed out publishing the fixture command to local MQTT"
                self._broker_status(False)
                return False

    async def _poll(self) -> None:
        try:
            while not self._stopping:
                await asyncio.sleep(30)
                async with self._command_lock:
                    await self.request_state(state_validator=self.state_validator)
        except asyncio.CancelledError:
            pass

    async def disconnect(self) -> None:
        await self.stop()

    async def stop(self) -> None:
        """Remove only this fixture's subscriptions; never stop HA's broker."""
        self._stopping = True
        self._state_update_event.set()
        if self._monitor:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
            self._monitor = None
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self._online = False
        if self.status_callback:
            self.status_callback(False)
