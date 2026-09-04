from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import require_entry_runtime_data
from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalSelect(device, s) for s in device.selects()]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback):
    runtime = require_entry_runtime_data(hass, config_entry)
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
        async with self.device.command_transaction():
            await self._async_select_option(option)

    async def _async_select_option(self, option: str) -> None:
        """Apply one complete mode-selection transaction."""
        if not await self.device.async_stop_preview(restore=False):
            self.internal_update()
            self._raise_command_error()
        if not await self.device.async_select_option(self.attr, option):
            self.internal_update()
            self._raise_command_error()

        self._attr_current_option = option
        self._async_write_ha_state()
