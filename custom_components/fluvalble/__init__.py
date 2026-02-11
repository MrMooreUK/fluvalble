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
    devices = hass.data.setdefault(DOMAIN, {})
    mac = entry.data.get(CONF_MAC)
    if not mac:
        _LOGGER.warning("Config entry %s missing MAC", entry.entry_id)
        return False

    # If the device is already in the Bluetooth cache (e.g. just discovered in config flow),
    # create the device and entities immediately so the user gets the switch/controls right away.
    service_info = bluetooth.async_last_service_info(hass, mac, connectable=True)
    if service_info:
        devices[entry.entry_id] = Device(
            entry.title, service_info.device, service_info.advertisement
        )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        if device := devices.get(entry.entry_id):
            device.update_ble(service_info.advertisement)
            return

        devices[entry.entry_id] = Device(
            entry.title, service_info.device, service_info.advertisement
        )
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        )

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
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
