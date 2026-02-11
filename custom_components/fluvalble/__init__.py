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
    mac_raw = entry.data.get(CONF_MAC)
    # HA's Bluetooth stack uses uppercase MACs internally. Normalize here
    # so the address filter in async_register_callback matches correctly,
    # even if an older config entry stored it as lowercase.
    mac = mac_raw.strip().upper() if mac_raw else None

    _LOGGER.warning(
        "[fluvalble] async_setup_entry called — mac=%s (raw=%s), entry_id=%s",
        mac,
        mac_raw,
        entry.entry_id,
    )

    if not mac:
        _LOGGER.error("[fluvalble] Config entry %s has no MAC address", entry.entry_id)
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
        _LOGGER.warning(
            "[fluvalble] Creating device for %s (name=%s)",
            mac,
            service_info.device.address,
        )
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

        pending_count = len(entry_data["pending_add_entities"])
        _LOGGER.warning(
            "[fluvalble] %d platform(s) pending entity creation", pending_count
        )

        for platform, add_fn in entry_data["pending_add_entities"].items():
            factory = factories.get(platform)
            if factory:
                entities = factory(device)
                _LOGGER.warning(
                    "[fluvalble] Adding %d entities for platform %s",
                    len(entities),
                    platform,
                )
                add_fn(entities)
        entry_data["pending_add_entities"].clear()

        _LOGGER.warning("[fluvalble] Device %s ready", mac)
        return device

    # Try Bluetooth cache first — instant entity setup if the light was just discovered.
    try:
        get_last = getattr(bluetooth, "async_last_service_info", None)
        if get_last:
            service_info = get_last(hass, mac, connectable=True)
            if service_info:
                _LOGGER.warning("[fluvalble] Found %s in BLE cache, creating device now", mac)
                _create_device(service_info)
            else:
                _LOGGER.warning("[fluvalble] %s NOT in BLE cache, will wait for advertisement", mac)
        else:
            _LOGGER.warning("[fluvalble] async_last_service_info not available in this HA version")
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "[fluvalble] Error checking BLE cache for %s, will wait for advertisement",
            mac,
            exc_info=True,
        )

    # Always forward platform setup — platforms will either create entities
    # immediately (device exists) or stash their add_entities callback
    # (device pending) so _create_device can populate them later.
    _LOGGER.warning("[fluvalble] Forwarding platform setup for %s", mac)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.warning("[fluvalble] Platform setup complete for %s", mac)

    @callback
    def update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        if device := entry_data["device"]:
            device.update_ble(service_info.advertisement, service_info.device)
            return

        # First time seeing the device via BLE advertisement
        _LOGGER.warning(
            "[fluvalble] BLE advertisement received for %s — creating device",
            mac,
        )
        _create_device(service_info)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            update_ble,
            {"address": mac},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    _LOGGER.warning("[fluvalble] Setup complete for %s — waiting for BLE", mac)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.warning("[fluvalble] Unloading entry %s", entry.entry_id)
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data and entry_data.get("device"):
            await entry_data["device"].client.stop()

    return unload_ok
