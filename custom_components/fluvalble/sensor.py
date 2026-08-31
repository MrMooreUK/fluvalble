"""Sensor platform for Fluval Aquarium LED diagnostics."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSensor(device, sensor) for sensor in device.sensors()]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    runtime = config_entry.runtime_data
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.SENSOR] = add_entities


class FluvalSensor(FluvalEntity, SensorEntity):
    """Fluval diagnostics sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def internal_update(self):
        """Update sensor state from the device."""
        attribute = self.device.attribute(self.attr)
        if not attribute:
            self._attr_available = False
            if self.hass:
                self._async_write_ha_state()
            return

        self._attr_available = "value" in attribute
        self._attr_native_value = attribute.get("value")
        self._attr_native_unit_of_measurement = attribute.get("native_unit_of_measurement")
        self._attr_extra_state_attributes = attribute.get("extra")

        if self.attr == "rssi":
            self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "dBm"
        elif self.attr == "last_seen":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        if self.hass:
            self._async_write_ha_state()
