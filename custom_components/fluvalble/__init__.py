"""The Fluval Aquarium LED integration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
import re
from time import monotonic
from typing import Any, TypeAlias

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, format_mac
from homeassistant.helpers.storage import Store
from .core import (
    CONF_ACTIVE_TIME,
    CONF_PING_INTERVAL,
    DEFAULT_ACTIVE_TIME,
    DEFAULT_PING_INTERVAL,
    DOMAIN,
)
from .core.device import Device
from .core.discovery import CONF_MODEL, CONF_PRODUCT_ID
from .core.effects import EFFECT_NONE, WEATHER_EFFECTS, effect_name

try:
    from homeassistant.config_entries import ConfigEntryState
except ImportError:  # pragma: no cover - stubbed test environments
    ConfigEntryState = None  # type: ignore[misc, assignment]

_LOGGER = logging.getLogger(__name__)


@dataclass
class FluvalRuntimeData:
    """Runtime state for one Fluval config entry (stored on entry.runtime_data)."""

    device: Device | None = None
    pending_add_entities: dict[Platform, Any] = field(default_factory=dict)
    background_tasks: set[asyncio.Task] = field(default_factory=set, repr=False)


try:
    FluvalConfigEntry: TypeAlias = ConfigEntry[FluvalRuntimeData]
except TypeError:  # pragma: no cover - stubbed test ConfigEntry isn't generic
    FluvalConfigEntry: TypeAlias = ConfigEntry  # type: ignore[misc,assignment]


def _runtime_device(entry_data: Any) -> Device | None:
    """Return the device from runtime_data or legacy hass.data dict entries."""
    if isinstance(entry_data, FluvalRuntimeData):
        return entry_data.device
    if isinstance(entry_data, dict):
        return entry_data.get("device")
    return None


@callback
def _sync_firmware_version_to_device_registry(hass: HomeAssistant, device: Device) -> None:
    """Publish fixture-reported firmware through standard HA device info."""
    if device.firmware_version is None:
        return

    registry = dr.async_get(hass)
    registry_device = registry.async_get_device(identifiers={(DOMAIN, device.mac.upper())})
    if registry_device is None or registry_device.sw_version == device.firmware_version:
        return
    registry.async_update_device(registry_device.id, sw_version=device.firmware_version)


@callback
def _sync_product_identity(hass: HomeAssistant, entry: FluvalConfigEntry, device: Device) -> None:
    """Persist an APK product identity and publish its model to Home Assistant."""
    if device.product_id is None:
        return

    data = dict(entry.data)
    changed = data.get(CONF_PRODUCT_ID) != device.product_id
    if changed:
        data[CONF_PRODUCT_ID] = device.product_id
    if device.model_name and data.get(CONF_MODEL) != device.model_name:
        data[CONF_MODEL] = device.model_name
        changed = True
    if changed:
        hass.config_entries.async_update_entry(entry, data=data)

    registry = dr.async_get(hass)
    registry_device = registry.async_get_device(identifiers={(DOMAIN, device.mac.upper())})
    if registry_device is not None and registry_device.model != device.model_name:
        registry.async_update_device(registry_device.id, model=device.model_name)


DISCOVERY_LOG_INTERVAL = 5
SERVICE_SET_CHANNELS = "set_channels"
SERVICE_PREVIEW_SCHEDULE = "preview_schedule"
SERVICE_PREVIEW_NATIVE_SCHEDULE = "preview_native_schedule"
SERVICE_STOP_PREVIEW = "stop_preview"
SERVICE_SAVE_SCHEDULE = "save_schedule"
SERVICE_SET_NATIVE_AUTO_SCHEDULE = "set_native_auto_schedule"
SERVICE_SET_NATIVE_PRO_SCHEDULE = "set_native_pro_schedule"
SERVICE_SET_NATIVE_EFFECT_SCHEDULE = "set_native_effect_schedule"
SERVICE_RECALL_MANUAL_PRESET = "recall_manual_preset"
SERVICE_SAVE_MANUAL_PRESET = "save_manual_preset"
SERVICES_REGISTERED = "services_registered"
STATIC_REGISTERED = "static_registered"
WEBSOCKET_REGISTERED = "websocket_registered"
STATIC_URL = "/fluvalble"
STORAGE_KEY = "fluvalble_schedules"
STORAGE_VERSION = 1
EFFECT_CATALOG = "apk-weather-mesh-v1"
LEGACY_FOUR_EFFECT_NAMES = {
    "Thunderstorm": "Lightning",
    "Lightning": "Sun and lightning",
    "Sun and lightning": "Partly cloudy",
    "Colour cycle": "Crescent moon",
}
LEGACY_SCHEDULE_MIGRATION_RETRY_SECONDS = 5
LEGACY_SCHEDULE_MIGRATION_RETRY_COUNT = 12
MAX_SCHEDULE_POINTS = 12
MIN_NATIVE_PRO_SCHEDULE_POINTS = 4
MAX_NATIVE_PRO_SCHEDULE_POINTS = 12
NATIVE_SCHEDULE_CHANNELS = tuple(f"channel_{index}" for index in range(1, 6))
LEGACY_SCHEDULE_CHANNELS = ("red", "green", "blue", "white", "channel_5")
LEGACY_PLANT_PRO_CHANNELS = ("red", "blue", "cool_white", "warm_white", "amber")
SCHEDULE_POINT_FIELDS = {"time", *NATIVE_SCHEDULE_CHANNELS, *LEGACY_SCHEDULE_CHANNELS}
NATIVE_EFFECT_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
RETIRED_CHANNEL_SUFFIXES = tuple(f"_channel_{index}" for index in range(1, 6))
RETIRED_DIAGNOSTIC_SUFFIXES = (
    "_diagnostics",
    "_refresh_diagnostics",
    "_test_led_channels",
)
RETIRED_ENTITY_DOMAINS = frozenset({Platform.NUMBER.value})
RETIRED_SWITCH_SUFFIXES = ("_led_on_off",)
RETIRED_SELECT_SUFFIXES = ("_schedule_mode",)


def _validate_schedule_points(points: object) -> list[dict]:
    """Validate untrusted schedule data before storing it or driving BLE writes."""
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_SCHEDULE_POINTS:
        raise vol.Invalid(f"Schedule must contain 2 to {MAX_SCHEDULE_POINTS} points")

    validated = []
    for point in points:
        if not isinstance(point, dict) or set(point) - SCHEDULE_POINT_FIELDS:
            raise vol.Invalid("Each schedule point must contain only supported fields")
        time_value = point.get("time")
        if not isinstance(time_value, str) or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value) is None:
            raise vol.Invalid("Schedule times must use HH:MM in the 24-hour range")

        validated_point: dict[str, str | int] = {"time": time_value}
        for channel, legacy_channel in zip(
            NATIVE_SCHEDULE_CHANNELS,
            LEGACY_SCHEDULE_CHANNELS,
            strict=True,
        ):
            if channel != legacy_channel and channel in point and legacy_channel in point:
                raise vol.Invalid(f"{channel} and its legacy alias {legacy_channel} cannot both be present")
            value = point.get(channel, point.get(legacy_channel, 0))
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise vol.Invalid(f"{channel} must be an integer from 0 to 100")
            validated_point[channel] = value
        validated.append(validated_point)

    return validated


def _normalize_saved_schedule_points(points: object) -> list[dict] | None:
    """Migrate a valid saved RGB-style schedule to canonical channel keys."""
    if not isinstance(points, list):
        return None
    try:
        return _validate_schedule_points(points)
    except vol.Invalid:
        # Preserve historical malformed storage for inspection; every fixture
        # write is still protected by the service validator.
        return points


def _validate_time(value: object, label: str) -> tuple[int, int]:
    """Validate one user-facing 24-hour time and return its numeric parts."""
    if not isinstance(value, str) or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
        raise vol.Invalid(f"{label} must use HH:MM in the 24-hour range")
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _validate_native_levels(value: object, label: str) -> list[int]:
    """Validate canonical levels or the previous Plant-specific aliases."""
    if not isinstance(value, dict):
        raise vol.Invalid(f"{label} must contain all five fixture channels")
    if set(value) == set(NATIVE_SCHEDULE_CHANNELS):
        source_channels = NATIVE_SCHEDULE_CHANNELS
    elif set(value) == set(LEGACY_PLANT_PRO_CHANNELS):
        source_channels = LEGACY_PLANT_PRO_CHANNELS
    else:
        raise vol.Invalid(f"{label} must contain exactly {', '.join(NATIVE_SCHEDULE_CHANNELS)}")
    levels = []
    for channel in source_channels:
        level = value[channel]
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 100:
            raise vol.Invalid(f"{label}.{channel} must be an integer from 0 to 100")
        levels.append(level)
    return levels


def _validate_native_auto_schedule(value: object) -> dict[str, Any]:
    """Validate a fixture-owned Auto schedule."""
    required = {"sunrise", "sunrise_ramp", "sunset", "sunset_ramp", "day", "night"}
    optional = {"sleep"}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - optional:
        raise vol.Invalid("Auto schedule fields are incomplete or unsupported")
    sunrise = _validate_time(value["sunrise"], "sunrise")
    sunset = _validate_time(value["sunset"], "sunset")
    sleep = None if value.get("sleep") in (None, "") else _validate_time(value["sleep"], "sleep")
    ramps = []
    for label in ("sunrise_ramp", "sunset_ramp"):
        ramp = value[label]
        if isinstance(ramp, bool) or not isinstance(ramp, int) or not 0 <= ramp <= 240:
            raise vol.Invalid(f"{label} must be an integer from 0 to 240 minutes")
        ramps.append(ramp)
    return {
        "sunrise": (*sunrise, ramps[0]),
        "sunset": (*sunset, ramps[1]),
        "sleep": sleep,
        "day_levels": _validate_native_levels(value["day"], "day"),
        "night_levels": _validate_native_levels(value["night"], "night"),
    }


def _validate_native_pro_points(value: object) -> list[dict[str, Any]]:
    """Validate fixture-owned Professional schedule points."""
    if (
        not isinstance(value, list)
        or not MIN_NATIVE_PRO_SCHEDULE_POINTS <= len(value) <= MAX_NATIVE_PRO_SCHEDULE_POINTS
    ):
        raise vol.Invalid(
            "Native Professional schedule must contain "
            f"{MIN_NATIVE_PRO_SCHEDULE_POINTS} to {MAX_NATIVE_PRO_SCHEDULE_POINTS} points"
        )
    points = []
    for point in value:
        if not isinstance(point, dict) or "time" not in point:
            raise vol.Invalid("Each Professional point must contain time and all five channels")
        hour, minute = _validate_time(point["time"], "point time")
        levels = _validate_native_levels({key: item for key, item in point.items() if key != "time"}, "point")
        points.append({"hour": hour, "minute": minute, "levels": levels})
    return points


def _validate_native_effect_windows(value: object) -> list[dict[str, Any]]:
    """Validate fixture-owned timed weather-effect windows."""
    if not isinstance(value, list) or len(value) > 7:
        raise vol.Invalid("Fluval controllers support at most seven timed effect windows")
    windows = []
    used_weekdays: set[str] = set()
    supported = {"start", "end", "effect", "weekdays", "enabled"}
    for window in value:
        if not isinstance(window, dict) or not {"start", "end", "effect"}.issubset(window):
            raise vol.Invalid("Each effect window requires start, end, and effect")
        if set(window) - supported:
            raise vol.Invalid("Effect window contains unsupported fields")
        start_hour, start_minute = _validate_time(window["start"], "effect start")
        end_hour, end_minute = _validate_time(window["end"], "effect end")
        if (start_hour, start_minute, end_hour, end_minute) == (0, 0, 0, 0):
            raise vol.Invalid("effect start and end cannot both be 00:00")
        effect = window["effect"]
        if effect not in WEATHER_EFFECTS:
            raise vol.Invalid(f"effect must be one of {', '.join(WEATHER_EFFECTS)}")
        weekdays = window.get("weekdays", list(NATIVE_EFFECT_WEEKDAYS))
        if not isinstance(weekdays, list) or any(day not in NATIVE_EFFECT_WEEKDAYS for day in weekdays):
            raise vol.Invalid("weekdays must contain valid lowercase weekday names")
        if len(set(weekdays)) != len(weekdays):
            raise vol.Invalid("weekdays must not contain duplicates")
        if not weekdays:
            raise vol.Invalid("each effect window requires at least one weekday")
        repeated_weekdays = used_weekdays.intersection(weekdays)
        if repeated_weekdays:
            raise vol.Invalid("each weekday can be assigned to only one effect window")
        used_weekdays.update(weekdays)
        enabled = window.get("enabled", True)
        if not isinstance(enabled, bool):
            raise vol.Invalid("enabled must be true or false")
        windows.append(
            {
                "start_hour": start_hour,
                "start_minute": start_minute,
                "end_hour": end_hour,
                "end_minute": end_minute,
                "effect": effect,
                "weekdays": [day in weekdays for day in NATIVE_EFFECT_WEEKDAYS],
                "enabled": enabled,
            }
        )
    return windows


def _validate_manual_preset_slot(value: object) -> int:
    """Validate the user-facing P1-P4 slot number."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
        raise vol.Invalid("Manual preset slot must be an integer from 1 to 4")
    return value


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
        vol.Required("points"): _validate_schedule_points,
        vol.Optional("duration", default=60): vol.All(int, vol.Range(min=1, max=3600)),
        vol.Optional("step_seconds", default=2): vol.All(int, vol.Range(min=1, max=300)),
    }
)

NATIVE_PREVIEW_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("minute"): vol.All(int, vol.Range(min=0, max=1439)),
        vol.Required("schedule_type"): vol.In(["auto", "professional"]),
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
        vol.Required("points"): _validate_schedule_points,
        vol.Optional("mode"): vol.In(["manual", "native"]),
    }
)

NATIVE_AUTO_SCHEDULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("schedule"): _validate_native_auto_schedule,
    }
)

NATIVE_PRO_SCHEDULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("points"): _validate_native_pro_points,
    }
)

NATIVE_EFFECT_SCHEDULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("windows"): _validate_native_effect_windows,
    }
)

MANUAL_PRESET_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Optional("mac"): str,
        vol.Required("slot"): _validate_manual_preset_slot,
    }
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.LIGHT,
]


async def async_setup_entry(hass: HomeAssistant, entry: FluvalConfigEntry) -> bool:
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

    # Discovery uses lowercase format_mac unique_ids. Migrate legacy uppercase
    # unique_ids so the same lamp is not rediscovered as a new device.
    desired_unique_id = format_mac(mac)
    if entry.unique_id != desired_unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=desired_unique_id)

    _migrate_legacy_registry_entries(hass, entry, mac)
    _cleanup_duplicate_devices(hass, entry, mac)

    runtime = FluvalRuntimeData()
    entry.runtime_data = runtime
    hass.data[DOMAIN][entry.entry_id] = runtime
    last_discovery_log = 0.0

    def create_runtime_task(coroutine) -> asyncio.Task:
        """Create a task owned by this config entry and track it for unload."""
        task = hass.async_create_task(coroutine)
        runtime.background_tasks.add(task)
        task.add_done_callback(runtime.background_tasks.discard)
        return task

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
            service_info.source,
            hass=hass,
            # Lamp profile is a fallback for fixtures whose APK product ID is
            # unavailable. A decoded product ID remains authoritative.
            config_data={**dict(entry.data), **dict(entry.options)},
            ping_interval=ping_interval,
            active_time=active_time,
        )
        device.entry_id = entry.entry_id
        runtime.device = device
        device.register_update(
            "firmware_version",
            lambda: _sync_firmware_version_to_device_registry(hass, device),
        )
        _sync_product_identity(hass, entry, device)

        # Retroactively add entities for platforms that set up before the
        # device was available (they stashed their add_entities callback).
        from .binary_sensor import create_entities as sensor_entities  # noqa: PLC0415
        from .select import create_entities as select_entities  # noqa: PLC0415
        from .light import create_entities as light_entities  # noqa: PLC0415
        from .button import create_entities as button_entities  # noqa: PLC0415
        from .sensor import create_entities as diagnostics_entities  # noqa: PLC0415
        from .switch import create_entities as switch_entities  # noqa: PLC0415

        factories = {
            Platform.BINARY_SENSOR: sensor_entities,
            Platform.SELECT: select_entities,
            Platform.LIGHT: light_entities,
            Platform.BUTTON: button_entities,
            Platform.SENSOR: diagnostics_entities,
            Platform.SWITCH: switch_entities,
        }

        for platform, add_fn in runtime.pending_add_entities.items():
            factory = factories.get(platform)
            if factory:
                add_fn(factory(device))
        runtime.pending_add_entities.clear()

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
        if device := runtime.device:
            device.update_ble(
                service_info.device,
                service_info.advertisement,
                service_info.source,
            )
            _sync_product_identity(hass, entry, device)
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

    if hass.state is CoreState.running:
        create_runtime_task(_async_migrate_legacy_auto_schedule(hass, entry.entry_id))
    else:
        startup_listener_fired = False

        @callback
        def _migrate_legacy_schedule_once(_event) -> None:
            nonlocal startup_listener_fired
            startup_listener_fired = True
            create_runtime_task(_async_migrate_legacy_auto_schedule(hass, entry.entry_id))

        remove_startup_listener = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            _migrate_legacy_schedule_once,
        )

        @callback
        def _remove_pending_startup_listener() -> None:
            if not startup_listener_fired:
                remove_startup_listener()

        entry.async_on_unload(_remove_pending_startup_listener)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.debug("Setup complete for %s — waiting for BLE", mac)
    return True


@callback
def _migrate_legacy_registry_entries(hass: HomeAssistant, entry: ConfigEntry, mac: str) -> None:
    """Remove retired entities and clear a MAC formerly stored as a serial."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        domain = str(getattr(entity, "domain", "") or str(entity.entity_id).partition(".")[0])
        unique_id = str(getattr(entity, "unique_id", ""))
        retired_platform = domain in RETIRED_ENTITY_DOMAINS
        retired_switch = domain == Platform.SWITCH.value and unique_id.endswith(RETIRED_SWITCH_SUFFIXES)
        retired_select = domain == Platform.SELECT.value and unique_id.endswith(RETIRED_SELECT_SUFFIXES)
        retired_channel = unique_id.endswith(RETIRED_CHANNEL_SUFFIXES)
        retired_diagnostics = unique_id.endswith(RETIRED_DIAGNOSTIC_SUFFIXES)
        if retired_platform or retired_switch or retired_select or retired_channel or retired_diagnostics:
            _LOGGER.info("Removing retired Fluval entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)

    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if getattr(device_entry, "serial_number", None) == mac:
            _LOGGER.info("Clearing MAC address from serial number for %s", device_entry.id)
            device_registry.async_update_device(device_entry.id, serial_number=None)


@callback
def _cleanup_duplicate_devices(hass: HomeAssistant, entry: ConfigEntry, mac: str) -> None:
    """Consolidate legacy registry rows into this entry's canonical BLE device."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    devices = list(dr.async_entries_for_config_entry(device_registry, entry.entry_id))
    if len(devices) < 2:
        return

    normalized_mac = format_mac(mac).lower()

    def _is_canonical(device_entry) -> bool:
        identifiers = getattr(device_entry, "identifiers", set()) or set()
        connections = getattr(device_entry, "connections", set()) or set()
        return any(
            str(domain) == DOMAIN and str(identifier).lower() == normalized_mac for domain, identifier in identifiers
        ) or any(
            str(connection_type) == CONNECTION_BLUETOOTH and str(address).lower() == normalized_mac
            for connection_type, address in connections
        )

    canonical = next((device_entry for device_entry in devices if _is_canonical(device_entry)), None)
    if canonical is None:
        return

    own_entities = list(er.async_entries_for_config_entry(entity_registry, entry.entry_id))
    all_entities = list(getattr(entity_registry, "entities", {}).values())
    for duplicate in devices:
        if duplicate.id == canonical.id:
            continue

        foreign_config_entries = set(getattr(duplicate, "config_entries", set()) or set()) - {entry.entry_id}
        foreign_entities = [
            entity
            for entity in all_entities
            if getattr(entity, "device_id", None) == duplicate.id
            and getattr(entity, "config_entry_id", None) != entry.entry_id
        ]
        if foreign_config_entries or foreign_entities:
            _LOGGER.warning(
                "Keeping duplicate Fluval device %s because another integration references it",
                duplicate.id,
            )
            continue

        for entity in own_entities:
            if getattr(entity, "device_id", None) == duplicate.id:
                entity_registry.async_update_entity(entity.entity_id, device_id=canonical.id)
        _LOGGER.info("Removing duplicate Fluval device registry entry %s", duplicate.id)
        device_registry.async_remove_device(duplicate.id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change so ping/active-time take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _register_static_paths(hass: HomeAssistant) -> None:
    """Serve the Fluval BLE Lovelace card from the integration directory."""
    if hass.data[DOMAIN].get(STATIC_REGISTERED):
        return

    static_path = str(Path(__file__).parent / "www")
    register_many = getattr(hass.http, "async_register_static_paths", None)
    register_one = getattr(hass.http, "async_register_static_path", None)

    try:
        if register_many is not None:
            from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

            result = register_many([StaticPathConfig(STATIC_URL, static_path, cache_headers=False)])
            if inspect.isawaitable(result):
                await result
        elif register_one is not None:
            # Compatibility fallback for older supported HA releases.
            result = register_one(STATIC_URL, static_path, cache_headers=False)
            if inspect.isawaitable(result):
                await result
        else:
            _LOGGER.warning(
                "Unable to register Fluval BLE Lovelace card static path; "
                "copy both fluvalble-schedule-card.js and "
                "fluvalble-spectrum-data.js to /config/www manually"
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
            device = _runtime_device(entry_data)
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
            device = _runtime_device(entry_data)
            if device is None:
                continue
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

    async def async_preview_native_schedule(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_preview_native_schedule(call.data["minute"], call.data["schedule_type"]):
            raise HomeAssistantError(device.command_error_message())

    async def async_stop_preview(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_stop_preview():
            raise HomeAssistantError(device.command_error_message())

    async def async_save_schedule(call: ServiceCall) -> None:
        entry_id = get_entry_id(call.data)
        mode = call.data.get("mode")
        if mode == "native" and not await _async_upload_native_schedule(hass, entry_id, call.data["points"]):
            device = _device_for_entry(hass, entry_id)
            raise HomeAssistantError(
                device.command_error_message() if device is not None else "Fluval BLE device is not loaded"
            )
        if mode == "manual" and not await _async_set_fixture_manual(hass, entry_id):
            device = _device_for_entry(hass, entry_id)
            raise HomeAssistantError(
                device.command_error_message() if device is not None else "Fluval BLE device is not loaded"
            )
        await _async_save_schedule(
            hass,
            entry_id,
            call.data["points"],
            mode=mode,
        )

    async def async_set_native_auto_schedule(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_set_native_auto_schedule(call.data["schedule"]):
            raise HomeAssistantError(device.diagnostics.get("last_error") or "Unable to store the native Auto schedule")

    async def async_set_native_pro_schedule(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_set_native_pro_schedule(call.data["points"]):
            raise HomeAssistantError(
                device.diagnostics.get("last_error") or "Unable to store the native Professional schedule"
            )

    async def async_set_native_effect_schedule(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_set_native_effect_schedule(call.data["windows"]):
            raise HomeAssistantError(
                device.diagnostics.get("last_error") or "Unable to store the native effect schedule"
            )
        await _async_save_effect_schedule(
            hass,
            get_entry_id(call.data),
            call.data["windows"],
        )

    async def async_recall_manual_preset(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_recall_manual_preset(call.data["slot"]):
            raise HomeAssistantError(device.command_error_message())

    async def async_save_manual_preset(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_save_manual_preset(call.data["slot"]):
            raise HomeAssistantError(device.command_error_message())

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
        SERVICE_PREVIEW_NATIVE_SCHEDULE,
        async_preview_native_schedule,
        schema=NATIVE_PREVIEW_SERVICE_SCHEMA,
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
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_NATIVE_AUTO_SCHEDULE,
        async_set_native_auto_schedule,
        schema=NATIVE_AUTO_SCHEDULE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_NATIVE_PRO_SCHEDULE,
        async_set_native_pro_schedule,
        schema=NATIVE_PRO_SCHEDULE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_NATIVE_EFFECT_SCHEDULE,
        async_set_native_effect_schedule,
        schema=NATIVE_EFFECT_SCHEDULE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RECALL_MANUAL_PRESET,
        async_recall_manual_preset,
        schema=MANUAL_PRESET_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_MANUAL_PRESET,
        async_save_manual_preset,
        schema=MANUAL_PRESET_SERVICE_SCHEMA,
    )
    hass.data[DOMAIN][SERVICES_REGISTERED] = True


def _format_fixture_minute(value: object) -> str | None:
    """Return one fixture time value as HH:MM."""
    if isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return value
    if isinstance(value, dict):
        hour = value.get("hour")
        minute = value.get("minute")
        if isinstance(hour, int) and isinstance(minute, int) and 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    return None


def _normalize_fixture_auto_schedule(schedule: object) -> dict[str, Any] | None:
    """Normalize classic, FACEBD, and Plant Pro Auto readback."""
    if not isinstance(schedule, dict):
        return None
    sunrise = _format_fixture_minute(schedule.get("sunrise"))
    sunset = _format_fixture_minute(schedule.get("sunset"))
    if sunrise is None or sunset is None:
        return None
    sunrise_value = schedule.get("sunrise")
    sunset_value = schedule.get("sunset")
    try:
        sunrise_ramp = int(
            sunrise_value.get("ramp", 0) if isinstance(sunrise_value, dict) else schedule.get("sunrise_ramp", 0)
        )
        sunset_ramp = int(
            sunset_value.get("ramp", 0) if isinstance(sunset_value, dict) else schedule.get("sunset_ramp", 0)
        )
    except (TypeError, ValueError):
        return None
    day_levels = schedule.get("day_levels")
    night_levels = schedule.get("night_levels")
    if (
        not isinstance(day_levels, list)
        or not isinstance(night_levels, list)
        or not 4 <= len(day_levels) <= 5
        or not 4 <= len(night_levels) <= 5
    ):
        return None
    try:
        normalized_day = [int(value) for value in day_levels]
        normalized_night = [int(value) for value in night_levels]
    except (TypeError, ValueError):
        return None
    if any(not 0 <= value <= 100 for value in (*normalized_day, *normalized_night)):
        return None
    return {
        "sunrise": sunrise,
        "sunrise_ramp": sunrise_ramp,
        "sunset": sunset,
        "sunset_ramp": sunset_ramp,
        "sleep": _format_fixture_minute(schedule.get("sleep")),
        "day_levels": normalized_day,
        "night_levels": normalized_night,
    }


def _normalize_fixture_pro_schedule(schedule: object) -> list[dict[str, Any]] | None:
    """Normalize native Professional readback for the schedule card."""
    if not isinstance(schedule, list) or not schedule:
        return None
    points: list[dict[str, Any]] = []
    for point in schedule:
        if not isinstance(point, dict):
            return None
        time_value = point.get("time")
        if time_value is None and isinstance(point.get("minute"), int):
            minute = point["minute"]
            if not 0 <= minute < 1440:
                return None
            time_value = f"{minute // 60:02d}:{minute % 60:02d}"
        time_text = _format_fixture_minute(time_value)
        if time_text is None:
            return None
        levels = point.get("levels")
        try:
            if isinstance(levels, list):
                if not 4 <= len(levels) <= 5:
                    return None
                channel_values = [int(value) for value in levels]
            else:
                channel_values = [int(point.get(f"channel_{index}", 0)) for index in range(1, 6)]
        except (TypeError, ValueError):
            return None
        if any(not 0 <= value <= 100 for value in channel_values):
            return None
        channel_values.extend([0] * (5 - len(channel_values)))
        points.append(
            {
                "time": time_text,
                **{channel: channel_values[index] for index, channel in enumerate(NATIVE_SCHEDULE_CHANNELS)},
            }
        )
    return points


def _normalize_effect_schedule(schedule: object) -> list[dict[str, Any]] | None:
    """Normalize saved, submitted, or fixture-read timed-effect windows for the card."""
    if not isinstance(schedule, list):
        return None
    windows: list[dict[str, Any]] = []
    for window in schedule:
        if not isinstance(window, dict):
            return None
        start = _format_fixture_minute(window.get("start"))
        if start is None and isinstance(window.get("start_hour"), int) and isinstance(window.get("start_minute"), int):
            start = _format_fixture_minute({"hour": window["start_hour"], "minute": window["start_minute"]})
        end = _format_fixture_minute(window.get("end"))
        if end is None and isinstance(window.get("end_hour"), int) and isinstance(window.get("end_minute"), int):
            end = _format_fixture_minute({"hour": window["end_hour"], "minute": window["end_minute"]})
        if start is None or end is None:
            return None

        effect = window.get("effect")
        if not isinstance(effect, str):
            effect_id = window.get("effect_id")
            effect = effect_name(effect_id) if isinstance(effect_id, int) else None
        if effect not in WEATHER_EFFECTS:
            return None

        weekdays = window.get("weekdays", list(NATIVE_EFFECT_WEEKDAYS))
        if (
            isinstance(weekdays, list)
            and len(weekdays) == len(NATIVE_EFFECT_WEEKDAYS)
            and all(isinstance(value, bool) for value in weekdays)
        ):
            weekday_names = [day for day, enabled in zip(NATIVE_EFFECT_WEEKDAYS, weekdays, strict=True) if enabled]
        elif isinstance(weekdays, list) and all(day in NATIVE_EFFECT_WEEKDAYS for day in weekdays):
            weekday_names = list(dict.fromkeys(weekdays))
        else:
            return None
        if not weekday_names:
            return None

        enabled = window.get("enabled", True)
        if not isinstance(enabled, bool):
            return None
        windows.append(
            {
                "start": start,
                "end": end,
                "effect": effect,
                "weekdays": weekday_names,
                "enabled": enabled,
            }
        )
    return windows


def _native_schedule_readback(device: Device | None) -> dict[str, Any]:
    """Return protocol-neutral native schedule readback for the dashboard."""
    if device is None:
        return {
            "available": False,
            "mode": None,
            "auto": None,
            "professional": None,
            "effects": None,
            "channels": [],
            "effect_options": [],
            "effect_readback_complete": False,
            "spectrum_profile": None,
            "protocol": None,
            "read_at": None,
        }
    auto = _normalize_fixture_auto_schedule(device.values.get("native_auto_schedule"))
    professional = _normalize_fixture_pro_schedule(device.values.get("native_pro_schedule"))
    effects = _normalize_effect_schedule(device.values.get("native_effect_schedule"))
    protocol_name = device.diagnostics.get("native_schedule_protocol")
    return {
        "available": auto is not None or professional is not None or effects is not None,
        "mode": device.values.get("mode"),
        "auto": auto,
        "professional": professional,
        "effects": effects,
        "channels": [device.entity_name(channel) for channel in device.numbers()],
        "effect_options": [effect for effect in device.effect_list() if effect != EFFECT_NONE],
        "effect_readback_complete": protocol_name in {"facebd", "plant_pro"},
        "spectrum_profile": device.spectrum_profile(),
        "protocol": protocol_name,
        "read_at": device.diagnostics.get("native_schedule_readback_at"),
    }


async def _async_schedule_payload(hass: HomeAssistant, entry_id: str, *, refresh: bool = False) -> dict[str, Any]:
    """Build the saved and fixture schedule payload for the dashboard."""
    device = _device_for_entry(hass, entry_id)
    refresh_ok = None
    if refresh:
        refresh_ok = bool(device is not None and await device.async_refresh_state())
    saved = await _async_load_schedule_data(hass, entry_id)
    effect_windows = saved.get("effect_windows")
    if (
        effect_windows is not None
        and device is not None
        and device.uses_four_effect_catalogue()
        and saved.get("effect_catalog") != EFFECT_CATALOG
    ):
        effect_windows = [
            {**window, "effect": LEGACY_FOUR_EFFECT_NAMES.get(window["effect"], window["effect"])}
            for window in effect_windows
        ]
    return {
        "entry_id": entry_id,
        "points": saved.get("points"),
        "mode": saved.get("mode", "manual"),
        "effect_windows": effect_windows,
        "fixture": _native_schedule_readback(device),
        "refresh_ok": refresh_ok,
    }


def _register_websocket(hass: HomeAssistant) -> None:
    """Register websocket commands for Lovelace schedule loading."""
    if hass.data[DOMAIN].get(WEBSOCKET_REGISTERED):
        return

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "fluvalble/get_schedule",
            vol.Optional("entry_id"): str,
            vol.Optional("mac"): str,
            vol.Optional("refresh", default=False): bool,
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

        connection.send_result(
            msg["id"],
            await _async_schedule_payload(hass, entry_id, refresh=msg.get("refresh", False)),
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
        return {
            "points": _normalize_saved_schedule_points(saved),
            "mode": "manual",
            "effect_windows": None,
            "effect_catalog": None,
        }
    if isinstance(saved, dict):
        return {
            "points": _normalize_saved_schedule_points(saved.get("points")),
            "mode": saved.get("mode", "manual"),
            "effect_windows": _normalize_effect_schedule(saved.get("effect_windows")),
            "effect_catalog": saved.get("effect_catalog"),
        }
    return {"points": None, "mode": "manual", "effect_windows": None, "effect_catalog": None}


async def _async_save_schedule(
    hass: HomeAssistant,
    entry_id: str,
    points: list,
    *,
    mode: str | None = None,
) -> None:
    """Save one schedule to storage."""
    canonical_points = _normalize_saved_schedule_points(points)
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}
    schedules = data.setdefault("schedules", {})
    existing = schedules.get(entry_id)
    existing_mode = existing.get("mode", "manual") if isinstance(existing, dict) else "manual"
    existing_effect_windows = existing.get("effect_windows") if isinstance(existing, dict) else None
    existing_effect_catalog = existing.get("effect_catalog") if isinstance(existing, dict) else None
    schedule_mode = mode or existing_mode
    schedules[entry_id] = {
        "points": canonical_points,
        "mode": schedule_mode,
        "effect_windows": existing_effect_windows,
        "effect_catalog": existing_effect_catalog,
    }
    await store.async_save(data)

    runtime = hass.data.get(DOMAIN, {}).get(entry_id)
    device = _runtime_device(runtime)
    if device is not None:
        device.schedule_mode = schedule_mode
        for handler in device.updates_component:
            handler()


async def _async_save_effect_schedule(
    hass: HomeAssistant,
    entry_id: str,
    windows: list[dict[str, Any]],
) -> None:
    """Save the user-authored timed-effect windows without replacing channel schedules."""
    normalized = _normalize_effect_schedule(windows)
    if normalized is None:
        raise HomeAssistantError("Unable to normalize the timed-effect schedule")
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}
    schedules = data.setdefault("schedules", {})
    existing = schedules.get(entry_id)
    if isinstance(existing, list):
        existing = {"points": existing, "mode": "manual"}
    if not isinstance(existing, dict):
        existing = {"points": None, "mode": "manual"}
    schedules[entry_id] = {
        **existing,
        "points": _normalize_saved_schedule_points(existing.get("points")),
        "effect_windows": normalized,
        "effect_catalog": EFFECT_CATALOG,
    }
    await store.async_save(data)


def _device_for_entry(hass: HomeAssistant, entry_id: str) -> Device | None:
    """Return the currently loaded device for a config entry."""
    return _runtime_device(hass.data.get(DOMAIN, {}).get(entry_id))


async def async_set_schedule_mode(hass: HomeAssistant, entry_id: str, mode: str) -> None:
    """Set whether the saved curve is inactive or stored in the fixture."""
    if mode not in {"manual", "native"}:
        raise HomeAssistantError(f"Unsupported fixture schedule mode: {mode}")

    saved = await _async_load_schedule_data(hass, entry_id)
    points = saved.get("points") or []
    if mode == "native" and not await _async_upload_native_schedule(hass, entry_id, points):
        device = _device_for_entry(hass, entry_id)
        raise HomeAssistantError(
            device.command_error_message() if device is not None else "Fluval BLE device is not loaded"
        )
    if mode == "manual" and not await _async_set_fixture_manual(hass, entry_id):
        device = _device_for_entry(hass, entry_id)
        raise HomeAssistantError(
            device.command_error_message() if device is not None else "Fluval BLE device is not loaded"
        )
    await _async_save_schedule(hass, entry_id, points, mode=mode)


async def _async_upload_native_schedule(hass: HomeAssistant, entry_id: str, points: list[dict]) -> bool:
    """Upload an HA schedule as a fixture-native Professional curve once."""
    device = _device_for_entry(hass, entry_id)
    if device is None:
        return False
    if not MIN_NATIVE_PRO_SCHEDULE_POINTS <= len(points) <= MAX_NATIVE_PRO_SCHEDULE_POINTS:
        device.diagnostics.update(
            {
                "native_schedule_last_result": "invalid_point_count",
                "last_error": (
                    "Professional schedules require "
                    f"{MIN_NATIVE_PRO_SCHEDULE_POINTS} to {MAX_NATIVE_PRO_SCHEDULE_POINTS} points"
                ),
            }
        )
        return False
    ok = await device.async_set_native_pro_schedule(points, activate=True)
    device.diagnostics["native_schedule_last_result"] = "uploaded" if ok else "failed"
    return ok


async def _async_set_fixture_manual(hass: HomeAssistant, entry_id: str) -> bool:
    """Disable the onboard schedule by selecting the fixture's Manual mode."""
    device = _device_for_entry(hass, entry_id)
    if device is None:
        return False
    if device.values.get("mode") == "manual":
        return True
    return await device.async_select_option("mode", "manual")


async def _async_migrate_legacy_auto_schedule(hass: HomeAssistant, entry_id: str) -> None:
    """Convert an old HA-executed Auto curve to a native fixture schedule."""
    saved = await _async_load_schedule_data(hass, entry_id)
    if saved.get("mode") != "auto":
        return

    points = saved.get("points") or []
    if not MIN_NATIVE_PRO_SCHEDULE_POINTS <= len(points) <= MAX_NATIVE_PRO_SCHEDULE_POINTS:
        await _async_save_schedule(hass, entry_id, points, mode="manual")
        device = _device_for_entry(hass, entry_id)
        if device is not None:
            device.diagnostics.update(
                {
                    "native_schedule_last_result": "legacy_schedule_requires_edit",
                    "last_error": (
                        "Reduce the saved schedule to "
                        f"{MIN_NATIVE_PRO_SCHEDULE_POINTS}-{MAX_NATIVE_PRO_SCHEDULE_POINTS} points"
                    ),
                }
            )
        _LOGGER.warning(
            "Legacy Fluval schedule for entry %s has %s points; saved it as Manual because FluvalConnect supports %s-%s",
            entry_id,
            len(points),
            MIN_NATIVE_PRO_SCHEDULE_POINTS,
            MAX_NATIVE_PRO_SCHEDULE_POINTS,
        )
        return

    for attempt in range(LEGACY_SCHEDULE_MIGRATION_RETRY_COUNT):
        device = _device_for_entry(hass, entry_id)
        if device is not None:
            device.diagnostics["native_schedule_migration_attempt"] = attempt + 1
            if await _async_upload_native_schedule(hass, entry_id, points):
                await _async_save_schedule(hass, entry_id, points, mode="native")
                return
            if device.diagnostics.get("status") == "invalid_native_schedule":
                await _async_save_schedule(hass, entry_id, points, mode="manual")
                device.diagnostics["native_schedule_last_result"] = "legacy_schedule_requires_edit"
                _LOGGER.warning(
                    "Legacy Fluval schedule for entry %s has %s points; saved it as Manual because %s",
                    entry_id,
                    len(points),
                    device.diagnostics.get("last_error", "the fixture rejected its point count"),
                )
                return
        await asyncio.sleep(LEGACY_SCHEDULE_MIGRATION_RETRY_SECONDS)

    _LOGGER.warning(
        "Could not migrate legacy Fluval schedule for entry %s after %s seconds; it remains saved for a later retry",
        entry_id,
        LEGACY_SCHEDULE_MIGRATION_RETRY_SECONDS * LEGACY_SCHEDULE_MIGRATION_RETRY_COUNT,
    )


async def async_unload_entry(hass: HomeAssistant, entry: FluvalConfigEntry) -> bool:
    """Unload a config entry and tear down BLE / platform resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    runtime = getattr(entry, "runtime_data", None)
    if not isinstance(runtime, FluvalRuntimeData):
        runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    if isinstance(runtime, FluvalRuntimeData) and runtime.device is not None:
        runtime.device.cancel_reachability_refresh()
        if runtime.device.preview_task is not None or runtime.device.native_preview_active:
            await runtime.device.async_stop_preview()
        tasks = list(runtime.background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        runtime.background_tasks.clear()
        client = runtime.device.client
        if client is not None:
            try:
                await client.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Error stopping Fluval BLE client during unload", exc_info=True)

    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
