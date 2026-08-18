from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalNumber(device, ch) for ch in device.numbers()]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    runtime = config_entry.runtime_data
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.NUMBER] = add_entities


class FluvalNumber(FluvalEntity, NumberEntity):
    _attr_icon = "mdi:brightness-6"
    _attr_mode = NumberMode.SLIDER

    def internal_update(self):
        attribute = self.device.attribute(self.attr)
        if not attribute:
            self._attr_available = False
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
        if not await self.device.async_set_value(self.attr, int(value)):
            self.internal_update()
            return

        self._attr_native_value = int(value)
        self._async_write_ha_state()
