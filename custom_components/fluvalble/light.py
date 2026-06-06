"""Light platform: a master dimmer that controls all channels together."""

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core import DOMAIN
from .core.device import Device
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0

# Device channels run 0–1000; Home Assistant light brightness is 0–255.
DEVICE_MAX = 1000
HA_MAX = 255


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalLight(device, "light")]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    device = entry_data["device"]

    if device:
        add_entities(create_entities(device))
    else:
        entry_data["pending_add_entities"][Platform.LIGHT] = add_entities


class FluvalLight(FluvalEntity, LightEntity):
    """Master dimmer: on/off plus a single brightness that scales all channels."""

    _attr_icon = "mdi:led-strip-variant"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def internal_update(self):
        self._attr_available = self.device.connected
        self._attr_is_on = bool(self.device.values.get("led_on_off"))
        level = self.device.master_brightness()  # 0–1000
        self._attr_brightness = round(level / DEVICE_MAX * HA_MAX)

        if self.hass:
            self._async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on, optionally setting overall brightness."""
        if ATTR_BRIGHTNESS in kwargs:
            level = round(kwargs[ATTR_BRIGHTNESS] / HA_MAX * DEVICE_MAX)
            self.device.set_master_brightness(level)
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        if not self.device.values.get("led_on_off"):
            self.device.set_led_power(True)
        self._attr_is_on = True
        self._async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        self.device.set_led_power(False)
        self._attr_is_on = False
        self._async_write_ha_state()
