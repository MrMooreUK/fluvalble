"""Sensor platform for Fluval Aquarium LED diagnostics."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import require_entry_runtime_data
from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSensor(device, sensor) for sensor in device.sensors()]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback) -> None:
    runtime = require_entry_runtime_data(hass, config_entry)
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.SENSOR] = add_entities


class FluvalSensor(FluvalEntity, SensorEntity):
    """Fluval diagnostics sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: Device, attr: str) -> None:
        """Initialize a diagnostic sensor."""
        if attr in {"rssi", "last_seen"}:
            # Persistent GATT sessions do not provide meaningful advertisement
            # RSSI or last-seen values. Keep their registry rows so switching
            # back to a timed connection can restore the same entities.
            self._attr_entity_registry_enabled_default = not device.is_persistent_connection()
        super().__init__(device, attr)
        if attr == "last_seen" and device.is_persistent_connection():
            # Preserve the entity's unique ID while describing the timestamp
            # that is meaningful for an open GATT session.
            self._attr_translation_key = "connected_since"

    def internal_update(self):
        """Update sensor state from the device."""
        attribute = self.device.attribute(self.attr)
        if not attribute:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = None
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
        elif self.attr == "active_connection_source":
            self._attr_icon = "mdi:bluetooth"
        if self.hass:
            self._async_write_ha_state()
