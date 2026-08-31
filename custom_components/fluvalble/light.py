"""Native Home Assistant colour light for Fluval fixtures."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .core.device import Device
from .core.effects import EFFECT_NONE
from .core.entity import FluvalEntity

PARALLEL_UPDATES = 0

_DEFAULT_PLANT_RGB = (170, 210, 255)
_DEFAULT_AQUASKY_RGBW = (0, 0, 0, 255)


def create_entities(device: Device) -> list:
    """Build the entity list for this platform."""
    return [FluvalLight(device, "light")]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fluval light entity."""
    runtime = config_entry.runtime_data
    device = runtime.device

    if device:
        add_entities(create_entities(device))
    else:
        runtime.pending_add_entities[Platform.LIGHT] = add_entities


class FluvalLight(FluvalEntity, LightEntity):
    """Expose Fluval channels through Home Assistant's native light controls."""

    _attr_icon = "mdi:led-strip-variant"
    _attr_rgb_color: tuple[int, int, int] | None = None
    _attr_rgbw_color: tuple[int, int, int, int] | None = None

    def __init__(self, device: Device, attr: str) -> None:
        super().__init__(device, attr)
        self._update_effect_capabilities()
        if device.light_mode() == "rgb":
            self._attr_color_mode = ColorMode.RGB
            self._attr_supported_color_modes = {ColorMode.RGB}
        else:
            self._attr_color_mode = ColorMode.RGBW
            self._attr_supported_color_modes = {ColorMode.RGBW}

    def internal_update(self) -> None:
        """Refresh the entity from decoded fixture state."""
        self._attr_available = self.device.controls_available
        self._attr_is_on = bool(self.device.values.get("led_on_off"))
        self._attr_brightness = self.device.light_brightness_255() or None
        self._attr_effect = self.device.values.get("effect")
        self._update_effect_capabilities()

        if self.device.light_mode() == "rgb":
            self._attr_color_mode = ColorMode.RGB
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_rgb_color = self.device.light_rgb_255()
            self._attr_rgbw_color = None
        else:
            self._attr_color_mode = ColorMode.RGBW
            self._attr_supported_color_modes = {ColorMode.RGBW}
            self._attr_rgbw_color = self.device.light_rgbw_255()
            self._attr_rgb_color = None

        if self.hass:
            self._async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the fixture and apply an optional colour or brightness."""
        requested_effect = kwargs.get(ATTR_EFFECT)
        if requested_effect == EFFECT_NONE:
            await self.device.async_stop_effect()
            self.internal_update()
            return
        if requested_effect is not None:
            await self.device.async_set_effect(str(requested_effect))
            self.internal_update()
            return

        brightness = max(
            1,
            min(
                255,
                int(kwargs.get(ATTR_BRIGHTNESS, self.device.light_brightness_255() or 255)),
            ),
        )

        color = self._requested_color(kwargs, brightness)
        if color is not None:
            channels, rgb, rgbw = color
            if await self.device.async_apply_light_channels(channels):
                self.device.remember_commanded_light(
                    channels,
                    rgb=rgb,
                    rgbw=rgbw,
                    brightness=brightness,
                )
            self.internal_update()
            return

        if ATTR_BRIGHTNESS in kwargs:
            await self._async_set_brightness(brightness)
            self.internal_update()
            return

        if self.device.master_brightness() > 0:
            await self.device.async_set_switch("led_on_off", True)
            self.internal_update()
            return

        channels, rgb, rgbw = self._default_color(brightness)
        if await self.device.async_apply_light_channels(channels):
            self.device.remember_commanded_light(
                channels,
                rgb=rgb,
                rgbw=rgbw,
                brightness=brightness,
            )
        self.internal_update()

    def _update_effect_capabilities(self) -> None:
        """Expose native effects only for positively identified controllers."""
        self._attr_effect_list = self.device.effect_list()
        self._attr_supported_features = LightEntityFeature.EFFECT if self._attr_effect_list else 0

    def _requested_color(
        self,
        kwargs: dict,
        brightness: int,
    ) -> (
        tuple[
            dict[str, int],
            tuple[int, int, int] | None,
            tuple[int, int, int, int] | None,
        ]
        | None
    ):
        """Translate colour kwargs into physical Fluval channels."""
        if self.device.light_mode() == "rgb":
            if ATTR_RGB_COLOR not in kwargs:
                return None
            rgb = tuple(kwargs[ATTR_RGB_COLOR])
            return self.device.channels_from_rgb(rgb, brightness), rgb, None

        if ATTR_RGBW_COLOR in kwargs:
            rgbw = tuple(kwargs[ATTR_RGBW_COLOR])
        elif ATTR_RGB_COLOR in kwargs:
            rgbw = (*tuple(kwargs[ATTR_RGB_COLOR]), 0)
        else:
            return None
        return self.device.channels_from_rgbw(rgbw, brightness), None, rgbw

    def _default_color(
        self,
        brightness: int,
    ) -> tuple[
        dict[str, int],
        tuple[int, int, int] | None,
        tuple[int, int, int, int] | None,
    ]:
        """Return a useful first-on colour for a fixture with zeroed channels."""
        if self.device.light_mode() == "rgb":
            return (
                self.device.channels_from_rgb(_DEFAULT_PLANT_RGB, brightness),
                _DEFAULT_PLANT_RGB,
                None,
            )
        return (
            self.device.channels_from_rgbw(_DEFAULT_AQUASKY_RGBW, brightness),
            None,
            _DEFAULT_AQUASKY_RGBW,
        )

    async def _async_set_brightness(self, brightness: int) -> bool:
        """Scale the current colour mix without changing its hue."""
        if self.device.master_brightness() == 0:
            channels, rgb, rgbw = self._default_color(brightness)
            if not await self.device.async_apply_light_channels(channels):
                return False
            self.device.remember_commanded_light(
                channels,
                rgb=rgb,
                rgbw=rgbw,
                brightness=brightness,
            )
            return True

        rgb = self.device.light_rgb_255() if self.device.light_mode() == "rgb" else None
        rgbw = self.device.light_rgbw_255() if self.device.light_mode() == "rgbw" else None
        if not await self.device.async_set_master_brightness(round(brightness / 255 * 100)):
            return False
        self.device.clear_commanded_light()
        if not self.device.values.get("led_on_off") and not await self.device.async_set_switch("led_on_off", True):
            return False
        channels = {channel: int(self.device.values[channel]) for channel in self.device.numbers()}
        self.device.remember_commanded_light(
            channels,
            rgb=rgb,
            rgbw=rgbw,
            brightness=brightness,
        )
        return True

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the fixture without rewriting its colour channels."""
        if not await self.device.async_set_switch("led_on_off", False):
            self.internal_update()
            return
        self._attr_is_on = False
        self._async_write_ha_state()
