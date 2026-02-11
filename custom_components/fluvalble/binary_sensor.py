from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core import DOMAIN
from .core.device import Device
from .core.entity import FluvalEntity


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSensor(device, "connection")]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
):
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    device = entry_data["device"]

    if device:
        add_entities(create_entities(device))
    else:
        entry_data["pending_add_entities"][Platform.BINARY_SENSOR] = add_entities


class FluvalSensor(FluvalEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def internal_update(self):
        attribute = self.device.attribute(self.attr)
        if not attribute:
            return

        self._attr_is_on = attribute.get("is_on")
        self._attr_extra_state_attributes = attribute.get("extra")

        if self.hass:
            self._async_write_ha_state()
