"""Button platform for Fluval Aquarium LED."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import require_entry_runtime_data
from .core.device import Device
from .core.entity import FluvalEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [
        FluvalIdentifyButton(device, "identify"),
        FluvalSyncClockButton(device, "sync_clock"),
    ]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    runtime = require_entry_runtime_data(hass, config_entry)
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.BUTTON] = add_entities


class FluvalSyncClockButton(FluvalEntity, ButtonEntity):
    """Button to sync the lamp RTC from Home Assistant time."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-check-outline"

    async def async_press(self) -> None:
        """Force a clock sync on the connected lamp."""
        if not await self.device.async_sync_clock(force=True):
            self._raise_command_error()
        _LOGGER.info("Fluval clock synced for %s", self.device.mac)


class FluvalIdentifyButton(FluvalEntity, ButtonEntity):
    """Button that asks the physical fixture to identify itself."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Send FluvalConnect's native Find command."""
        if not await self.device.async_identify():
            self._raise_command_error()
