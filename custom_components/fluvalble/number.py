from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core import DOMAIN
from .core.device import Device
from .core.entity import FluvalEntity


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalNumber(device, ch) for ch in device.numbers()]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    device = entry_data["device"]

    if device:
        add_entities(create_entities(device))
    else:
        entry_data["pending_add_entities"][Platform.NUMBER] = add_entities


class FluvalNumber(FluvalEntity, NumberEntity):
    def internal_update(self):
        attribute = self.device.attribute(self.attr)
        if not attribute:
            return
        self._attr_available = "value" in attribute
        self._attr_native_min_value = attribute.get("min")
        self._attr_native_max_value = attribute.get("max")
        self._attr_native_step = attribute.get("step")
        self._attr_native_value = attribute.get("value")

        if self.hass:
            self._async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        self.device.set_value(self.attr, int(value))
        self._attr_native_value = int(value)
        self._async_write_ha_state()
