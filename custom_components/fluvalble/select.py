from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core import DOMAIN
from .core.device import Device
from .core.entity import FluvalEntity


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSelect(device, s) for s in device.selects()]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
):
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    device = entry_data["device"]

    if device:
        add_entities(create_entities(device))
    else:
        entry_data["pending_add_entities"][Platform.SELECT] = add_entities


class FluvalSelect(FluvalEntity, SelectEntity):
    def internal_update(self):
        attribute = self.device.attribute(self.attr)
        if not attribute:
            return
        self._attr_current_option = attribute.get("default")
        self._attr_options = attribute.get("options", [])
        self._attr_available = "default" in attribute

        if self.hass:
            self._async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        self.device.select_option(self.attr, option)
        self._attr_current_option = option
        self._async_write_ha_state()
