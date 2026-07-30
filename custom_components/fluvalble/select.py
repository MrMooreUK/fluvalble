from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSelect(device, s) for s in device.selects()]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback):
    runtime = config_entry.runtime_data
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.SELECT] = add_entities


class FluvalSelect(FluvalEntity, SelectEntity):
    _attr_icon = "mdi:tune"

    def internal_update(self):
        attribute = self.device.attribute(self.attr)
        if not attribute:
            self._attr_available = False
            if self.hass:
                self._async_write_ha_state()
            return
        self._attr_current_option = attribute.get("default")
        self._attr_options = attribute.get("options", [])
        self._attr_available = "default" in attribute and self.device.controls_available

        if self.hass:
            self._async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if self.attr == "schedule_mode":
            if not self.hass or not self.device.entry_id:
                self.internal_update()
                return
            from . import async_set_schedule_mode  # noqa: PLC0415

            await async_set_schedule_mode(self.hass, self.device.entry_id, option)
            self.internal_update()
            return

        if not await self.device.async_select_option(self.attr, option):
            self.internal_update()
            return

        self._attr_current_option = option
        self._async_write_ha_state()
