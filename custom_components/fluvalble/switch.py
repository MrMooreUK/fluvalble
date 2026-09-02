"""Switch platform for Fluval Aquarium LED."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.device import Device
from .core.entity import FluvalEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build switches supported by the detected fixture transport."""
    if not device.supports_facebd_dst_control():
        return []
    return [FluvalDaylightSavingSwitch(device, "daylight_saving_time")]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fluval switches for a config entry."""
    runtime = config_entry.runtime_data
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.SWITCH] = add_entities


class FluvalDaylightSavingSwitch(FluvalEntity, SwitchEntity):
    """Control the fixture-owned FACEBD daylight-saving flag."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:sun-clock-outline"

    def internal_update(self) -> None:
        """Refresh state from fixture readback."""
        attribute = self.device.attribute(self.attr)
        is_on = attribute.get("is_on")
        self._attr_is_on = is_on if isinstance(is_on, bool) else None
        self._attr_available = (
            isinstance(is_on, bool) and self.device.supports_facebd_dst_control() and self.device.controls_available
        )
        if self.hass:
            self._async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Enable fixture daylight-saving handling."""
        del kwargs
        if not await self.device.async_set_daylight_saving_time(True):
            _LOGGER.warning("Unable to enable daylight-saving time for %s", self.device.mac)
        self.internal_update()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable fixture daylight-saving handling."""
        del kwargs
        if not await self.device.async_set_daylight_saving_time(False):
            _LOGGER.warning("Unable to disable daylight-saving time for %s", self.device.mac)
        self.internal_update()
