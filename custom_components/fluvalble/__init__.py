"""The Fluval Aquarium LED integration."""
from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, Platform
from homeassistant.core import HomeAssistant, callback
from .core import DOMAIN
from .core.device import Device

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fluval Aquarium LED from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    mac = entry.data.get(CONF_MAC)
    if not mac:
        _LOGGER.warning("Config entry %s missing MAC", entry.entry_id)
        return False

    # Shared dict for this entry — platforms read from here.
    # "device" is set once the BLE device is seen; "pending_add_entities" lets
    # platforms that loaded before the device register their add_entities
    # callbacks so we can populate them once the device arrives.
    entry_data: dict = {
        "device": None,
        "pending_add_entities": {},
    }
    hass.data[DOMAIN][entry.entry_id] = entry_data

    def _create_device(
        service_info: bluetooth.BluetoothServiceInfoBleak,
    ) -> Device:
        """Instantiate Device and add entities for any platforms that are already loaded."""
        device = Device(
            entry.title, service_info.device, service_info.advertisement
        )
        entry_data["device"] = device

        # Retroactively add entities for platforms that set up before the
        # device was available (they stashed their add_entities callback).
        from .switch import create_entities as switch_entities  # noqa: C0415
        from .number import create_entities as number_entities  # noqa: C0415
        from .binary_sensor import create_entities as sensor_entities  # noqa: C0415
        from .select import create_entities as select_entities  # noqa: C0415

        factories = {
            Platform.SWITCH: switch_entities,
            Platform.NUMBER: number_entities,
            Platform.BINARY_SENSOR: sensor_entities,
            Platform.SELECT: select_entities,
        }

        for platform, add_fn in entry_data["pending_add_entities"].items():
            factory = factories.get(platform)
            if factory:
                add_fn(factory(device))
        entry_data["pending_add_entities"].clear()

        _LOGGER.info("Fluval device %s ready", mac)
        return device

    # Try Bluetooth cache first — instant entity setup if the light was just discovered.
    try:
        get_last = getattr(bluetooth, "async_last_service_info", None)
        if get_last:
            service_info = get_last(hass, mac, connectable=True)
            if service_info:
                _create_device(service_info)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not create device from cache, will wait for BLE callback", exc_info=True)

    # Always forward platform setup — platforms will either create entities
    # immediately (device exists) or stash their add_entities callback
    # (device pending) so _create_device can populate them later.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        if device := entry_data["device"]:
            device.update_ble(service_info.advertisement)
            return

        # First time seeing the device via BLE advertisement
        _create_device(service_info)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            update_ble,
            {"address": mac},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data and entry_data.get("device"):
            await entry_data["device"].client.stop()

    return unload_ok
