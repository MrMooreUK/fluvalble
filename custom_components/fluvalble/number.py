"""Exact physical-channel controls for Fluval aquarium lights."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import require_entry_runtime_data
from .core import LAMP_PROFILE_AUTO
from .core.products import product_from_id
from .core.device import Device, NUMBERS
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0


def _layout_channels(device: Device) -> list[str]:
    """Wait for identification instead of registering a guessed superset."""
    if (
        product_from_id(device.product_id) is None
        and device.lamp_profile == LAMP_PROFILE_AUTO
        and device._channel_count_hint is None
    ):
        return []
    return device.numbers()


def create_entities(device: Device) -> list:
    """Build one exact control for every APK-defined physical channel."""
    return [FluvalChannelNumber(device, channel) for channel in _layout_channels(device)]


def setup_channel_entities(hass, entry, device, add_entities):
    """Reconcile deferred identification without leaving a phantom fifth slider."""
    from homeassistant.helpers import entity_registry as er

    runtime = require_entry_runtime_data(hass, entry)
    entities = {}
    removing = set()
    active = True

    async def remove(entity):
        try:
            if entity.hass:
                await entity.async_remove()
            registry = er.async_get(hass)
            entity_id = registry.async_get_entity_id("number", "fluvalble", entity.unique_id)
            if entity_id and product_from_id(device.product_id) is not None and entity.attr not in device.numbers():
                registry.async_remove(entity_id)
        finally:
            removing.discard(entity.attr)
            if active:
                sync()

    def sync():
        if not active or runtime.unloading:
            return
        desired = set(_layout_channels(device))
        authoritative = product_from_id(device.product_id) is not None
        # A provisional width must not erase user customizations or references.
        # Existing controls remain unavailable until their channel returns.
        for channel in (set(entities) - desired) if authoritative else ():
            removing.add(channel)
            task = hass.async_create_task(remove(entities.pop(channel)))
            runtime.background_tasks.add(task)
            task.add_done_callback(runtime.background_tasks.discard)
        if desired and authoritative:
            registry = er.async_get(hass)
            for channel in set(NUMBERS) - desired - removing:
                unique_id = device.mac.upper().replace(":", "") + "_" + channel
                entity_id = registry.async_get_entity_id("number", "fluvalble", unique_id)
                if entity_id:
                    registry.async_remove(entity_id)
        added = [
            FluvalChannelNumber(device, channel)
            for channel in device.numbers()
            if channel in desired and channel not in entities and channel not in removing
        ]
        entities.update({entity.attr: entity for entity in added})
        if added:
            add_entities(added)

    def stop():
        nonlocal active
        active = False
        device.deregister_update("channel_layout", sync)

    device.register_update("channel_layout", sync)
    entry.async_on_unload(stop)
    runtime.unload_callbacks.append(stop)
    sync()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up physical-channel controls for one Fluval fixture."""
    runtime = require_entry_runtime_data(hass, config_entry)
    device = runtime.device

    if device:
        setup_channel_entities(hass, config_entry, device, add_entities)
    else:
        runtime.pending_add_entities[Platform.NUMBER] = add_entities


class FluvalChannelNumber(FluvalEntity, NumberEntity):
    """Expose one APK-defined emitter as an exact percentage slider."""

    _attr_entity_registry_enabled_default = True
    _attr_icon = "mdi:brightness-6"
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"

    def internal_update(self) -> None:
        """Refresh the exact physical-channel percentage."""
        if self.attr not in self.device.numbers():
            self._attr_available = False
            self._attr_native_value = None
            if self.hass:
                self._async_write_ha_state()
            return
        attribute = self.device.attribute(self.attr)
        if not attribute:
            self._attr_available = False
            self._attr_native_value = None
            if self.hass:
                self._async_write_ha_state()
            return

        self._attr_available = "value" in attribute and self.device.controls_available
        self._attr_native_min_value = attribute.get("min")
        self._attr_native_max_value = attribute.get("max")
        self._attr_native_step = attribute.get("step")
        self._attr_native_value = attribute.get("value")

        if self.hass:
            self._async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Write one physical emitter without round-tripping through RGB."""
        async with self.device.command_transaction():
            if not await self.device.async_set_value(self.attr, int(value)):
                self.internal_update()
                self._raise_command_error()
        self.internal_update()
