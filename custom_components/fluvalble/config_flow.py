"""Config flow for Fluval Aquarium LED integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac

from .core import (
    CONF_ACTIVE_TIME,
    CONF_LAMP_PROFILE,
    CONF_PING_INTERVAL,
    DEFAULT_ACTIVE_TIME,
    DEFAULT_LAMP_PROFILE,
    DEFAULT_PING_INTERVAL,
    DOMAIN,
    LAMP_PROFILE_AQUASKY,
    LAMP_PROFILE_AQUASKY3,
    LAMP_PROFILE_AUTO,
    LAMP_PROFILE_MARINE,
    LAMP_PROFILE_PLANT,
    LAMP_PROFILE_PLANT_PRO,
)
from .core.discovery import discovery_metadata, is_likely_fluval

_LOGGER = logging.getLogger(__name__)

# Bluetooth address filter expects uppercase with colons (e.g. AA:BB:CC:DD:EE:FF)
MAC_REGEX = re.compile(
    r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2})$"
)

MANUAL_ENTRY = "__manual__"


def validate_active_time(value: Any) -> int:
    """Accept persistent mode (0) or a non-churning finite idle window."""
    try:
        active_time = int(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("Active connection window must be an integer") from err

    if active_time == 0 or 30 <= active_time <= 600:
        return active_time
    raise vol.Invalid("Active connection window must be 0 or between 30 and 600 seconds")


def normalize_mac(mac: str) -> str:
    """Normalize MAC to uppercase colon-separated for HA Bluetooth API.

    HA's habluetooth stack stores addresses in uppercase (e.g. AA:BB:CC:DD:EE:FF).
    The address filter in async_register_callback must match that format exactly.
    """
    mac = mac.strip().upper().replace("-", ":").replace(" ", "")
    if len(mac) == 12 and mac.isalnum():
        return ":".join(mac[i : i + 2] for i in range(0, 12, 2))
    if MAC_REGEX.match(mac):
        return mac.upper()
    return mac


def _format_bluetooth_mac(mac: str) -> str:
    """Normalize MAC with HA's helper, falling back to local normalization."""
    try:
        return format_mac(mac)
    except (TypeError, ValueError):
        return normalize_mac(mac)


def unique_id_from_mac(mac: str) -> str:
    """Stable config-entry unique_id for a MAC (always lowercase via format_mac).

    Discovery uses format_mac (lowercase). Manual setup used to store uppercase
    unique_ids, so HA treated the same lamp as a new discovery prompt.
    """
    return _format_bluetooth_mac(mac).lower()


def _is_likely_fluval(info: bluetooth.BluetoothServiceInfoBleak) -> bool:
    """True only for Fluval LED advertisements (strict — avoids discovery spam)."""
    try:
        adv = info.advertisement if info else None
        name = (adv.local_name if adv else None) or getattr(info, "name", None) or ""
    except Exception:  # noqa: BLE001
        return False
    return is_likely_fluval(name, adv)


def _device_display_name(
    service_info: bluetooth.BluetoothServiceInfoBleak,
    *,
    is_fluval: bool = False,
) -> str:
    """Build a clear display name so Fluval lights are easy to find in the list."""
    try:
        adv = service_info.advertisement if service_info else None
        name = ((adv.local_name if adv else None) or getattr(service_info, "name", None) or "").strip()
        address = getattr(service_info, "address", "") or ""
    except Exception:  # noqa: BLE001
        return "Unknown device"
    if not name or name.lower() == "unknown":
        name = "Fluval LED" if is_fluval else "Unknown device"
    return f"{name} ({address})"


async def _get_discovered_devices(
    hass: HomeAssistant,
) -> list[bluetooth.BluetoothServiceInfoBleak]:
    """Return only devices that look like Fluval lights (by service UUID or name)."""
    try:
        get_discovered = getattr(bluetooth, "async_discovered_service_info", None)
        if not get_discovered:
            return []
        all_devices = get_discovered(hass, connectable=True)
    except Exception:  # noqa: BLE001
        return []
    # Only show devices that advertise the Fluval service or have "Fluval" in the name,
    # so the list isn't full of random BLE devices that are hard to identify.
    return [info for info in all_devices if _is_likely_fluval(info)]


async def validate_input(hass: HomeAssistant, data: dict[str, Any], ble_name: str = "") -> dict[str, Any]:
    """Validate the user input and return cleaned config data."""
    mac = normalize_mac(data[CONF_MAC])
    if not MAC_REGEX.match(mac):
        raise InvalidFormat
    title = ble_name.strip() or f"Fluval {mac}"
    config_data = {CONF_MAC: mac}

    service_info = bluetooth.async_last_service_info(hass, mac, connectable=True)
    if service_info is None:
        service_info = bluetooth.async_last_service_info(hass, mac)
    if service_info is not None:
        title = ble_name.strip() or service_info.name or title
        config_data.update(
            discovery_metadata(
                service_info.name or ble_name,
                service_info.advertisement,
            )
        )

    return {"title": title, "data": config_data}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fluval Aquarium LED."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._discovered_devices: list[bluetooth.BluetoothServiceInfoBleak] = []
        self._bluetooth_discovery_info: bluetooth.BluetoothServiceInfoBleak | None = None

    # ------------------------------------------------------------------
    # Bluetooth auto-discovery (triggered by manifest.json bluetooth key)
    # ------------------------------------------------------------------

    def _mac_already_configured(self, mac: str) -> bool:
        """True if any entry already owns this MAC (case-insensitive)."""
        target = unique_id_from_mac(mac)
        for entry in self._async_current_entries():
            for candidate in (entry.unique_id, entry.data.get(CONF_MAC)):
                if candidate and unique_id_from_mac(str(candidate)) == target:
                    return True
        return False

    async def async_step_bluetooth(self, discovery_info: bluetooth.BluetoothServiceInfoBleak) -> ConfigFlowResult:
        """Handle Bluetooth auto-discovery when a Fluval light is seen."""
        mac = unique_id_from_mac(discovery_info.address)
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        # Legacy entries stored uppercase unique_ids; still treat as configured.
        if self._mac_already_configured(mac):
            return self.async_abort(reason="already_configured")

        # Secondary filter after manifest matchers — abort anything that isn't
        # a real Fluval LED (manifest wildcards can still be broad).
        adv = discovery_info.advertisement
        local_name = (adv.local_name if adv else None) or discovery_info.name
        if not is_likely_fluval(local_name, adv):
            return self.async_abort(reason="not_fluval")

        self._bluetooth_discovery_info = discovery_info
        name = _device_display_name(discovery_info, is_fluval=True)
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm adding a device found via Bluetooth auto-discovery."""
        errors: dict[str, str] = {}
        if user_input is not None and self._bluetooth_discovery_info is not None:
            discovery = self._bluetooth_discovery_info
            mac = _format_bluetooth_mac(discovery.address)
            ble_name = (
                (discovery.advertisement.local_name if discovery.advertisement else None)
                or getattr(discovery, "name", None)
                or ""
            )
            try:
                info = await validate_input(self.hass, {CONF_MAC: mac}, ble_name=ble_name)
            except InvalidFormat:
                errors["base"] = "invalid_format"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during Bluetooth confirm")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=info["data"])

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self.context.get("title_placeholders", {}).get("name", "Fluval LED"),
            },
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Manual config flow (initiated by user from Integrations page)
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step: pick from discovered devices or enter MAC manually."""
        configured = {entry.data.get(CONF_MAC) for entry in self._async_current_entries() if entry.data.get(CONF_MAC)}
        configured_normalized = {normalize_mac(m) for m in configured if m}

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_MAC)
            if selected == MANUAL_ENTRY:
                return await self.async_step_manual()
            mac = normalize_mac(selected)
            if MAC_REGEX.match(mac):
                await self.async_set_unique_id(unique_id_from_mac(mac))
                self._abort_if_unique_id_configured()
                if self._mac_already_configured(mac):
                    return self.async_abort(reason="already_configured")
                try:
                    info = await validate_input(self.hass, {CONF_MAC: mac})
                except InvalidFormat:
                    errors["base"] = "invalid_format"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(title=info["title"], data=info["data"])

        self._discovered_devices = await _get_discovered_devices(self.hass)
        options = self._device_options(configured_normalized)
        # If no discoverable devices (or all already configured), go straight to manual entry
        if len(options) <= 1:
            return await self.async_step_manual()

        schema = vol.Schema({vol.Required(CONF_MAC): vol.In(options)})
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len([o for o in options if o != MANUAL_ENTRY]))},
        )

    def _device_options(self, configured_normalized: set[str]) -> dict[str, str]:
        """Build dropdown options: value -> label. Exclude already configured."""
        options: dict[str, str] = {}
        for info in self._discovered_devices:
            mac = normalize_mac(info.address)
            if mac in configured_normalized:
                continue
            options[mac] = _device_display_name(info, is_fluval=True)
        options[MANUAL_ENTRY] = "My device isn't in the list — enter MAC address manually"
        return options

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle manual MAC address entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = normalize_mac(user_input[CONF_MAC])
            if not MAC_REGEX.match(mac):
                errors["base"] = "invalid_format"
            else:
                await self.async_set_unique_id(unique_id_from_mac(mac))
                self._abort_if_unique_id_configured()
                if self._mac_already_configured(mac):
                    return self.async_abort(reason="already_configured")
                try:
                    info = await validate_input(self.hass, {**user_input, CONF_MAC: mac})
                except InvalidFormat:
                    errors["base"] = "invalid_format"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(title=info["title"], data=info["data"])

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_MAC): str}),
            errors=errors,
            description_placeholders={"mac_example": "AA:BB:CC:DD:EE:FF"},
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Fluval Aquarium LED.

    Uses OptionsFlow (not OptionsFlowWithConfigEntry) so HA injects
    ``self.config_entry`` correctly — fixing the Configure gear 500 (#16).
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and handle the options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_LAMP_PROFILE,
                    default=options.get(CONF_LAMP_PROFILE, DEFAULT_LAMP_PROFILE),
                ): vol.In(
                    {
                        LAMP_PROFILE_AUTO: "Auto-detect from BLE name / protocol",
                        LAMP_PROFILE_PLANT: "Plant 5-channel (Pink–Warm White)",
                        LAMP_PROFILE_PLANT_PRO: "Current Plant 5-channel (Pink–Warm White)",
                        LAMP_PROFILE_MARINE: "Marine/Reef 5-channel spectrum",
                        LAMP_PROFILE_AQUASKY: "AquaSky 2.0 (4-channel RGBW)",
                        LAMP_PROFILE_AQUASKY3: "AquaSky 3.0 / FACEBD (4-channel RGBW)",
                    }
                ),
                vol.Optional(
                    CONF_PING_INTERVAL,
                    default=options.get(CONF_PING_INTERVAL, DEFAULT_PING_INTERVAL),
                ): vol.All(int, vol.Range(min=5, max=60)),
                vol.Optional(
                    CONF_ACTIVE_TIME,
                    default=options.get(CONF_ACTIVE_TIME, DEFAULT_ACTIVE_TIME),
                ): validate_active_time,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class InvalidFormat(HomeAssistantError):
    """Error to indicate the MAC address format is invalid."""
