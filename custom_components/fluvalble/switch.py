from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSwitch(device, "led_on_off")]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback):
    runtime = config_entry.runtime_data
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        # Device not yet available — stash callback for later.
        runtime.pending_add_entities[Platform.SWITCH] = add_entities


class FluvalSwitch(FluvalEntity, SwitchEntity):
    _attr_icon = "mdi:led-strip-variant"

    def internal_update(self):
        attribute = self.device.attribute(self.attr)
        self._attr_available = bool(attribute) and self.device.controls_available
        if not attribute:
            if self.hass:
                self._async_write_ha_state()
            return

        self._attr_is_on = attribute.get("is_on")

        if self.hass:
            self._async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the LED off."""
        if not await self.device.async_set_switch(self.attr, False):
            self.internal_update()
            return

        self._attr_is_on = False
        self._async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the LED on."""
        if not await self.device.async_set_switch(self.attr, True):
            self.internal_update()
            return

        self._attr_is_on = True
        self._async_write_ha_state()
