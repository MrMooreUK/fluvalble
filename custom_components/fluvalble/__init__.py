"""The Fluval Aquarium LED integration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
import re
from time import monotonic
from typing import Any, TypeAlias

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, CONF_MAC, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, format_mac
from .core import (
    CONFIG_ENTRY_VERSION,
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


def _action_validation_error(
    translation_key: str,
    **translation_placeholders: object,
) -> ServiceValidationError:
    """Return a translated error for invalid action input or targeting."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders={key: str(value) for key, value in translation_placeholders.items()} or None,
    )


def _action_error(
    translation_key: str,
    **translation_placeholders: object,
) -> HomeAssistantError:
    """Return a translated error for an action that could not be completed."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=translation_key,
        translation_placeholders={key: str(value) for key, value in translation_placeholders.items()} or None,
    )


def _command_error(message: str) -> HomeAssistantError:
    """Return the shared translated fixture-command failure."""
    return _action_error("command_failed", error=message)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate historical Fluval config entries to the current schema."""
    if entry.version == 1:
        _LOGGER.info("Migrating Fluval config entry %s from version 1 to 2", entry.entry_id)
        update_entry = hass.config_entries.async_update_entry
        parameters = inspect.signature(update_entry).parameters
        if "version" in parameters or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
            update_entry(entry, version=CONFIG_ENTRY_VERSION)
        else:
            # HA 2024.1 migrations mutate the version directly; the config
            # entry manager schedules persistence after migration succeeds.
            entry.version = CONFIG_ENTRY_VERSION
        return True

    return entry.version == CONFIG_ENTRY_VERSION


@dataclass
class FluvalRuntimeData:
    """Runtime state for one Fluval config entry."""

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


def entry_runtime_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> FluvalRuntimeData | None:
    """Return runtime data on both current and older Home Assistant releases."""
    runtime = getattr(entry, "runtime_data", None)
    if isinstance(runtime, FluvalRuntimeData):
        return runtime
    legacy_runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    return legacy_runtime if isinstance(legacy_runtime, FluvalRuntimeData) else None


def require_entry_runtime_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> FluvalRuntimeData:
    """Return initialized runtime data for an entity platform."""
    runtime = entry_runtime_data(hass, entry)
    if runtime is None:
        raise RuntimeError(f"Fluval runtime data is unavailable for config entry {entry.entry_id}")
    return runtime


def _store_entry_runtime_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: FluvalRuntimeData,
) -> None:
    """Store runtime data using APIs available on the running HA version."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    if hasattr(entry, "runtime_data"):
        entry.runtime_data = runtime


def _registry_device_for_entry(registry, entry: ConfigEntry, device: Device):
    """Resolve only this entry's device, including on older HA versions."""
    identifier = (DOMAIN, device.mac.upper())
    if lookup := getattr(registry, "async_get_device_by_identifier", None):
        return lookup(identifier, entry.entry_id)
    return next(
        (
            candidate
            for candidate in dr.async_entries_for_config_entry(registry, entry.entry_id)
            if identifier in candidate.identifiers
        ),
        None,
    )


@callback
def _sync_firmware_version_to_device_registry(hass: HomeAssistant, entry: ConfigEntry, device: Device) -> None:
    """Publish fixture-reported firmware through standard HA device info."""
    if device.firmware_version is None:
        return

    registry = dr.async_get(hass)
    registry_device = _registry_device_for_entry(registry, entry, device)
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
    registry_device = _registry_device_for_entry(registry, entry, device)
    if registry_device is not None and registry_device.model != device.model_name:
        registry.async_update_device(registry_device.id, model=device.model_name)


DISCOVERY_LOG_INTERVAL = 5
SERVICE_SET_CHANNELS = "set_channels"
SERVICE_RECALL_MANUAL_PRESET = "recall_manual_preset"
SERVICE_SAVE_MANUAL_PRESET = "save_manual_preset"
SERVICES_REGISTERED = "services_registered"
WEBSOCKET_REGISTERED = "websocket_registered"
NATIVE_SCHEDULE_CHANNELS = tuple(f"channel_{index}" for index in range(1, 6))
LEGACY_SCHEDULE_CHANNELS = ("red", "green", "blue", "white", "channel_5")
LEGACY_PLANT_PRO_CHANNELS = ("red", "blue", "cool_white", "warm_white", "amber")
NATIVE_EFFECT_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
SERVICE_TARGET_FIELDS = {
    vol.Optional(ATTR_DEVICE_ID): str,
    # Retain the two historical selectors for saved automations and the bundled
    # Lovelace cards. They are intentionally omitted from services.yaml so new
    # action-editor calls use Home Assistant's device picker.
    vol.Optional("entry_id"): str,
    vol.Optional("mac"): str,
}
RETIRED_DIAGNOSTIC_SUFFIXES = (
    "_connection_mode",
    "_diagnostics",
    "_refresh_diagnostics",
    "_test_led_channels",
    "_advertisement_source",
)
RETIRED_NUMBER_SUFFIXES = ("_transition",)
RETIRED_SWITCH_SUFFIXES = ("_led_on_off",)
RETIRED_SELECT_SUFFIXES = ("_schedule_mode",)


def _validate_manual_preset_slot(value: object) -> int:
    """Validate the user-facing P1-P4 slot number."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
        raise vol.Invalid("Manual preset slot must be an integer from 1 to 4")
    return value


CHANNEL_SERVICE_SCHEMA = vol.Schema(
    {
        **SERVICE_TARGET_FIELDS,
        vol.Optional("red"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("green"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("blue"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("white"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("channel_5"): vol.All(int, vol.Range(min=0, max=100)),
        vol.Optional("transition", default=0): vol.All(int, vol.Range(min=0, max=86400)),
        vol.Optional("step_seconds", default=30): vol.All(int, vol.Range(min=1, max=3600)),
    }
)

MANUAL_PRESET_SERVICE_SCHEMA = vol.Schema(
    {
        **SERVICE_TARGET_FIELDS,
        vol.Required("slot"): _validate_manual_preset_slot,
    }
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SCENE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.LIGHT,
]


def _migrate_connection_window(hass: HomeAssistant, entry: FluvalConfigEntry) -> int:
    """Replace legacy unlimited connections without touching fixture settings."""
    active_time = entry.options.get(CONF_ACTIVE_TIME, DEFAULT_ACTIVE_TIME)
    if active_time == 0:
        active_time = DEFAULT_ACTIVE_TIME
        hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_ACTIVE_TIME: active_time})
    return active_time


async def async_setup_entry(hass: HomeAssistant, entry: FluvalConfigEntry) -> bool:
    """Set up Fluval Aquarium LED from a config entry."""
    hass.data.setdefault(DOMAIN, {})
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

    active_time = _migrate_connection_window(hass, entry)
    _migrate_legacy_registry_entries(hass, entry, mac)
    _sync_connection_diagnostic_registry_entries(hass, entry)
    _cleanup_duplicate_devices(hass, entry, mac)

    runtime = FluvalRuntimeData()
    _store_entry_runtime_data(hass, entry, runtime)
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
            lambda: _sync_firmware_version_to_device_registry(hass, entry, device),
        )
        _sync_product_identity(hass, entry, device)

        # Retroactively add entities for platforms that set up before the
        # device was available (they stashed their add_entities callback).
        from .binary_sensor import create_entities as sensor_entities  # noqa: PLC0415
        from .select import create_entities as select_entities  # noqa: PLC0415
        from .scene import create_entities as scene_entities  # noqa: PLC0415
        from .light import create_entities as light_entities  # noqa: PLC0415
        from .number import create_entities as number_entities  # noqa: PLC0415
        from .button import create_entities as button_entities  # noqa: PLC0415
        from .sensor import create_entities as diagnostics_entities  # noqa: PLC0415
        from .switch import create_entities as switch_entities  # noqa: PLC0415

        factories = {
            Platform.BINARY_SENSOR: sensor_entities,
            Platform.SELECT: select_entities,
            Platform.SCENE: scene_entities,
            Platform.LIGHT: light_entities,
            Platform.NUMBER: number_entities,
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

    _register_legacy_options_reload(entry)

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
        retired_number = domain == Platform.NUMBER.value and unique_id.endswith(RETIRED_NUMBER_SUFFIXES)
        retired_switch = domain == Platform.SWITCH.value and unique_id.endswith(RETIRED_SWITCH_SUFFIXES)
        retired_select = domain == Platform.SELECT.value and unique_id.endswith(RETIRED_SELECT_SUFFIXES)
        retired_diagnostics = unique_id.endswith(RETIRED_DIAGNOSTIC_SUFFIXES)
        if retired_number or retired_switch or retired_select or retired_diagnostics:
            _LOGGER.info("Removing retired Fluval entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)

    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if getattr(device_entry, "serial_number", None) == mac:
            _LOGGER.info("Clearing MAC address from serial number for %s", device_entry.id)
            device_registry.async_update_device(device_entry.id, serial_number=None)


@callback
def _sync_connection_diagnostic_registry_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Restore diagnostics previously disabled by the integration, not the user."""
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = str(getattr(entity, "unique_id", ""))
        is_rssi = unique_id.endswith("_rssi")
        is_last_seen = unique_id.endswith("_last_seen")
        if not is_rssi and not is_last_seen:
            continue

        disabled_by = getattr(entity, "disabled_by", None)
        if disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity.entity_id, disabled_by=None)


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


def _register_legacy_options_reload(entry: ConfigEntry) -> None:
    """Retain options reloads on HA versions before OptionsFlowWithReload."""
    if hasattr(config_entries, "OptionsFlowWithReload"):
        return
    previous_options = dict(entry.options)

    async def options_updated(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        nonlocal previous_options
        current_options = dict(updated_entry.options)
        if current_options == previous_options:
            return
        previous_options = current_options
        await _async_update_listener(hass, updated_entry)

    entry.async_on_unload(entry.add_update_listener(options_updated))


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload options on Home Assistant versions without the reload helper."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""
    if hass.data[DOMAIN].get(SERVICES_REGISTERED):
        return

    def target_entry_ids(data: dict) -> set[str] | None:
        """Resolve a Home Assistant device target to its config entries."""
        device_id = data.get(ATTR_DEVICE_ID)
        if not device_id:
            return None
        device_entry = dr.async_get(hass).async_get(device_id)
        if device_entry is None:
            raise _action_validation_error("selected_device_missing")
        entry_ids = set(getattr(device_entry, "config_entries", set()) or set())
        if not entry_ids:
            raise _action_validation_error("device_not_managed")
        return entry_ids

    def loaded_device_candidates(data: dict, device_entry_ids: set[str] | None = None) -> list[tuple[str, Device]]:
        """Return loaded fixtures matching every supplied target identifier."""
        entry_id = data.get("entry_id")
        mac = (data.get("mac") or "").upper()
        if device_entry_ids is None and data.get(ATTR_DEVICE_ID):
            device_entry_ids = target_entry_ids(data)
        candidates: list[tuple[str, Device]] = []
        for candidate_entry_id, entry_data in hass.data[DOMAIN].items():
            if candidate_entry_id in {
                SERVICES_REGISTERED,
                WEBSOCKET_REGISTERED,
            }:
                continue
            device = _runtime_device(entry_data)
            if device is None:
                continue
            if device_entry_ids is not None and candidate_entry_id not in device_entry_ids:
                continue
            if entry_id and candidate_entry_id != entry_id:
                continue
            if mac and device.mac.upper() != mac:
                continue
            candidates.append((candidate_entry_id, device))
        return candidates

    def get_device(call: ServiceCall) -> Device:
        candidates = loaded_device_candidates(call.data)
        if len(candidates) == 1:
            return candidates[0][1]
        if len(candidates) > 1:
            raise _action_validation_error("select_one_light")
        raise _action_error("light_unavailable")

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
            raise _action_validation_error("channels_required")
        if not await device.async_set_channels(
            values,
            transition=call.data["transition"],
            step_seconds=call.data["step_seconds"],
        ):
            raise _command_error(device.command_error_message())

    async def async_recall_manual_preset(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_recall_manual_preset(call.data["slot"]):
            raise _command_error(device.command_error_message())

    async def async_save_manual_preset(call: ServiceCall) -> None:
        device = get_device(call)
        if not await device.async_save_manual_preset(call.data["slot"]):
            raise _command_error(device.command_error_message())

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHANNELS,
        async_set_channels,
        schema=CHANNEL_SERVICE_SCHEMA,
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
    """Normalize native Professional fixture readback."""
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
    """Normalize fixture-read timed-effect windows."""
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
    """Return protocol-neutral fixture-owned schedule readback."""
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
        "effect_readback_complete": protocol_name in {"facebd", "plant_pro", "spp"},
        "spectrum_profile": device.spectrum_profile(),
        "protocol": protocol_name,
        "read_at": device.diagnostics.get("native_schedule_readback_at"),
    }


async def _async_schedule_payload(hass: HomeAssistant, entry_id: str, *, refresh: bool = False) -> dict[str, Any]:
    """Return fixture-owned schedule readback without local draft storage."""
    device = _runtime_device(hass.data.get(DOMAIN, {}).get(entry_id))
    refresh_ok = None
    if refresh:
        refresh_ok = bool(device is not None and await device.async_refresh_state())
    return {
        "entry_id": entry_id,
        "fixture": _native_schedule_readback(device),
        "refresh_ok": refresh_ok,
    }


def _register_websocket(hass: HomeAssistant) -> None:
    """Register the retained schedule-readback API."""
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


async def async_unload_entry(hass: HomeAssistant, entry: FluvalConfigEntry) -> bool:
    """Unload a config entry and tear down BLE / platform resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    runtime = entry_runtime_data(hass, entry)

    if isinstance(runtime, FluvalRuntimeData):
        tasks = list(runtime.background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        runtime.background_tasks.clear()

    if isinstance(runtime, FluvalRuntimeData) and runtime.device is not None:
        runtime.device.cancel_reachability_refresh()
        await runtime.device.async_cancel_channel_mode_restore()
        client = runtime.device.client
        if client is not None:
            try:
                await client.stop()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Error stopping Fluval BLE client during unload", exc_info=True)

    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
