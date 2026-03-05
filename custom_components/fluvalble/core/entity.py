"""Base entity of a Fluval BLE connected LED device for home assistant."""

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo, Entity

from . import DOMAIN
from .device import Device


class FluvalEntity(Entity):
    """Base entity class."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device: Device, attr: str) -> None:
        """Initialize the entity."""
        self.device = device
        self.attr = attr

        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, device.mac)},
            identifiers={(DOMAIN, device.mac)},
            manufacturer="Fluval",
            model="Aquarium LED",
            name=device.name or "Fluval",
        )
        self._attr_translation_key = attr
        self._attr_unique_id = device.mac.replace(":", "") + "_" + attr

        # Store the bound method so deregistration uses the exact same object.
        self._update_handler = self.internal_update
        self._update_handler()
        device.register_update(attr, self._update_handler)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up update-handler registration when the entity is removed."""
        self.device.deregister_update(self.attr, self._update_handler)

    def internal_update(self):
        """Provide a function for internal updates."""
        pass
