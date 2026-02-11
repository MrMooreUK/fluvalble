"""Config flow for Fluval Aquarium LED integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .core import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Bluetooth address filter expects lowercase with colons (e.g. aa:bb:cc:dd:ee:ff)
MAC_REGEX = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2})$")


def normalize_mac(mac: str) -> str:
    """Normalize MAC to lowercase colon-separated for HA Bluetooth API."""
    mac = mac.strip().lower().replace("-", ":").replace(" ", "")
    if len(mac) == 12 and mac.isalnum():
        return ":".join(mac[i : i + 2] for i in range(0, 12, 2))
    if MAC_REGEX.match(mac):
        return mac.lower()
    return mac


STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_MAC): str})


class PlaceholderHub:
    """Placeholder class to make tests pass.

    TODO Remove this placeholder class and replace with things from your PyPI package.
    """

    def __init__(self, mac: str) -> None:
        """Initialize."""
        self.mac = mac

    async def connect_test(self) -> bool:
        """Test if we can connect with the host."""
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
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
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
