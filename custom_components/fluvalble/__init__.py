"""The Fluval Aquarium LED integration."""

from __future__ import annotations

import logging
from pathlib import Path
from time import monotonic
import inspect
from datetime import timedelta

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_track_time_interval
from .core import (
    CONF_ACTIVE_TIME,
    CONF_PING_INTERVAL,
    DEFAULT_ACTIVE_TIME,
    DEFAULT_PING_INTERVAL,
    DOMAIN,
)
from .core.device import Device

_LOGGER = logging.getLogger(__name__)

DISCOVERY_LOG_INTERVAL = 5
SERVICE_SET_CHANNELS = "set_channels"
SERVICE_PREVIEW_SCHEDULE = "preview_schedule"
SERVICE_STOP_PREVIEW = "stop_preview"
SERVICE_SAVE_SCHEDULE = "save_schedule"
SERVICES_REGISTERED = "services_registered"
STATIC_REGISTERED = "static_registered"
WEBSOCKET_REGISTERED = "websocket_registered"
STATIC_URL = "/fluvalble"
STORAGE_KEY = "fluvalble_schedules"
STORAGE_VERSION = 1

CHANNEL_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Optional("red"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("green"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("blue"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("white"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("channel_5"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("transition", default=0): vol.All(int, vol.Range(min=0, max=86400)),
        vol.Optional("step_seconds", default=30): vol.All(int, vol.Range(min=1, max=3600)),
    }
)

PREVIEW_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("points"): list,
        vol.Optional("duration", default=60): vol.All(int, vol.Range(min=1, max=3600)),
        vol.Optional("step_seconds", default=2): vol.All(int, vol.Range(min=1, max=300)),
    }
)

STOP_PREVIEW_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
    }
)

SCHEDULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("points"): list,
        vol.Optional("mode"): vol.In(["manual", "auto", "professional"]),
    }
)

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.LIGHT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fluval Aquarium LED from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    await _register_static_paths(hass)
    _register_websocket(hass)
    _register_services(hass)
    mac_raw = entry.data.get(CONF_MAC)
    # HA's Bluetooth stack uses uppercase MACs internally. Normalize here
    # so the address filter in async_register_callback matches correctly,
    # even if an older config entry stored it as lowercase.
    mac = mac_raw.strip().upper() if mac_raw else None

    if not mac:
        _LOGGER.error("Config entry %s has no MAC address", entry.entry_id)
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
    last_discovery_log = 0.0

    def log_discovery_update(message: str, service_info, change) -> None:
        """Throttle noisy BLE advertisement debug logs."""
        nonlocal last_discovery_log
        now = monotonic()
        if now - last_discovery_log < DISCOVERY_LOG_INTERVAL:
            return

        last_discovery_log = now
        _LOGGER.debug(message, service_info.device, change)

    def _create_device(
        service_info: bluetooth.BluetoothServiceInfoBleak,
    ) -> Device:
        """Instantiate Device and add entities for any platforms that are already loaded."""
        _LOGGER.debug("Creating device for %s", mac)
        ping_interval = entry.options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL)
        active_time = entry.options.get(CONF_ACTIVE_TIME, DEFAULT_ACTIVE_TIME)
        device = Device(
            entry.title,
            service_info.device,
            service_info.advertisement,
            hass=hass,
            config_data=dict(entry.data),
            ping_interval=ping_interval,
            active_time=active_time,
        )
        entry_data["device"] = device

        # Retroactively add entities for platforms that set up before the
        # device was available (they stashed their add_entities callback).
        from .switch import create_entities as switch_entities  # noqa: PLC0415
        from .number import create_entities as number_entities  # noqa: PLC0415
        from .binary_sensor import create_entities as sensor_entities  # noqa: PLC0415
        from .select import create_entities as select_entities  # noqa: PLC0415
        from .light import create_entities as light_entities  # noqa: PLC0415
        from .button import create_entities as button_entities  # noqa: PLC0415
        from .sensor import create_entities as diagnostics_entities  # noqa: PLC0415

        factories = {
            Platform.SWITCH: switch_entities,
            Platform.NUMBER: number_entities,
            Platform.BINARY_SENSOR: sensor_entities,
            Platform.SELECT: select_entities,
            Platform.LIGHT: light_entities,
            Platform.BUTTON: button_entities,
            Platform.SENSOR: diagnostics_entities,
        }

        for platform, add_fn in entry_data["pending_add_entities"].items():
            factory = factories.get(platform)
            if factory:
                add_fn(factory(device))
        entry_data["pending_add_entities"].clear()

        _LOGGER.info("Device %s ready", mac)
        return device

    # Try Bluetooth cache first — instant entity setup if the light was just discovered.
    try:
        get_last = getattr(bluetooth, "async_last_service_info", None)
        if get_last:
            service_info = get_last(hass, mac, connectable=True)
            if service_info:
                _LOGGER.debug("Found %s in BLE cache, creating device now", mac)
                _create_device(service_info)
            else:
                _LOGGER.debug("%s not in BLE cache, will wait for advertisement", mac)
        else:
            _LOGGER.debug("async_last_service_info not available in this HA version")
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Error checking BLE cache for %s, will wait for advertisement",
            mac,
            exc_info=True,
        )

    # Always forward platform setup — platforms will either create entities
    # immediately (device exists) or stash their add_entities callback
    # (device pending) so _create_device can populate them later.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        log_discovery_update("Fluval BLE update: %s %s", service_info, change)
        if device := entry_data["device"]:
            device.update_ble(service_info.device, service_info.advertisement)
            return

        # First time seeing the device via BLE advertisement
        _LOGGER.debug("BLE advertisement received for %s — creating device", mac)
        _create_device(service_info)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            update_ble,
            {"address": mac},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            lambda now: hass.loop.call_soon_threadsafe(
                lambda: hass.async_create_task(_async_apply_auto_schedule(hass, entry.entry_id))
            ),
            timedelta(minutes=1),
        )
    )

    _LOGGER.debug("Setup complete for %s — waiting for BLE", mac)
    return True


async def _register_static_paths(hass: HomeAssistant) -> None:
    """Serve the Fluval BLE Lovelace card from the integration directory."""
    if hass.data[DOMAIN].get(STATIC_REGISTERED):
        return

    static_path = str(Path(__file__).parent / "www")
    register_one = getattr(hass.http, "async_register_static_path", None)
    register_many = getattr(hass.http, "async_register_static_paths", None)

    try:
        if register_one is not None:
            result = register_one(STATIC_URL, static_path, cache_headers=False)
            if inspect.isawaitable(result):
                await result
        elif register_many is not None:
            from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

            result = register_many([StaticPathConfig(STATIC_URL, static_path, cache_headers=False)])
            if inspect.isawaitable(result):
                await result
        else:
            _LOGGER.warning(
                "Unable to register Fluval BLE Lovelace card static path; "
                "copy fluvalble-schedule-card.js to /config/www manually"
            )
            return
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "Unable to register Fluval BLE Lovelace card static path; "
            "integration will continue without the built-in card resource",
            exc_info=True,
        )
        return

    hass.data[DOMAIN][STATIC_REGISTERED] = True


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.data[DOMAIN].get(SERVICES_REGISTERED):
        return

    def get_device(call: ServiceCall) -> Device:
        entry_id = call.data.get("entry_id")
        mac = (call.data.get("mac") or "").upper()
        for candidate_entry_id, entry_data in hass.data[DOMAIN].items():
            if candidate_entry_id in {
                SERVICES_REGISTERED,
                STATIC_REGISTERED,
                WEBSOCKET_REGISTERED,
            }:
                continue
            device = entry_data.get("device") if isinstance(entry_data, dict) else None
            if device is None:
                continue
            if entry_id and candidate_entry_id != entry_id:
                continue
            if mac and device.mac.upper() != mac:
                continue
            return device
        raise HomeAssistantError("No matching Fluval BLE device is ready")

    def get_entry_id(data: dict) -> str:
        entry_id = data.get("entry_id")
        mac = (data.get("mac") or "").upper()
        for candidate_entry_id, entry_data in hass.data[DOMAIN].items():
            if candidate_entry_id in {
                SERVICES_REGISTERED,
                STATIC_REGISTERED,
                WEBSOCKET_REGISTERED,
            }:
                continue
            if not isinstance(entry_data, dict):
                continue
            device = entry_data.get("device")
            if entry_id and candidate_entry_id == entry_id:
                return candidate_entry_id
            if mac and device is not None and device.mac.upper() == mac:
                return candidate_entry_id

        for entry in hass.config_entries.async_entries(DOMAIN):
            entry_mac = (entry.data.get(CONF_MAC) or "").upper()
            if entry_id and entry.entry_id == entry_id:
                return entry.entry_id
            if mac and entry_mac == mac:
                return entry.entry_id

        if not entry_id and not mac:
            entries = hass.config_entries.async_entries(DOMAIN)
            if entries:
                return entries[0].entry_id

        raise HomeAssistantError("No matching Fluval BLE config entry was found")

    async def async_set_channels(call: ServiceCall) -> None:
        device = get_device(call)
        values = {
            channel: call.data[color]
            for channel, color in (
                ("channel_1", "red"),
                ("channel_2", "green"),
                ("channel_3", "blue"),
                ("channel_4", "white"),
                ("channel_5", "channel_5"),
            )
            if color in call.data
        }
        if not values:
            raise HomeAssistantError("At least one channel value is required")
        await device.async_set_channels(
            values,
            transition=call.data["transition"],
            step_seconds=call.data["step_seconds"],
        )

    async def async_preview_schedule(call: ServiceCall) -> None:
        device = get_device(call)
        await device.async_preview_schedule(
            call.data["points"],
            duration=call.data["duration"],
            step_seconds=call.data["step_seconds"],
        )

    async def async_stop_preview(call: ServiceCall) -> None:
        device = get_device(call)
        await device.async_stop_preview()

    async def async_save_schedule(call: ServiceCall) -> None:
        entry_id = get_entry_id(call.data)
        await _async_save_schedule(
            hass,
            entry_id,
            call.data["points"],
            mode=call.data.get("mode"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHANNELS,
        async_set_channels,
        schema=CHANNEL_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREVIEW_SCHEDULE,
        async_preview_schedule,
        schema=PREVIEW_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_PREVIEW,
        async_stop_preview,
        schema=STOP_PREVIEW_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_SCHEDULE,
        async_save_schedule,
        schema=SCHEDULE_SERVICE_SCHEMA,
    )
    hass.data[DOMAIN][SERVICES_REGISTERED] = True


def _register_websocket(hass: HomeAssistant) -> None:
    """Register websocket commands for Lovelace schedule loading."""
    if hass.data[DOMAIN].get(WEBSOCKET_REGISTERED):
        return

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "fluvalble/get_schedule",
            vol.Optional("entry_id"): str,
            vol.Optional("mac"): str,
        }
    )
    @websocket_api.async_response
    async def websocket_get_schedule(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
    ) -> None:
        """Return the saved schedule for a Fluval entry."""
        try:
            entry_id = _entry_id_from_message(hass, msg)
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "not_found", str(err))
            return

        saved = await _async_load_schedule_data(hass, entry_id)
        connection.send_result(
            msg["id"],
            {
                "entry_id": entry_id,
                "points": saved.get("points"),
                "mode": saved.get("mode", "manual"),
            },
        )

    websocket_api.async_register_command(hass, websocket_get_schedule)
    hass.data[DOMAIN][WEBSOCKET_REGISTERED] = True


def _entry_id_from_message(hass: HomeAssistant, msg: dict) -> str:
    """Resolve a websocket message target to a config entry id."""
    entry_id = msg.get("entry_id")
    mac = (msg.get("mac") or "").upper()

    for entry in hass.config_entries.async_entries(DOMAIN):
        entry_mac = (entry.data.get(CONF_MAC) or "").upper()
        if entry_id and entry.entry_id == entry_id:
            return entry.entry_id
        if mac and entry_mac == mac:
            return entry.entry_id

    if not entry_id and not mac:
        entries = hass.config_entries.async_entries(DOMAIN)
        if entries:
            return entries[0].entry_id

    raise HomeAssistantError("No matching Fluval BLE config entry was found")


async def _async_load_schedule(hass: HomeAssistant, entry_id: str) -> list | None:
    """Load one saved schedule from storage."""
    return (await _async_load_schedule_data(hass, entry_id)).get("points")


async def _async_load_schedule_data(hass: HomeAssistant, entry_id: str) -> dict:
    """Load one saved schedule record from storage."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}
    schedules = data.get("schedules", {})
    saved = schedules.get(entry_id)
    if isinstance(saved, list):
        return {"points": saved, "mode": "manual"}
    if isinstance(saved, dict):
        return {
            "points": saved.get("points"),
            "mode": saved.get("mode", "manual"),
        }
    return {"points": None, "mode": "manual"}


async def _async_save_schedule(
    hass: HomeAssistant,
    entry_id: str,
    points: list,
    *,
    mode: str | None = None,
) -> None:
    """Save one schedule to storage."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}
    schedules = data.setdefault("schedules", {})
    existing = schedules.get(entry_id)
    existing_mode = existing.get("mode", "manual") if isinstance(existing, dict) else "manual"
    schedules[entry_id] = {
        "points": points,
        "mode": mode or existing_mode,
    }
    await store.async_save(data)


async def _async_apply_auto_schedule(hass: HomeAssistant, entry_id: str) -> None:
    """Apply the saved schedule for one entry when HA schedule mode is auto."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not isinstance(entry_data, dict):
        return

    device = entry_data.get("device")
    if device is None:
        return

    saved = await _async_load_schedule_data(hass, entry_id)
    if saved.get("mode") != "auto" or not saved.get("points"):
        return

    # Use HA local time through dt_util to respect the configured timezone.
    from homeassistant.util import dt as dt_util  # noqa: PLC0415

    local_now = dt_util.now()
    minute = (local_now.hour * 60) + local_now.minute
    points = device._normalize_schedule_points(saved["points"])  # noqa: SLF001
    channels = device._interpolate_schedule(points, minute)  # noqa: SLF001
    if all(int(device.values.get(channel, -1)) == value for channel, value in channels.items()):
        return

    await device.async_set_channels(channels)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data and entry_data.get("device"):
            await entry_data["device"].client.stop()

    return unload_ok
