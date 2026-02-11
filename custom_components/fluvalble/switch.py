from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core import DOMAIN
from .core.device import Device
from .core.entity import FluvalEntity


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSwitch(device, "led_on_off")]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
):
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    device = entry_data["device"]

    if device:
        add_entities(create_entities(device))
    else:
        # Device not yet available — stash callback for later.
        entry_data["pending_add_entities"][Platform.SWITCH] = add_entities


class FluvalSwitch(FluvalEntity, SwitchEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH

    def internal_update(self):
        attribute = self.device.attribute(self.attr)
        if not attribute:
            return

        self._attr_is_on = attribute.get("is_on")

        if self.hass:
            self._async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the LED off."""
        self.device.set_led_power(False)
        self._attr_is_on = False
        self._async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the LED on."""
        self.device.set_led_power(True)
        self._attr_is_on = True
        self._async_write_ha_state()
