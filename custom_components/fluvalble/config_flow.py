"""Config flow for Fluval Aquarium LED integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant import config_entries
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .core import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Fluval LED GATT service UUID (advertised by the light)
FLUVAL_SERVICE_UUID = "00001002-0000-1000-8000-00805F9B34FB"

# Bluetooth address filter expects lowercase with colons (e.g. aa:bb:cc:dd:ee:ff)
MAC_REGEX = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2})$")

MANUAL_ENTRY = "__manual__"


def normalize_mac(mac: str) -> str:
    """Normalize MAC to lowercase colon-separated for HA Bluetooth API."""
    mac = mac.strip().lower().replace("-", ":").replace(" ", "")
    if len(mac) == 12 and mac.isalnum():
        return ":".join(mac[i : i + 2] for i in range(0, 12, 2))
    if MAC_REGEX.match(mac):
        return mac.lower()
    return mac


def _device_display_name(service_info: bluetooth.BluetoothServiceInfoBleak) -> str:
    """Build a display name for a discovered device."""
    name = (
        (service_info.advertisement.local_name or service_info.name or "")
        .strip()
        or "Unknown"
    )
    return f"{name} ({service_info.address})"


async def _get_discovered_devices(hass: HomeAssistant) -> list[bluetooth.BluetoothServiceInfoBleak]:
    """Return list of connectable BLE devices, preferring Fluval lights."""
    try:
        all_devices = bluetooth.async_discovered_service_info(hass, connectable=True)
    except Exception:  # noqa: BLE001
        return []
    # Prefer devices that advertise the Fluval service or have "Fluval" in the name
    fluval_devices: list[bluetooth.BluetoothServiceInfoBleak] = []
    other_devices: list[bluetooth.BluetoothServiceInfoBleak] = []
    for info in all_devices:
        name = (info.advertisement.local_name or info.name or "").lower()
        uuids = list(info.advertisement.service_uuids) if info.advertisement.service_uuids else []
        if FLUVAL_SERVICE_UUID.lower() in [u.lower() for u in uuids] or "fluval" in name:
            fluval_devices.append(info)
        else:
            other_devices.append(info)
    # Fluval first, then others (so user sees likely candidates at top)
    return fluval_devices + other_devices


class PlaceholderHub:
    """Placeholder for validation (TODO: replace with real BLE connect test)."""

    def __init__(self, mac: str) -> None:
        self.mac = mac

    async def connect_test(self) -> bool:
        return True


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    mac = normalize_mac(data[CONF_MAC])
    if not MAC_REGEX.match(mac):
        raise CannotConnect
    hub = PlaceholderHub(mac)
    if not await hub.connect_test():
        raise CannotConnect
    return {"title": f"Fluval {mac}", CONF_MAC: mac}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fluval Aquarium LED."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._discovered_devices: list[bluetooth.BluetoothServiceInfoBleak] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: pick from discovered devices or enter MAC manually."""
        configured = {
            entry.data.get(CONF_MAC)
            for entry in self._async_current_entries()
            if entry.data.get(CONF_MAC)
        }
        configured_normalized = {normalize_mac(m) for m in configured if m}

        if user_input is not None:
            selected = user_input.get(CONF_MAC)
            if selected == MANUAL_ENTRY:
                return await self.async_step_manual()
            mac = normalize_mac(selected)
            if MAC_REGEX.match(mac):
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                try:
                    info = await validate_input(self.hass, {CONF_MAC: mac})
                except CannotConnect:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=vol.Schema({vol.Required(CONF_MAC): vol.In(self._device_options(configured_normalized))}),
                        errors={"base": "cannot_connect"},
                    )
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    return self.async_show_form(
                        step_id="user",
                        data_schema=vol.Schema({vol.Required(CONF_MAC): vol.In(self._device_options(configured_normalized))}),
                        errors={"base": "unknown"},
                    )
                return self.async_create_entry(title=info["title"], data={CONF_MAC: info[CONF_MAC]})

        self._discovered_devices = await _get_discovered_devices(self.hass)
        options = self._device_options(configured_normalized)
        # If no discoverable devices (or all already configured), go straight to manual entry
        if len(options) <= 1:
            return await self.async_step_manual()

        schema = vol.Schema({vol.Required(CONF_MAC): vol.In(options)})
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"count": str(len([o for o in options if o != MANUAL_ENTRY]))},
        )

    def _device_options(self, configured_normalized: set[str]) -> dict[str, str]:
        """Build dropdown options: value -> label. Exclude already configured."""
        options: dict[str, str] = {}
        for info in self._discovered_devices:
            mac = normalize_mac(info.address)
            if mac in configured_normalized:
                continue
            options[mac] = _device_display_name(info)
        options[MANUAL_ENTRY] = "My device isn't in the list — enter MAC address manually"
        return options

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual MAC address entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = normalize_mac(user_input[CONF_MAC])
            if MAC_REGEX.match(mac):
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
            try:
                info = await validate_input(self.hass, {**user_input, CONF_MAC: mac})
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data={CONF_MAC: info[CONF_MAC]})

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
            errors=errors,
            description_placeholders={"mac_example": "AA:BB:CC:DD:EE:FF"},
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
