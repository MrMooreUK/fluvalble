"""Downloadable diagnostics for the Fluval Aquarium LED integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

try:
    from homeassistant.helpers.redact import async_redact_data
except ImportError:  # Home Assistant before the redaction helper moved
    from homeassistant.components.diagnostics import async_redact_data

from . import entry_runtime_data

REDACTED = "**REDACTED**"
TO_REDACT = {
    CONF_MAC,
    "address",
    "advertisement_name",
    "bluetooth_address",
    "configured_mac",
    "entry_id",
    "local_name",
    "mac",
    "manufacturer_data",
    "name",
    "path",
    "service_data",
    "source",
    "source_address",
    "source_name",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    return await _build_report(entry, hass)


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a device."""
    del device
    return await _build_report(entry, hass)


async def _build_report(
    entry: ConfigEntry,
    hass: HomeAssistant | None = None,
) -> dict[str, Any]:
    """Collect a non-disruptive runtime snapshot when the device is ready."""
    runtime = entry_runtime_data(hass, entry) if hass is not None else getattr(entry, "runtime_data", None)
    fluval = getattr(runtime, "device", None)
    if fluval is None:
        report: dict[str, Any] = {"status": "not_ready"}
    else:
        report = await fluval.async_collect_diagnostics()

    report["entry"] = {
        "entry_id": getattr(entry, "entry_id", None),
        "title": getattr(entry, "title", None),
        "unique_id": getattr(entry, "unique_id", None),
        "data": dict(getattr(entry, "data", {})),
        "options": dict(getattr(entry, "options", {})),
    }
    return _redact_diagnostics(report)


def _redact_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    """Use Home Assistant's recursive redaction helper."""
    return async_redact_data(value, TO_REDACT)
