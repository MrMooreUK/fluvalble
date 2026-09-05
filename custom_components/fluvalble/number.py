"""Exact physical-channel controls for Fluval aquarium lights."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import require_entry_runtime_data
from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build one exact control for every APK-defined physical channel."""
    return [FluvalChannelNumber(device, channel) for channel in device.numbers()]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up physical-channel controls for one Fluval fixture."""
    runtime = require_entry_runtime_data(hass, config_entry)
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.NUMBER] = add_entities


class FluvalChannelNumber(FluvalEntity, NumberEntity):
    """Expose one APK-defined emitter as an exact percentage slider."""

    _attr_entity_registry_enabled_default = True
    _attr_icon = "mdi:brightness-6"
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"

    def internal_update(self) -> None:
        """Refresh the exact physical-channel percentage."""
        attribute = self.device.attribute(self.attr)
        if not attribute:
            self._attr_available = False
            self._attr_native_value = None
            if self.hass:
                self._async_write_ha_state()
            return

        self._attr_available = "value" in attribute and self.device.controls_available
        self._attr_native_min_value = attribute.get("min")
        self._attr_native_max_value = attribute.get("max")
        self._attr_native_step = attribute.get("step")
        self._attr_native_value = attribute.get("value")

        if self.hass:
            self._async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Write one physical emitter without round-tripping through RGB."""
        if not await self.device.async_set_value(self.attr, int(value)):
            self.internal_update()
            self._raise_command_error()
        self.internal_update()
