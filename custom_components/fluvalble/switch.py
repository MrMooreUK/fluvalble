"""Switch platform for Fluval Aquarium LED."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import require_entry_runtime_data
from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build switches supported by the detected fixture transport."""
    if not device.supports_facebd_dst_control():
        return []
    return [FluvalDaylightSavingSwitch(device, "daylight_saving_time")]


def setup_switch_entities(hass, entry, device, add_entities):
    """Add a transport-specific control when GATT resolves after setup."""
    runtime = require_entry_runtime_data(hass, entry)
    added = False
    active = True

    def sync():
        nonlocal added
        if not active or runtime.unloading or added:
            return
        entities = create_entities(device)
        if entities:
            added = True
            add_entities(entities)

    def stop():
        nonlocal active
        active = False
        device.deregister_update("transport_capabilities", sync)

    device.register_update("transport_capabilities", sync)
    entry.async_on_unload(stop)
    runtime.unload_callbacks.append(stop)
    sync()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fluval switches for a config entry."""
    runtime = require_entry_runtime_data(hass, config_entry)
    device = runtime.device

    if device:
        setup_switch_entities(hass, config_entry, device, add_entities)
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
            self.internal_update()
            self._raise_command_error()
        self.internal_update()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable fixture daylight-saving handling."""
        del kwargs
        if not await self.device.async_set_daylight_saving_time(False):
            self.internal_update()
            self._raise_command_error()
        self.internal_update()
