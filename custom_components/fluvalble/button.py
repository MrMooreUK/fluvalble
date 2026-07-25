"""Button platform for Fluval Aquarium LED diagnostics."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core import DOMAIN
from .core.device import Device
from .core.entity import FluvalEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [
        FluvalDiagnosticsButton(device, "refresh_diagnostics"),
        FluvalChannelTestButton(device, "test_led_channels"),
    ]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    device = entry_data["device"]

    if device:
        add_entities(create_entities(device))
    else:
        entry_data["pending_add_entities"][Platform.BUTTON] = add_entities


class FluvalDiagnosticsButton(FluvalEntity, ButtonEntity):
    """Button to collect copyable BLE diagnostics from the integration."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        """Collect diagnostics for the configured BLE controller."""
        report = await self.device.async_collect_diagnostics()
        if report.get("status") != "ok":
            _LOGGER.warning("Fluval diagnostics failed: %s", report)
        else:
            _LOGGER.info("Fluval diagnostics: %s", report)


class FluvalChannelTestButton(FluvalEntity, ButtonEntity):
    """Run a visible, verified test of each physical LED channel."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:led-strip-variant"

    async def async_press(self) -> None:
        """Illuminate every supported channel and record exact readback."""
        if not await self.device.async_test_led_channels():
            _LOGGER.warning(
                "Fluval LED channel test did not verify every channel: %s",
                self.device.diagnostics,
            )
