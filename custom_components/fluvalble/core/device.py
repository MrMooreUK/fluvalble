"""A single Fluval BLE connected LED device."""

from collections.abc import Callable
import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
import logging
from time import monotonic
from typing import Any, TypedDict

from bleak import AdvertisementData, BLEDevice, BleakError, BleakScanner
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time

from . import (
    CONF_LAMP_PROFILE,
    DEFAULT_LAMP_PROFILE,
    LAMP_PROFILE_AQUASKY,
    LAMP_PROFILE_AQUASKY3,
    LAMP_PROFILE_AUTO,
    LAMP_PROFILE_MARINE,
    LAMP_PROFILE_PLANT,
    LAMP_PROFILE_PLANT_PRO,
)
from .client import Client
from .discovery import (
    CONF_MODEL,
    CONF_PRODUCT_ID,
    detect_model,
)
from .effects import (
    effect_id,
    effect_list as classic_effect_list,
    effect_name,
    four_effect_id,
    four_effect_list,
    four_effect_name,
)
from . import protocol
from .products import product_from_id, product_id_from_manufacturer_data

_LOGGER = logging.getLogger(__name__)

# An idle GATT disconnect is expected. Treat the fixture as reachable while
# recent advertisement, connection, or successful command activity exists.
REACHABLE_SECONDS = 300

NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4", "channel_5"]
# FluvalConnect exposes Manual, Auto, and Professional as one operating-mode
# control for every supported light family. Schedule editors configure those
# modes; they are not a second fixture mode selector.
SELECTS = ["mode"]
SENSORS = ["rssi", "last_seen", "active_connection_source", "advertisement_source"]
AQUASKY_NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4"]
CHANNEL_NAMES_AQUASKY = {
    "channel_1": "Red",
    "channel_2": "Green",
    "channel_3": "Blue",
    "channel_4": "White",
    "channel_5": "Violet",
}
CHANNEL_NAMES_PLANT = {
    "channel_1": "Pink",
    "channel_2": "Blue",
    "channel_3": "Cold White",
    "channel_4": "White",
    "channel_5": "Warm White",
}
CHANNEL_NAMES_MARINE = {
    "channel_1": "Pink",
    "channel_2": "Cyan",
    "channel_3": "Blue",
    "channel_4": "Purple",
    "channel_5": "Cold White",
}
CHANNEL_NAMES_PLANT_PRO = {
    # Kept as a compatibility profile name. FluvalConnect assigns Plant PRO
    # and Plant 4.0 the same APK light type and five-channel order.
    "channel_1": "Pink",
    "channel_2": "Blue",
    "channel_3": "Cold White",
    "channel_4": "White",
    "channel_5": "Warm White",
}
# Back-compat alias used by tests / schedule helpers
CHANNEL_NAMES = CHANNEL_NAMES_AQUASKY
MODES = ["manual", "automatic", "professional"]
MODE_TO_CODE = {mode: index for index, mode in enumerate(MODES)}
DIAGNOSTIC_UPDATE_INTERVAL = 5
BLE_LOOKUP_TIMEOUT = 10
BLE_LOOKUP_RETRIES = 3
PREVIEW_STEP_SECONDS = 2
TRANSITION_STEP_SECONDS = 30
DAY_MINUTES = 24 * 60

# Approximate sRGB appearance of the five-channel spectral LEDs. These values
# affect only Home Assistant's colour representation; BLE writes still use the
# APK-defined channel order without conversion at the protocol layer.
PLANT_CHANNEL_RGB = {
    "channel_1": (1.00, 0.28, 0.38),
    "channel_2": (0.18, 0.38, 1.00),
    "channel_3": (0.72, 0.84, 1.00),
    "channel_4": (1.00, 1.00, 1.00),
    "channel_5": (1.00, 0.72, 0.42),
}
MARINE_CHANNEL_RGB = {
    "channel_1": (1.00, 0.25, 0.45),  # Pink
    "channel_2": (0.00, 1.00, 1.00),  # Cyan
    "channel_3": (0.00, 0.10, 1.00),  # Blue
    "channel_4": (0.55, 0.10, 1.00),  # Purple
    "channel_5": (0.75, 0.86, 1.00),  # Cold White
}


class Attribute(TypedDict, total=False):
    """Attributes used by entities like binary_sensor and number."""

    options: list[str]
    default: str

    min: int
    max: int
    step: int
    value: int

    is_on: bool
    extra: dict
    device_class: str
    native_unit_of_measurement: str | None


class Device:
    """Fluval BLE LED device class."""

    def __init__(
        self,
        name: str,
        device: BLEDevice | None = None,
        advertisement: AdvertisementData | None = None,
        advertisement_source: str | None = None,
        hass: HomeAssistant | None = None,
        config_data: dict[str, Any] | None = None,
        ping_interval: int = 10,
        active_time: int = 120,
    ) -> None:
        """Initialize the device."""
        config_data = config_data or {}
        self.hass = hass
        self.name = name or (device.name if device else None) or "Fluval"
        configured_product_id = config_data.get(CONF_PRODUCT_ID)
        self.product_id = (
            configured_product_id
            if isinstance(configured_product_id, int) and not isinstance(configured_product_id, bool)
            else None
        )
        if self.product_id is None and advertisement is not None:
            self.product_id = product_id_from_manufacturer_data(advertisement.manufacturer_data)
        product = product_from_id(self.product_id)
        self.model = (
            (product.model if product is not None else None)
            or config_data.get(CONF_MODEL)
            or detect_model((device.name if device else None) or name, advertisement)
        )
        self.lamp_profile = config_data.get(CONF_LAMP_PROFILE, DEFAULT_LAMP_PROFILE)
        self._channel_count_hint: int | None = None
        self.address = (config_data.get("mac") or (device.address if device else "")).upper()
        self.client: Client | None = None
        self._ping_interval = ping_interval
        self._active_time = active_time
        self.connected = False
        self.entry_id: str | None = None
        self.schedule_mode = "manual"
        self.conn_info = {
            "mac": self.address,
            "model": self.model,
            "product_id": self.product_id,
            "service_uuids": config_data.get("service_uuids", []),
            "service_data": config_data.get("service_data", {}),
        }
        self.facebd = self._uses_facebd_protocol(
            self.name,
            self.conn_info["service_uuids"],
            self.conn_info["service_data"],
            config_data.get("manufacturer_data", {}),
        )
        self.updates_connect: list = []
        self.updates_component: list = []
        self._last_diagnostic_update = 0.0
        self.values = {}
        for channel in NUMBERS:
            self.values[channel] = 0
        self.values["mode"] = "manual"
        self.values["led_on_off"] = False
        self.values["effect"] = None
        self.firmware_version: str | None = None
        self.diagnostics: dict[str, Any] = {
            "status": "not_run",
            "configured_mac": self.address,
        }
        self.preview_task: asyncio.Task | None = None
        self.preview_restore_values: dict[str, int] | None = None
        self.preview_restore_mode: str | None = None
        self.native_preview_active = False
        self.native_preview_schedule_type: str | None = None
        self.native_preview_restore_mode: str | None = None
        self._clock_synced = False
        self._clock_sync_started = False
        self._clock_sync_lock = asyncio.Lock()
        # Preserve the exact colour HA requested while the decoded physical
        # channels still match it.  Plant RGB conversion is intentionally
        # lossy, so reconstructing RGB from those five channels would otherwise
        # make the colour picker jump after every status update.
        self._commanded_rgb: tuple[int, int, int] | None = None
        self._commanded_rgbw: tuple[int, int, int, int] | None = None
        self._commanded_brightness: int | None = None
        self._commanded_channels: dict[str, int] | None = None
        self._effect_restore_channels: dict[str, int] | None = None
        self._reachability_unsub: Callable[[], None] | None = None

        if device and advertisement:
            self.update_ble(device, advertisement, advertisement_source)

    @property
    def mac(self) -> str:
        """Expose the MAC address of the device."""
        return self.address

    @property
    def model_name(self) -> str:
        """Expose a model name for Home Assistant device info."""
        return self.model

    @property
    def controls_available(self) -> bool:
        """Return true when HA has enough BLE info to attempt commands."""
        return bool(self.client or self.conn_info.get("last_seen"))

    def touch_seen(self, *, rssi: int | None = None, notify: bool = True) -> None:
        """Record successful advertisement, connection, or command activity."""
        self.conn_info["last_seen"] = datetime.now(UTC)
        if rssi is not None:
            self.conn_info["rssi"] = rssi
            self.conn_info["rssi_updated_at"] = self.conn_info["last_seen"]
        if notify:
            for handler in self.updates_connect:
                handler()
        if not self.connected:
            self._schedule_reachability_refresh()

    def cancel_reachability_refresh(self) -> None:
        """Cancel the pending reachability expiry callback."""
        if self._reachability_unsub is not None:
            self._reachability_unsub()
            self._reachability_unsub = None

    @callback
    def _on_reachability_expired(self, _now: datetime) -> None:
        """Refresh entities when the recent-activity window expires."""
        self._reachability_unsub = None
        for handler in self.updates_connect:
            handler()

    def _schedule_reachability_refresh(self) -> None:
        """Schedule a one-shot refresh at the recent-activity expiry."""
        if self.hass is None or self.connected:
            return

        self.cancel_reachability_refresh()
        last_seen = self.conn_info.get("last_seen")
        if not isinstance(last_seen, datetime):
            return
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)

        expiry = last_seen + timedelta(seconds=REACHABLE_SECONDS)
        if expiry <= datetime.now(UTC):
            self._on_reachability_expired(datetime.now(UTC))
            return
        self._reachability_unsub = async_track_point_in_time(
            self.hass,
            self._on_reachability_expired,
            expiry,
        )

    def update_ble(
        self,
        device: BLEDevice,
        advertisement: AdvertisementData,
        source: str | None = None,
    ) -> None:
        """Update BLE metadata."""
        self.address = device.address
        self.conn_info["mac"] = device.address
        self.touch_seen(rssi=advertisement.rssi, notify=False)
        self._record_advertisement_source(source or self._source_from_device(device))
        self.conn_info["service_uuids"] = list(advertisement.service_uuids)
        self.conn_info["service_data"] = {key: bytes(value).hex() for key, value in advertisement.service_data.items()}
        product_id = product_id_from_manufacturer_data(advertisement.manufacturer_data)
        if product_id is not None:
            self.product_id = product_id
            self.conn_info["product_id"] = product_id
            self.diagnostics["product_id"] = product_id
            product = product_from_id(product_id)
            if product is not None and product.model is not None:
                self.model = product.model
                self.conn_info["model"] = self.model
        self.facebd = self._uses_facebd_protocol(
            device.name,
            advertisement.service_uuids,
            advertisement.service_data,
            advertisement.manufacturer_data,
        )

        if self.client is None:
            self.client = self._new_client(device)
        else:
            self.client.device = device

        self._notify_diagnostics_throttled()
        for handler in self.updates_component:
            handler()

    @staticmethod
    def _source_from_device(device: BLEDevice) -> str | None:
        """Return the HA scanner source embedded in a connectable BLEDevice."""
        details = device.details if isinstance(device.details, dict) else {}
        source = details.get("source")
        return str(source) if source else None

    def _source_metadata(self, source: str | None) -> dict[str, str | None]:
        """Resolve an HA scanner source to a stable name and scanner type."""
        source_name = source
        source_type = None
        if self.hass is not None and source:
            get_scanner = getattr(bluetooth, "async_scanner_by_source", None)
            scanner = get_scanner(self.hass, source) if get_scanner else None
            if scanner is not None:
                source_name = getattr(scanner, "name", None) or source
                details = getattr(scanner, "details", None)
                scanner_type = getattr(details, "scanner_type", None)
                source_type = getattr(scanner_type, "value", None) or (
                    str(scanner_type) if scanner_type is not None else None
                )
        return {
            "source": source,
            "source_name": source_name,
            "source_type": source_type,
        }

    def _record_advertisement_source(self, source: str | None) -> None:
        """Record which scanner supplied the advertisement-backed RSSI."""
        metadata = self._source_metadata(source)
        self.conn_info.update(
            {
                "advertisement_source": metadata["source_name"],
                "advertisement_source_address": metadata["source"],
                "advertisement_source_type": metadata["source_type"],
                "advertisement_updated_at": self.conn_info.get("rssi_updated_at"),
            }
        )

    def _record_active_connection_source(
        self,
        device: BLEDevice,
        connected_source: str | None = None,
    ) -> None:
        """Snapshot the selected HA route after GATT setup succeeds."""
        metadata = self._source_metadata(connected_source or self._source_from_device(device))
        self.conn_info.update(
            {
                "active_connection_source": metadata["source_name"],
                "active_connection_source_address": metadata["source"],
                "active_connection_source_type": metadata["source_type"],
                "active_connection_connected_at": datetime.now(UTC),
            }
        )

    def set_connected(self, connected: bool):
        """Set active GATT status while tracking fixture reachability."""
        self.connected = connected
        if connected:
            self.touch_seen(notify=False)
            self.cancel_reachability_refresh()
        else:
            # Allow clock sync again on the next successful connect (#8).
            self._clock_synced = False
            self._clock_sync_started = False
            self._schedule_reachability_refresh()

        for handler in self.updates_connect:
            handler()
        for handler in self.updates_component:
            handler()

    def is_reachable(self) -> bool:
        """Return whether the fixture has a live session or recent activity."""
        if self.connected:
            return True
        last_seen = self.conn_info.get("last_seen")
        if not isinstance(last_seen, datetime):
            return False
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        return (datetime.now(UTC) - last_seen).total_seconds() <= REACHABLE_SECONDS

    def command_error_message(self) -> str:
        """Return the most useful available BLE command error."""
        if self.client is not None and self.client.last_error:
            return self.client.last_error
        return self.diagnostics.get("last_error") or "Fluval BLE command failed"

    def _notify_diagnostics_throttled(self):
        """Notify diagnostic entities at most once per interval."""
        now = monotonic()
        if now - self._last_diagnostic_update < DIAGNOSTIC_UPDATE_INTERVAL:
            return

        self._last_diagnostic_update = now
        for handler in self.updates_connect:
            handler()

    def _record_native_schedule_readback(
        self,
        *,
        protocol_name: str,
        auto: dict[str, Any] | None = None,
        professional: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Store protocol-neutral fixture schedule readback."""
        if auto is None and professional is None:
            return False
        if auto is not None:
            self.values["native_auto_schedule"] = auto
            self.diagnostics["native_auto_schedule"] = auto
        if professional is not None:
            self.values["native_pro_schedule"] = professional
            self.diagnostics["native_pro_schedule"] = professional
        self.diagnostics.update(
            {
                "native_schedule_protocol": protocol_name,
                "native_schedule_readback_at": datetime.now(UTC).isoformat(),
            }
        )
        return True

    def _record_native_effect_schedule_readback(
        self,
        *,
        protocol_name: str,
        windows: list[dict[str, Any]] | None,
    ) -> bool:
        """Store protocol-neutral fixture-owned timed-effect readback."""
        if windows is None:
            return False
        normalized = [
            {
                **window,
                "effect": self._native_effect_name(window["effect_id"]),
            }
            for window in windows
        ]
        self.values["native_effect_schedule"] = normalized
        self.diagnostics["native_effect_schedule"] = normalized
        if protocol_name == "plant_pro":
            # Backward-compatible diagnostics key from the original Plant Pro service.
            self.diagnostics["plant_pro_effect_schedule"] = normalized
        self.diagnostics.update(
            {
                "native_schedule_protocol": protocol_name,
                "native_schedule_readback_at": datetime.now(UTC).isoformat(),
            }
        )
        return True

    def numbers(self) -> list[str]:
        """List of numbers provided by the device."""
        if self._resolved_channel_count() == 4:
            return list(AQUASKY_NUMBERS)
        return list(NUMBERS)

    def _resolved_channel_count(self) -> int:
        """Return the APK channel count, with fallbacks for unidentified fixtures."""
        if (product := product_from_id(self.product_id)) is not None:
            return product.channel_count
        profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
        if profile == LAMP_PROFILE_AQUASKY:
            return 4
        if profile == LAMP_PROFILE_AQUASKY3:
            return 4
        if profile in (LAMP_PROFILE_PLANT, LAMP_PROFILE_PLANT_PRO, LAMP_PROFILE_MARINE):
            return 5
        if self._channel_count_hint in (4, 5):
            return self._channel_count_hint
        if self.facebd:
            return 4
        if self._uses_plant_pro_protocol():
            return 5

        model_l = (self.model or "").lower()
        name_l = (self.name or "").lower()
        combined = f"{model_l} {name_l}"

        if any(token in combined for token in ("plant", "marine", "reef")):
            return 5
        # AquaSky controllers are RGBW. Plant/Marine fixtures remain 5-channel.
        if "aquasky" in combined:
            return 4
        return 5

    def _channel_labels(self) -> dict[str, str]:
        """Return channel labels for the active lamp profile."""
        if (product := product_from_id(self.product_id)) is not None:
            if product.spectrum == "plant":
                return CHANNEL_NAMES_PLANT
            if product.spectrum == "rgbw":
                return CHANNEL_NAMES_AQUASKY
            if product.spectrum == "marine":
                return CHANNEL_NAMES_MARINE

        profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
        if profile == LAMP_PROFILE_PLANT_PRO:
            return CHANNEL_NAMES_PLANT_PRO
        if profile == LAMP_PROFILE_PLANT:
            return CHANNEL_NAMES_PLANT
        if profile == LAMP_PROFILE_MARINE:
            return CHANNEL_NAMES_MARINE
        if profile in (LAMP_PROFILE_AQUASKY, LAMP_PROFILE_AQUASKY3):
            return CHANNEL_NAMES_AQUASKY
        model_l = (self.model or "").lower()
        name_l = (self.name or "").lower()
        if "marine" in model_l or "marine" in name_l or "reef" in model_l or "reef" in name_l:
            return CHANNEL_NAMES_MARINE
        if "plant" in model_l or "plant" in name_l:
            return CHANNEL_NAMES_PLANT
        return CHANNEL_NAMES_AQUASKY

    def spectrum_profile(self) -> str | None:
        """Return the APK spectrum asset family for this exact fixture."""
        if (product := product_from_id(self.product_id)) is not None:
            return product.spectrum_profile

        # Explicit profile choices are the only safe fallback when no APK
        # product ID was decoded. Auto detection must not invent a generation.
        profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
        return {
            LAMP_PROFILE_AQUASKY: "aquasky_legacy",
            LAMP_PROFILE_AQUASKY3: "aquasky_current",
            LAMP_PROFILE_PLANT: "plant_legacy",
            LAMP_PROFILE_PLANT_PRO: "plant_current",
            LAMP_PROFILE_MARINE: "reef_legacy",
        }.get(profile)

    def uses_plant_spectrum(self) -> bool:
        """Return whether the fixture uses the five-channel Plant spectrum."""
        return self._channel_labels() in (
            CHANNEL_NAMES_PLANT,
            CHANNEL_NAMES_PLANT_PRO,
        )

    def uses_marine_spectrum(self) -> bool:
        """Return whether the fixture uses the five-channel Marine spectrum."""
        return self._channel_labels() == CHANNEL_NAMES_MARINE

    def light_mode(self) -> str:
        """Return the native Home Assistant colour mode for this fixture."""
        return "rgb" if self.uses_plant_spectrum() or self.uses_marine_spectrum() else "rgbw"

    def master_brightness(self) -> int:
        """Overall brightness as the brightest supported channel."""
        chans = self.numbers()
        return max((self.values.get(ch, 0) for ch in chans), default=0)

    def light_brightness_255(self) -> int:
        """Return the current light brightness on Home Assistant's 0-255 scale."""
        if self._commanded_state_matches() and self._commanded_brightness is not None:
            return self._commanded_brightness
        return round(self.master_brightness() / 100 * 255)

    def light_rgb_255(self) -> tuple[int, int, int]:
        """Return a five-channel spectrum as an RGB colour for Home Assistant."""
        if self._commanded_state_matches() and self._commanded_rgb is not None:
            return self._commanded_rgb

        mix_r = mix_g = mix_b = 0.0
        channel_rgb = MARINE_CHANNEL_RGB if self.uses_marine_spectrum() else PLANT_CHANNEL_RGB
        for channel, (channel_r, channel_g, channel_b) in channel_rgb.items():
            weight = max(0, min(100, int(self.values.get(channel, 0)))) / 100
            mix_r += channel_r * weight
            mix_g += channel_g * weight
            mix_b += channel_b * weight
        peak = max(mix_r, mix_g, mix_b, 1e-6)
        return (
            max(0, min(255, round(mix_r / peak * 255))),
            max(0, min(255, round(mix_g / peak * 255))),
            max(0, min(255, round(mix_b / peak * 255))),
        )

    def light_rgbw_255(self) -> tuple[int, int, int, int]:
        """Return AquaSky physical channels as a normalized RGBW colour."""
        if self._commanded_state_matches() and self._commanded_rgbw is not None:
            return self._commanded_rgbw
        channels = [int(self.values.get(channel, 0)) for channel in AQUASKY_NUMBERS]
        peak = max(*channels, 1)
        return tuple(round(value / peak * 255) for value in channels)  # type: ignore[return-value]

    @staticmethod
    def _ha_component_to_percent(component: int, brightness: int) -> int:
        """Scale one HA colour component and brightness to a channel percent."""
        component = max(0, min(255, int(component)))
        brightness = max(0, min(255, int(brightness)))
        return max(0, min(100, round(component / 255 * brightness / 255 * 100)))

    def channels_from_rgbw(
        self,
        rgbw: tuple[int, int, int, int],
        brightness: int,
    ) -> dict[str, int]:
        """Map an HA RGBW colour directly onto AquaSky channels."""
        channels = {
            channel: self._ha_component_to_percent(component, brightness)
            for channel, component in zip(AQUASKY_NUMBERS, rgbw, strict=True)
        }
        # RGBW has no fifth component. Preserve a fifth non-Plant channel when
        # a profile exposes one instead of silently zeroing it.
        if "channel_5" in self.numbers():
            channels["channel_5"] = int(self.values.get("channel_5", 0))
        return channels

    def channels_from_rgb(
        self,
        rgb: tuple[int, int, int],
        brightness: int,
    ) -> dict[str, int]:
        """Translate HA RGB into the active five-channel spectral layout."""
        if self.uses_marine_spectrum():
            return self._marine_channels_from_rgb(rgb, brightness)

        red = max(0, min(255, int(rgb[0]))) / 255
        green = max(0, min(255, int(rgb[1]))) / 255
        blue = max(0, min(255, int(rgb[2]))) / 255
        scale = max(0, min(255, int(brightness))) / 255

        white = min(red, green, blue)
        remaining_red = red - white
        remaining_green = green - white
        remaining_blue = blue - white
        chroma = max(remaining_red, remaining_green, remaining_blue)
        warmth = red / (red + blue + 1e-6)
        white_weight = 0.0 if chroma >= 0.85 else (1.0 - chroma) * 0.55

        def percent(value: float) -> int:
            return max(0, min(100, round(value * scale * 100)))

        return {
            "channel_1": percent(remaining_red),
            "channel_2": percent(remaining_blue),
            "channel_3": percent(white * white_weight * (0.70 * (1.0 - warmth) + 0.15)),
            "channel_4": percent(remaining_green * 0.85 + white * 0.45 * white_weight),
            "channel_5": percent(white * white_weight * (0.70 * warmth + 0.15)),
        }

    def _marine_channels_from_rgb(
        self,
        rgb: tuple[int, int, int],
        brightness: int,
    ) -> dict[str, int]:
        """Translate HA RGB into Pink/Cyan/Blue/Purple/Cold White levels."""
        red = max(0, min(255, int(rgb[0]))) / 255
        green = max(0, min(255, int(rgb[1]))) / 255
        blue = max(0, min(255, int(rgb[2]))) / 255
        scale = max(0, min(255, int(brightness))) / 255

        cold_white = min(red, green, blue)
        remaining_red = red - cold_white
        remaining_green = green - cold_white
        remaining_blue = blue - cold_white

        # Marine fixtures have no green-only emitter. Cyan is the closest
        # native channel, while shared red/blue energy maps to Purple.
        cyan = remaining_green
        remaining_blue = max(0.0, remaining_blue - cyan)
        purple = min(remaining_red, remaining_blue)
        pink = remaining_red - purple
        blue_level = remaining_blue - purple

        def percent(value: float) -> int:
            return max(0, min(100, round(value * scale * 100)))

        return {
            "channel_1": percent(pink),
            "channel_2": percent(cyan),
            "channel_3": percent(blue_level),
            "channel_4": percent(purple),
            "channel_5": percent(cold_white),
        }

    def remember_commanded_light(
        self,
        channels: dict[str, int],
        *,
        rgb: tuple[int, int, int] | None = None,
        rgbw: tuple[int, int, int, int] | None = None,
        brightness: int,
    ) -> None:
        """Remember the exact HA colour while device channels still match it."""
        self._commanded_channels = {channel: max(0, min(100, int(channels[channel]))) for channel in self.numbers()}
        self._commanded_brightness = max(1, min(255, int(brightness)))
        self._commanded_rgb = (
            (
                max(0, min(255, int(rgb[0]))),
                max(0, min(255, int(rgb[1]))),
                max(0, min(255, int(rgb[2]))),
            )
            if rgb is not None
            else None
        )
        self._commanded_rgbw = (
            (
                max(0, min(255, int(rgbw[0]))),
                max(0, min(255, int(rgbw[1]))),
                max(0, min(255, int(rgbw[2]))),
                max(0, min(255, int(rgbw[3]))),
            )
            if rgbw is not None
            else None
        )

    def clear_commanded_light(self) -> None:
        """Forget a cached HA colour after a non-light channel change."""
        self._commanded_rgb = None
        self._commanded_rgbw = None
        self._commanded_brightness = None
        self._commanded_channels = None

    def _commanded_state_matches(self) -> bool:
        """Return whether current decoded channels still match the HA command."""
        if self._commanded_channels is None:
            return False
        return all(int(self.values.get(channel, 0)) == value for channel, value in self._commanded_channels.items())

    async def async_apply_light_channels(self, values: dict[str, int]) -> bool:
        """Apply colour channels and ensure the physical fixture is powered on."""
        if not await self.async_set_channels(values):
            return False
        self.clear_commanded_light()
        if not self.values.get("led_on_off"):
            return await self.async_set_switch("led_on_off", True)
        return True

    def supports_classic_effects(self) -> bool:
        """Return whether available BLE evidence identifies a classic controller."""
        product = product_from_id(self.product_id)
        if product is not None:
            if product.native_effect_count != 11:
                return False
        else:
            profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
            identity = f"{self.name} {self.model}".lower().replace(" ", "")
            if profile not in (LAMP_PROFILE_AQUASKY, LAMP_PROFILE_AQUASKY3) and "aquasky" not in identity:
                return False
        if self.client is not None and self.client.command_write_uuid:
            return self.client.command_write_uuid.lower().startswith("00001001")

        service_uuids = [str(uuid).lower() for uuid in self.conn_info.get("service_uuids", [])]
        return any(uuid.startswith(("00001000", "00001002")) for uuid in service_uuids) and not any(
            uuid.startswith(("facebd", "0000fff0")) for uuid in service_uuids
        )

    def effect_list(self) -> list[str]:
        """Return the APK-defined effect catalogue for this product."""
        product = product_from_id(self.product_id)
        if product is not None:
            if product.native_effect_count == 4:
                return four_effect_list()
            if product.native_effect_count == 11:
                return classic_effect_list()
            return []
        if self.supports_plant_pro_effects():
            return four_effect_list()
        return classic_effect_list() if self.supports_classic_effects() or self.supports_facebd_effects() else []

    def supports_facebd_effects(self) -> bool:
        """Return whether BLE evidence identifies an effect-capable FACEBD controller."""
        if not self._uses_wifi_protocol():
            return False
        product = product_from_id(self.product_id)
        if product is not None:
            return product.native_effect_count in (4, 11)
        if self.lamp_profile == LAMP_PROFILE_AQUASKY3:
            return True
        identity = f"{self.name} {self.model}".lower().replace(" ", "")
        return "aquasky" in identity

    def supports_plant_pro_effects(self) -> bool:
        """Return whether available evidence identifies a four-effect controller."""
        product = product_from_id(self.product_id)
        if product is not None:
            return product.native_effect_count == 4
        if self.lamp_profile == LAMP_PROFILE_PLANT_PRO:
            return True
        identity = f"{self.name} {self.model}".lower().replace(" ", "")
        return "plantpro" in identity or "plant4.0" in identity

    def uses_four_effect_catalogue(self) -> bool:
        """Return whether the APK assigns this product the four-effect catalogue."""
        return self.supports_plant_pro_effects()

    def _native_effect_id(self, effect: str) -> int | None:
        """Resolve an effect name using this product's APK catalogue."""
        return four_effect_id(effect) if self.uses_four_effect_catalogue() else effect_id(effect)

    def _native_effect_name(self, effect_code: int) -> str | None:
        """Resolve a wire effect ID using this product's APK catalogue."""
        return four_effect_name(effect_code) if self.uses_four_effect_catalogue() else effect_name(effect_code)

    def _channel_snapshot(self) -> dict[str, int]:
        """Return the current supported static channel values."""
        return {channel: int(self.values.get(channel, 0)) for channel in self.numbers()}

    def _channels_after_effect(self) -> dict[str, int]:
        """Return a useful static channel mix for leaving an effect."""
        targets = self._effect_restore_channels or self._channel_snapshot()
        if any(targets.values()):
            return dict(targets)
        targets = {channel: 0 for channel in self.numbers()}
        targets["channel_4"] = 100
        return targets

    def _clear_effect_state(self) -> None:
        """Clear controller-effect state after a successful static command."""
        self.values["effect"] = None
        self._effect_restore_channels = None

    async def async_set_effect(self, effect: str) -> bool:
        """Start one APK-native effect on a supported Fluval controller."""
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval effect before BLE device is available")
            return False

        plant_pro = self._uses_plant_pro_protocol()
        facebd = self._uses_wifi_protocol()
        effect_code = self._native_effect_id(effect)
        if effect_code is None:
            return False
        if facebd and not self.supports_facebd_effects():
            _LOGGER.warning("FACEBD weather effects require an AquaSky controller identity")
            return False
        if not plant_pro and not facebd and not self.supports_classic_effects():
            _LOGGER.warning(
                "Classic weather effects are not valid for Fluval transport %s",
                self.client.command_write_uuid if self.client else None,
            )
            return False

        old_values = dict(self.values)
        old_restore = self._effect_restore_channels
        if not self.values.get("effect"):
            static_channels = self._channel_snapshot()
            if any(static_channels.values()):
                self._effect_restore_channels = static_channels

        packets: list[bytes] = []
        if self.values.get("mode") != "manual":
            packets.append(
                protocol.spp_mode_packet(MODE_TO_CODE["manual"])
                if plant_pro
                else protocol.wifi_mode_packet(MODE_TO_CODE["manual"])
                if facebd
                else protocol.old_mode_packet(MODE_TO_CODE["manual"])
            )
        if not self.values.get("led_on_off"):
            packets.append(
                protocol.spp_switch_packet(True)
                if plant_pro
                else protocol.wifi_switch_packet(True)
                if facebd
                else protocol.old_switch_packet(True)
            )
        packets.append(
            protocol.spp_effect_packet(effect_code)
            if plant_pro
            else protocol.wifi_effect_packet(effect_code)
            if facebd
            else protocol.old_weather_effect_packet(effect_code)
        )

        for packet in packets:
            if not await self._async_send_packet(packet):
                self.values = old_values
                self._effect_restore_channels = old_restore
                return False

        self.values["mode"] = "manual"
        self.values["led_on_off"] = True
        self.values["effect"] = effect
        self.clear_commanded_light()
        for handler in self.updates_component:
            handler()
        return True

    async def async_set_native_auto_schedule(
        self,
        schedule: dict[str, Any],
        *,
        activate: bool = True,
    ) -> bool:
        """Store a protocol-native Auto schedule in the fixture."""
        if not await self._async_prepare_command():
            return False

        if self._uses_wifi_protocol():
            packet = protocol.wifi_auto_schedule_packet(
                sunrise=schedule["sunrise"],
                sunset=schedule["sunset"],
                sleep=schedule.get("sleep"),
                day_levels=schedule["day_levels"],
                night_levels=schedule["night_levels"],
                channel_count=self._resolved_channel_count(),
            )
            native_protocol = "facebd"
        elif self._uses_plant_pro_protocol():
            packet = protocol.spp_auto_schedule_packet(
                sunrise=schedule["sunrise"],
                sunset=schedule["sunset"],
                sleep=schedule.get("sleep"),
                day_levels=schedule["day_levels"],
                night_levels=schedule["night_levels"],
            )
            native_protocol = "plant_pro"
        else:
            packet = protocol.old_auto_schedule_packet(
                sunrise=schedule["sunrise"],
                sunset=schedule["sunset"],
                sleep=schedule.get("sleep"),
                day_levels=schedule["day_levels"],
                night_levels=schedule["night_levels"],
                channel_count=self._resolved_channel_count(),
            )
            native_protocol = "classic"

        if not await self._async_send_packet(packet):
            return False
        if activate and not await self._async_send_packet(self._native_mode_packet("automatic")):
            return False
        if activate:
            self.values["mode"] = "automatic"
        # A successful write confirms submission, not readback. Discard any
        # older fixture copy so native preview cannot render stale levels.
        self.values.pop("native_auto_schedule", None)
        self.diagnostics.update(
            {
                "status": "native_auto_schedule_submitted",
                "native_schedule_protocol": native_protocol,
                "native_auto_schedule_packet": packet.hex(),
            }
        )
        self._notify_diagnostics_throttled()
        return True

    def native_pro_schedule_limits(self) -> tuple[str, int, int]:
        """Return the APK-defined Professional-schedule limits for this fixture."""
        if self._uses_wifi_protocol():
            return "facebd", protocol.WIFI_MIN_PRO_POINTS, protocol.WIFI_MAX_PRO_POINTS
        if self._uses_plant_pro_protocol():
            return "plant_pro", protocol.SPP_MIN_PRO_POINTS, protocol.SPP_MAX_PRO_POINTS
        return "classic", protocol.OLD_MIN_PRO_POINTS, protocol.OLD_MAX_PRO_POINTS

    async def async_set_native_pro_schedule(
        self,
        points: list[dict[str, Any]],
        *,
        activate: bool = True,
    ) -> bool:
        """Store a protocol-native Professional schedule in the fixture."""
        if points and all("time" not in point and "levels" in point for point in points):
            normalized = [
                {
                    "minute": (int(point["hour"]) * 60) + int(point["minute"]),
                    **{f"channel_{index}": int(level) for index, level in enumerate(point["levels"], start=1)},
                }
                for point in points
            ]
        else:
            normalized = self._normalize_schedule_points(points)

        if not protocol.SPP_MIN_PRO_POINTS <= len(normalized) <= protocol.SPP_MAX_PRO_POINTS:
            self._set_diagnostic_error(
                "invalid_native_schedule",
                f"Professional schedules require {protocol.SPP_MIN_PRO_POINTS} to {protocol.SPP_MAX_PRO_POINTS} points",
            )
            return False
        if not await self._async_prepare_command():
            return False

        native_protocol, minimum, maximum = self.native_pro_schedule_limits()

        if not minimum <= len(normalized) <= maximum:
            self._set_diagnostic_error(
                "invalid_native_schedule",
                f"{native_protocol} Professional schedules require {minimum} to {maximum} points",
            )
            return False

        if native_protocol == "facebd":
            packet = protocol.wifi_pro_schedule_packet(
                normalized,
                channel_count=self._resolved_channel_count(),
            )
        elif native_protocol == "plant_pro":
            spp_points = [
                {
                    "hour": point["minute"] // 60,
                    "minute": point["minute"] % 60,
                    "levels": [point.get(f"channel_{index}", 0) for index in range(1, 6)],
                }
                for point in normalized
            ]
            packet = protocol.spp_pro_schedule_packet(spp_points)
        else:
            packet = protocol.old_pro_schedule_packet(
                normalized,
                channel_count=self._resolved_channel_count(),
            )

        if not await self._async_send_packet(packet):
            return False
        if activate and not await self._async_send_packet(self._native_mode_packet("professional")):
            return False
        if activate:
            self.values["mode"] = "professional"
        self.values.pop("native_pro_schedule", None)
        self.diagnostics.update(
            {
                "status": "native_pro_schedule_submitted",
                "native_schedule_protocol": native_protocol,
                "native_pro_schedule_points": len(normalized),
                "native_pro_schedule_packet": packet.hex(),
            }
        )
        self._notify_diagnostics_throttled()
        return True

    async def async_set_native_effect_schedule(self, windows: list[dict[str, Any]]) -> bool:
        """Store APK-native timed weather-effect windows in the fixture."""
        if not await self._async_prepare_command():
            return False

        if self._uses_plant_pro_protocol():
            native_protocol = "plant_pro"
            packet_builder = protocol.spp_effect_schedule_packet
        elif self._uses_wifi_protocol() and self.supports_facebd_effects():
            native_protocol = "facebd"
            packet_builder = protocol.wifi_effect_schedule_packet
        elif self.supports_classic_effects():
            native_protocol = "classic"
            packet_builder = protocol.old_effect_schedule_packet
        else:
            self._set_diagnostic_error(
                "unsupported_transport",
                "Timed native effects require a supported classic, AquaSky 3.0/FACEBD, or Plant Pro controller",
            )
            return False

        wire_windows = []
        for window in windows:
            effect_code = window.get("effect_id")
            if isinstance(window.get("effect"), str):
                effect_code = self._native_effect_id(window["effect"])
            if not isinstance(effect_code, int) or self._native_effect_name(effect_code) is None:
                self._set_diagnostic_error(
                    "invalid_native_effect_schedule",
                    f"Effect {window.get('effect', effect_code)!r} is not supported by this product",
                )
                return False
            wire_windows.append({**window, "effect_id": effect_code})

        try:
            packet = packet_builder(wire_windows)
        except (KeyError, TypeError, ValueError) as err:
            self._set_diagnostic_error("invalid_native_effect_schedule", str(err))
            return False
        if not await self._async_send_packet(packet):
            return False
        normalized = [
            {
                "enabled": bool(window.get("enabled", True)),
                "weekdays": list(window["weekdays"]),
                "start": f"{window['start_hour']:02d}:{window['start_minute']:02d}",
                "end": f"{window['end_hour']:02d}:{window['end_minute']:02d}",
                "effect_id": window["effect_id"],
                "effect": self._native_effect_name(window["effect_id"]),
            }
            for window in wire_windows
        ]
        self.values["native_effect_schedule"] = normalized
        self.diagnostics.update(
            {
                "status": "native_effect_schedule_submitted",
                "native_schedule_protocol": native_protocol,
                "native_effect_schedule": normalized,
                "native_effect_schedule_packet": packet.hex(),
            }
        )
        if native_protocol == "plant_pro":
            self.diagnostics["plant_pro_effect_schedule"] = normalized
        self._notify_diagnostics_throttled()
        return True

    async def async_stop_effect(self) -> bool:
        """Stop a native effect by restoring the preceding static channel mix."""
        if not self.values.get("effect"):
            return True
        return await self.async_set_channels(self._channels_after_effect(), force=True)

    async def async_set_master_brightness(self, level: int) -> bool:
        """Scale all supported channels to level, preserving ratios."""
        level = min(100, max(0, round(level / 10) if level > 100 else int(level)))
        chans = self.numbers()
        current_max = max((self.values.get(ch, 0) for ch in chans), default=0)
        if current_max <= 0:
            targets = {channel: level for channel in chans}
        else:
            factor = level / current_max
            targets = {channel: min(100, max(0, round(self.values.get(channel, 0) * factor))) for channel in chans}
        return await self.async_set_channels(targets)

    def entity_name(self, attr: str) -> str:
        """Return a user-facing entity suffix for this device attribute."""
        labels = self._channel_labels()
        if attr in labels:
            return labels[attr]
        return attr.replace("_", " ").title()

    def selects(self) -> list[str]:
        """List of select boxes provided by the device."""
        return list(SELECTS)

    def sensors(self) -> list[str]:
        """List of diagnostics sensors provided by the device."""
        return list(SENSORS)

    def supports_facebd_dst_control(self) -> bool:
        """Return whether this fixture uses FluvalConnect's FACEBD DST setting."""
        return self._uses_wifi_protocol()

    def attribute(self, attr: str) -> Attribute:
        """Provide attributes to the entities like switches, numbers etc."""
        if attr == "connection":
            extra = dict(self.conn_info)
            extra["gatt_connected"] = self.connected
            return Attribute(is_on=self.is_reachable(), extra=extra)
        if attr.startswith("channel_"):
            return Attribute(min=0, max=100, step=1, value=self.values[attr])
        if attr == "mode":
            return Attribute(options=MODES, default=self.values[attr])
        if attr == "led_on_off":
            return Attribute(is_on=self.values[attr])
        if attr == "daylight_saving_time":
            value = self.values.get(attr)
            return Attribute(is_on=value) if isinstance(value, bool) else Attribute()
        if attr == "rssi":
            return Attribute(
                value=self.conn_info.get("rssi"),
                native_unit_of_measurement="dBm",
                extra={
                    "source_name": self.conn_info.get("advertisement_source"),
                    "source_address": self.conn_info.get("advertisement_source_address"),
                    "source_type": self.conn_info.get("advertisement_source_type"),
                    "last_advertisement": self.conn_info.get("rssi_updated_at"),
                    "last_updated": self.conn_info.get("rssi_updated_at"),
                },
            )
        if attr == "active_connection_source":
            return Attribute(
                value=self.conn_info.get("active_connection_source") if self.connected else None,
                extra={
                    "source_name": self.conn_info.get("active_connection_source"),
                    "source_address": self.conn_info.get("active_connection_source_address"),
                    "source_type": self.conn_info.get("active_connection_source_type"),
                    "connected_at": self.conn_info.get("active_connection_connected_at"),
                    "gatt_connected": self.connected,
                },
            )
        if attr == "advertisement_source":
            return Attribute(
                value=self.conn_info.get("advertisement_source"),
                extra={
                    "source_name": self.conn_info.get("advertisement_source"),
                    "source_address": self.conn_info.get("advertisement_source_address"),
                    "source_type": self.conn_info.get("advertisement_source_type"),
                    "last_updated": self.conn_info.get("advertisement_updated_at"),
                },
            )
        if attr == "last_seen":
            return Attribute(value=self.conn_info.get("last_seen"))
        return Attribute()

    def register_update(self, attr: str, handler: Callable):
        """Register handlers for updates."""
        if attr in ("connection", "rssi", "last_seen", "active_connection_source", "advertisement_source"):
            self.updates_connect.append(handler)
        else:
            self.updates_component.append(handler)

    def deregister_update(self, attr: str, handler: Callable):
        """Remove a previously registered update handler."""
        target = (
            self.updates_connect
            if attr in ("connection", "rssi", "last_seen", "active_connection_source", "advertisement_source")
            else self.updates_component
        )
        with contextlib.suppress(ValueError):
            target.remove(handler)

    async def async_set_value(self, attr: str, value: int) -> bool:
        """Set values received by entities such as numbers and switches."""
        if attr.startswith("channel_"):
            return await self.async_set_channels({attr: int(value)})

        _LOGGER.debug("Value %s changed to %s", attr, value)
        return False

    async def async_set_channels(
        self,
        values: dict[str, int],
        *,
        transition: int = 0,
        step_seconds: int = TRANSITION_STEP_SECONDS,
        force: bool = False,
    ) -> bool:
        """Set multiple channel values, optionally ramping over time."""
        channels = self.numbers()
        effect_active = bool(self.values.get("effect"))
        force = force or effect_active
        targets = {channel: max(0, min(100, int(values.get(channel, self.values[channel])))) for channel in channels}
        if not targets:
            return False

        if not force and all(int(self.values.get(channel, -1)) == value for channel, value in targets.items()):
            _LOGGER.debug("Skipping Fluval channel write because targets are unchanged: %s", targets)
            return True

        old_values = dict(self.values)
        changed_channels = [channel for channel, value in targets.items() if int(old_values.get(channel, -1)) != value]
        single_channel = changed_channels[0] if len(changed_channels) == 1 and not force else None
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval channel before BLE device is available")
            self.values = old_values
            return False

        if self.values.get("mode") != "manual":
            if self._uses_wifi_protocol():
                ok = await self._async_send_packet(protocol.wifi_mode_packet(MODE_TO_CODE["manual"]))
            elif self._uses_plant_pro_protocol():
                ok = await self._async_send_packet(protocol.spp_mode_packet(MODE_TO_CODE["manual"]))
            else:
                ok = await self._async_send_packet(protocol.old_mode_packet(MODE_TO_CODE["manual"]))
            if not ok:
                self.values = old_values
                return False
            self.values["mode"] = "manual"

        if transition <= 0:
            for channel, value in targets.items():
                self.values[channel] = value
            ok = await self._async_send_channel_state(
                old_values,
                force_power=force,
                single_channel=single_channel,
            )
            if ok and effect_active:
                self._clear_effect_state()
                for handler in self.updates_component:
                    handler()
            return ok

        steps = max(1, int(transition / max(1, step_seconds)))
        start_values = {channel: int(old_values[channel]) for channel in channels}
        for step in range(1, steps + 1):
            ratio = step / steps
            for channel in channels:
                start = start_values[channel]
                end = targets[channel]
                self.values[channel] = round(start + ((end - start) * ratio))
            if not await self._async_send_channel_state(
                old_values,
                force_power=force,
                single_channel=single_channel,
            ):
                self.values = old_values
                return False
            if step < steps:
                await asyncio.sleep(step_seconds)

        if effect_active:
            self._clear_effect_state()
            for handler in self.updates_component:
                handler()
        return True

    async def _async_send_channel_state(
        self,
        old_values: dict[str, Any],
        *,
        force_power: bool = False,
        single_channel: str | None = None,
    ) -> bool:
        """Send the current channel values to the controller."""
        channel_index = self.numbers().index(single_channel) if single_channel is not None else None
        if self._uses_wifi_protocol():
            any_channel_on = any(self._channel_values())
            if any_channel_on and (force_power or not self.values["led_on_off"]):
                self.values["led_on_off"] = True
                if not await self._async_send_packet(protocol.wifi_switch_packet(True)):
                    self.values = old_values
                    return False
            packet = (
                protocol.wifi_single_zone_packet(channel_index, self.values[single_channel])
                if channel_index is not None and single_channel is not None
                else protocol.wifi_all_zone_packet(self._channel_values())
            )
            ok = await self._async_send_packet(packet)
            if ok and not any_channel_on and (force_power or self.values["led_on_off"]):
                ok = await self._async_send_packet(protocol.wifi_switch_packet(False))
                if ok:
                    self.values["led_on_off"] = False
        elif self._uses_plant_pro_protocol():
            any_channel_on = any(self._channel_values())
            if any_channel_on and (force_power or not self.values["led_on_off"]):
                self.values["led_on_off"] = True
                if not await self._async_send_packet(protocol.spp_switch_packet(True)):
                    self.values = old_values
                    return False
            packet = (
                protocol.spp_single_zone_packet(channel_index, self.values[single_channel])
                if channel_index is not None and single_channel is not None
                else protocol.spp_all_zone_packet(self._channel_values())
            )
            ok = await self._async_send_packet(packet)
            if ok and not any_channel_on and (force_power or self.values["led_on_off"]):
                ok = await self._async_send_packet(protocol.spp_switch_packet(False))
                if ok:
                    self.values["led_on_off"] = False
        else:
            ok = await self._async_send_packet(protocol.old_all_zone_packet(self._channel_values()))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        return ok

    async def async_preview_schedule(
        self,
        points: list[dict[str, Any]],
        *,
        duration: int = 60,
        step_seconds: int = PREVIEW_STEP_SECONDS,
    ) -> bool:
        """Preview a 24-hour schedule on the real light in compressed time."""
        await self.async_stop_preview()
        self.preview_restore_values = {channel: int(self.values.get(channel, 0)) for channel in self.numbers()}
        self.preview_restore_mode = (
            self.values.get("mode") if self.values.get("mode") in {"automatic", "professional"} else None
        )
        self.preview_task = asyncio.create_task(self._async_preview_schedule(points, duration, step_seconds))
        return True

    async def async_preview_native_schedule(self, minute: int, schedule_type: str) -> bool:
        """Preview one minute of a schedule already stored by the fixture."""
        if schedule_type not in {"auto", "professional"} or not 0 <= minute < DAY_MINUTES:
            self._set_diagnostic_error(
                "invalid_native_preview", "Native preview requires Auto or Professional and minute 0-1439"
            )
            return False

        schedule_key = "native_auto_schedule" if schedule_type == "auto" else "native_pro_schedule"
        if not self.values.get(schedule_key):
            self._set_diagnostic_error(
                "native_preview_unavailable",
                f"Load the fixture's {schedule_type.title()} schedule before previewing it",
            )
            return False

        if self.preview_task is not None or self.preview_restore_values is not None:
            if not await self.async_stop_preview():
                return False
        if not await self._async_prepare_command():
            return False

        target_mode = "automatic" if schedule_type == "auto" else "professional"
        starting = not self.native_preview_active
        previous_type = self.native_preview_schedule_type
        if starting:
            current_mode = self.values.get("mode")
            self.native_preview_restore_mode = current_mode if current_mode in MODES else "manual"

        mode_changed = self.values.get("mode") != target_mode or previous_type not in (None, schedule_type)
        if mode_changed and (self._uses_wifi_protocol() or self._uses_plant_pro_protocol()):
            if not await self._async_send_packet(self._native_mode_packet(target_mode)):
                if starting:
                    self.native_preview_restore_mode = None
                return False
            self.values["mode"] = target_mode

        if self._uses_wifi_protocol():
            packet = protocol.wifi_auto_preview_packet(minute)
            native_protocol = "facebd"
        elif self._uses_plant_pro_protocol():
            packet = protocol.spp_schedule_preview_packet(minute)
            native_protocol = "plant_pro"
        else:
            levels = self._classic_native_preview_levels(schedule_type, minute)
            if levels is None:
                return False
            packet = protocol.old_auto_preview_packet(levels)
            native_protocol = "classic"

        if not await self._async_send_packet(packet):
            if starting:
                await self._async_restore_native_preview_mode()
            return False

        self.native_preview_active = True
        self.native_preview_schedule_type = schedule_type
        self.diagnostics.update(
            {
                "status": "native_preview_running",
                "native_preview_protocol": native_protocol,
                "native_preview_schedule_type": schedule_type,
                "preview_minute": minute,
                "preview_time": self._format_minute(minute),
            }
        )
        self._notify_diagnostics_throttled()
        return True

    async def async_stop_preview(self) -> bool:
        """Stop any running editor or fixture-native schedule preview."""
        restored = True
        if self.preview_task and not self.preview_task.done():
            self.preview_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.preview_task
        self.preview_task = None
        restore_mode = self.preview_restore_mode
        self.preview_restore_mode = None
        if restore_mode is not None:
            self.preview_restore_values = None
            restored = await self.async_select_option("mode", restore_mode)
        elif self.preview_restore_values:
            restore_values = self.preview_restore_values
            self.preview_restore_values = None
            restored = await self.async_set_channels(restore_values)

        if self.native_preview_active:
            if not await self._async_prepare_command():
                return False
            if self._uses_wifi_protocol():
                stopped = await self._async_send_packet(protocol.wifi_auto_preview_packet(None))
            elif self._uses_plant_pro_protocol():
                stopped = await self._async_send_packet(protocol.spp_schedule_preview_packet(None))
            else:
                stopped = await self._async_send_packet(protocol.old_auto_preview_packet(None))
            if not stopped:
                self._set_diagnostic_error("native_preview_stop_failed", "Unable to stop fixture schedule preview")
                return False
            if not await self._async_restore_native_preview_mode():
                self._set_diagnostic_error(
                    "native_preview_restore_failed", "Preview stopped but fixture mode was not restored"
                )
                return False
            self.diagnostics["status"] = "native_preview_stopped"
            self._notify_diagnostics_throttled()
        return restored

    async def _async_restore_native_preview_mode(self) -> bool:
        """Restore the fixture mode saved before native preview."""
        restore_mode = self.native_preview_restore_mode
        should_restore = self._uses_wifi_protocol() or self._uses_plant_pro_protocol()
        if restore_mode in MODES and should_restore and self.values.get("mode") != restore_mode:
            if not await self._async_send_packet(self._native_mode_packet(restore_mode)):
                return False
            self.values["mode"] = restore_mode
        self.native_preview_active = False
        self.native_preview_schedule_type = None
        self.native_preview_restore_mode = None
        return True

    async def _async_preview_schedule(
        self,
        points: list[dict[str, Any]],
        duration: int,
        step_seconds: int,
    ) -> None:
        """Run the schedule preview task."""
        normalized = self._normalize_schedule_points(points)
        if len(normalized) < 2:
            self._set_diagnostic_error(
                "preview_failed",
                "Schedule preview requires at least two points",
            )
            return

        steps = max(1, int(duration / max(1, step_seconds)))
        self.diagnostics.update(
            {
                "status": "preview_running",
                "schedule_points": normalized,
            }
        )
        for handler in self.updates_connect:
            handler()

        try:
            for step in range(steps + 1):
                minute = round((step / steps) * DAY_MINUTES) % DAY_MINUTES
                channels = self._interpolate_schedule(normalized, minute)
                self.diagnostics.update(
                    {
                        "status": "preview_running",
                        "preview_minute": minute,
                        "preview_time": self._format_minute(minute),
                        "spectrum": self._spectrum_report(channels),
                    }
                )
                await self.async_set_channels(channels)
                if step < steps:
                    await asyncio.sleep(step_seconds)
        except asyncio.CancelledError:
            self.diagnostics["status"] = "preview_stopped"
            raise
        else:
            self.diagnostics["status"] = "preview_complete"
        finally:
            for handler in self.updates_connect:
                handler()

    def _normalize_schedule_points(self, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize schedule points to minutes and channel values."""
        normalized = []
        for point in points:
            minute = self._parse_time_to_minute(str(point["time"]))
            channels = {
                channel: max(0, min(100, int(point.get(channel, point.get(color, 0)))))
                for channel, color in (
                    ("channel_1", "red"),
                    ("channel_2", "green"),
                    ("channel_3", "blue"),
                    ("channel_4", "white"),
                    ("channel_5", "channel_5"),
                )
            }
            normalized.append({"minute": minute, "time": self._format_minute(minute), **channels})

        return sorted(normalized, key=lambda item: item["minute"])

    def _interpolate_schedule(self, points: list[dict[str, Any]], minute: int) -> dict[str, int]:
        """Return interpolated channel values for one minute of the day."""
        previous = points[-1]
        next_point = points[0]
        for index, point in enumerate(points):
            if point["minute"] <= minute:
                previous = point
                next_point = points[(index + 1) % len(points)]

        start = previous["minute"]
        end = next_point["minute"]
        if end <= start:
            end += DAY_MINUTES
        current = minute if minute >= start else minute + DAY_MINUTES
        ratio = 0 if end == start else (current - start) / (end - start)

        return {
            channel: round(previous[channel] + ((next_point[channel] - previous[channel]) * ratio))
            for channel in NUMBERS
        }

    def _classic_native_preview_levels(self, schedule_type: str, minute: int) -> list[int] | None:
        """Calculate the APK's classic ``680B`` values from fixture readback."""
        if schedule_type == "professional":
            raw_points = self.values.get("native_pro_schedule")
            if not isinstance(raw_points, list):
                raw_points = []
            points = [
                {
                    "minute": int(point["minute"]) % DAY_MINUTES,
                    **{channel: max(0, min(100, int(point.get(channel, 0)))) for channel in NUMBERS},
                }
                for point in raw_points
                if isinstance(point, dict) and "minute" in point
            ]
        else:
            points = self._classic_auto_preview_points(self.values.get("native_auto_schedule"))

        if len(points) < 2:
            self._set_diagnostic_error(
                "native_preview_unavailable",
                f"The fixture did not report a complete {schedule_type.title()} schedule",
            )
            return None
        points.sort(key=lambda point: point["minute"])
        channels = self._interpolate_schedule(points, minute)
        return [channels[channel] for channel in self.numbers()]

    def _classic_auto_preview_points(self, schedule: object) -> list[dict[str, Any]]:
        """Expand classic Auto readback into the points used by the APK preview."""
        if not isinstance(schedule, dict):
            return []
        sunrise = self._native_schedule_minute(schedule.get("sunrise"))
        sunset = self._native_schedule_minute(schedule.get("sunset"))
        sleep = self._native_schedule_minute(schedule.get("sleep"))
        day_levels = schedule.get("day_levels")
        night_levels = schedule.get("night_levels")
        if sunrise is None or sunset is None or not isinstance(day_levels, list) or not isinstance(night_levels, list):
            return []

        channel_count = len(self.numbers())
        if len(day_levels) < channel_count or len(night_levels) < channel_count:
            return []
        day = [max(0, min(100, int(value))) for value in day_levels[:channel_count]]
        night = [max(0, min(100, int(value))) for value in night_levels[:channel_count]]
        off = [0] * channel_count
        sunrise_ramp = max(0, min(240, int(schedule["sunrise"].get("ramp", 0))))
        sunset_ramp = max(0, min(240, int(schedule["sunset"].get("ramp", 0))))

        def point(point_minute: int, levels: list[int]) -> dict[str, Any]:
            return {
                "minute": point_minute % DAY_MINUTES,
                **{channel: levels[index] if index < len(levels) else 0 for index, channel in enumerate(NUMBERS)},
            }

        points = [
            point(sunrise, off if sleep is not None else night),
            point(sunrise + sunrise_ramp, day),
            point(sunset - sunset_ramp, day),
            point(sunset, night),
        ]
        if sleep is not None:
            # FluvalConnect uses two points at the sleep minute: retain night
            # until that minute, then switch off for the overnight segment.
            points.extend((point(sleep, night), point(sleep, off)))
        return points

    @staticmethod
    def _native_schedule_minute(value: object) -> int | None:
        """Read one protocol-neutral fixture time object."""
        if not isinstance(value, dict):
            return None
        hour = value.get("hour")
        minute = value.get("minute")
        if not isinstance(hour, int) or not isinstance(minute, int) or not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None
        return hour * 60 + minute

    def _spectrum_report(self, channels: dict[str, int]) -> dict[str, Any]:
        """Return graph-friendly spectrum data for diagnostics and previews."""
        color_values = {
            "red": channels["channel_1"],
            "green": channels["channel_2"],
            "blue": channels["channel_3"],
            "white": channels["channel_4"],
            "channel_5": channels["channel_5"],
        }
        return {
            "channels": color_values,
            "peak": max(color_values.values()),
            "total": sum(color_values.values()),
        }

    def _parse_time_to_minute(self, value: str) -> int:
        """Parse HH:MM into minutes from midnight."""
        hour, minute = value.split(":", 1)
        return ((int(hour) % 24) * 60) + int(minute)

    def _format_minute(self, minute: int) -> str:
        """Format minutes from midnight as HH:MM."""
        minute %= DAY_MINUTES
        return f"{minute // 60:02d}:{minute % 60:02d}"

    async def async_set_switch(self, attr: str, value: bool) -> bool:
        """Set switch values and send the updated state to the light."""
        _LOGGER.debug("Switch %s changed to %s", attr, value)
        old_values = dict(self.values)
        self.values[attr] = value
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval switch before BLE device is available")
            self.values = old_values
            return False

        if self._uses_wifi_protocol():
            ok = await self._async_send_packet(protocol.wifi_switch_packet(value))
        elif self._uses_plant_pro_protocol():
            ok = await self._async_send_packet(protocol.spp_switch_packet(value))
        else:
            ok = await self._async_send_packet(protocol.old_switch_packet(value))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        elif attr == "led_on_off" and not value and self.values.get("effect"):
            self._clear_effect_state()
            for handler in self.updates_component:
                handler()
        return ok

    async def async_set_daylight_saving_time(self, enabled: bool) -> bool:
        """Set the fixture-owned FACEBD daylight-saving flag."""
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval daylight-saving time before BLE is available")
            return False
        if not self._uses_wifi_protocol():
            self._set_diagnostic_error(
                "unsupported_daylight_saving_time",
                "Daylight-saving control is supported only by FACEBD fixtures",
            )
            return False

        previous = self.values.get("daylight_saving_time")
        self.values["daylight_saving_time"] = enabled
        if not await self._async_send_packet(protocol.wifi_dst_packet(enabled)):
            if isinstance(previous, bool):
                self.values["daylight_saving_time"] = previous
            else:
                self.values.pop("daylight_saving_time", None)
            for handler in self.updates_component:
                handler()
            return False

        self.diagnostics["daylight_saving_time"] = enabled
        return True

    def _manual_preset_values(self, slot: int) -> list[int] | None:
        """Return one complete classic preset from fixture readback."""
        presets = self.values.get("native_manual_presets")
        channel_count = self._resolved_channel_count()
        if (
            not isinstance(presets, list)
            or len(presets) != 4
            or not isinstance(presets[slot - 1], list)
            or len(presets[slot - 1]) != channel_count
        ):
            return None
        return [int(value) for value in presets[slot - 1]]

    async def async_recall_manual_preset(self, slot: int) -> bool:
        """Apply one fixture-resident classic P1-P4 preset as FluvalConnect does."""
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 4:
            self._set_diagnostic_error("invalid_manual_preset", "Manual preset slot must be between 1 and 4")
            return False
        if not await self._async_prepare_command():
            return False
        if self._uses_wifi_protocol() or self._uses_plant_pro_protocol():
            self._set_diagnostic_error(
                "unsupported_manual_preset",
                "Fixture-resident manual presets are supported only by classic Fluval controllers",
            )
            return False

        preset = self._manual_preset_values(slot)
        if preset is None:
            await self.async_refresh_state()
            preset = self._manual_preset_values(slot)
        if preset is None:
            self._set_diagnostic_error(
                "manual_preset_unavailable",
                "Manual preset readback is unavailable; put the fixture in Manual mode and retry",
            )
            return False
        if not self.values.get("led_on_off"):
            self._set_diagnostic_error(
                "manual_preset_requires_light_on",
                "Turn on the fixture before recalling a manual preset",
            )
            return False

        targets = {channel: int(preset[index]) for index, channel in enumerate(self.numbers())}
        if not await self.async_set_channels(targets, force=True):
            return False
        self.diagnostics.update(
            {
                "status": "manual_preset_recalled",
                "manual_preset_slot": slot,
                "last_error": None,
            }
        )
        return True

    async def async_save_manual_preset(self, slot: int) -> bool:
        """Save the current classic channel state in fixture slot P1-P4."""
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 4:
            self._set_diagnostic_error("invalid_manual_preset", "Manual preset slot must be between 1 and 4")
            return False
        if not await self._async_prepare_command():
            return False
        if self._uses_wifi_protocol() or self._uses_plant_pro_protocol():
            self._set_diagnostic_error(
                "unsupported_manual_preset",
                "Fixture-resident manual presets are supported only by classic Fluval controllers",
            )
            return False
        if self.values.get("mode") != "manual":
            self._set_diagnostic_error(
                "manual_preset_requires_manual_mode",
                "Select Manual mode before saving a fixture preset",
            )
            return False
        if not await self._async_send_packet(protocol.old_save_manual_preset_packet(slot - 1)):
            return False

        presets = self.values.get("native_manual_presets")
        channel_count = self._resolved_channel_count()
        if (
            isinstance(presets, list)
            and len(presets) == 4
            and all(isinstance(preset, list) and len(preset) == channel_count for preset in presets)
        ):
            updated_presets = [list(preset) for preset in presets]
            updated_presets[slot - 1] = self._channel_values()
            self.values["native_manual_presets"] = updated_presets
            self.diagnostics["native_manual_presets"] = updated_presets
        self.diagnostics.update(
            {
                "status": "manual_preset_saved",
                "manual_preset_slot": slot,
                "last_error": None,
            }
        )
        return True

    async def async_identify(self) -> bool:
        """Ask the fixture to identify itself using FluvalConnect's Find command."""
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot identify Fluval light before BLE device is available")
            return False

        if self._uses_wifi_protocol():
            packet = protocol.wifi_find_packet()
        elif self._uses_plant_pro_protocol():
            packet = protocol.spp_find_packet()
        else:
            packet = protocol.old_find_packet()
        return await self._async_send_packet(packet)

    async def async_select_option(self, attr: str, option: str) -> bool:
        """Set select values and send the updated state to the light."""
        if attr != "mode" or option not in MODES:
            return False

        _LOGGER.debug("Mode changed to %s", option)
        old_values = dict(self.values)
        self.values[attr] = option
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval mode before BLE device is available")
            self.values = old_values
            return False

        if self._uses_wifi_protocol():
            ok = await self._async_send_packet(protocol.wifi_mode_packet(MODE_TO_CODE[option]))
        elif self._uses_plant_pro_protocol():
            ok = await self._async_send_packet(protocol.spp_mode_packet(MODE_TO_CODE[option]))
        else:
            ok = await self._async_send_packet(protocol.old_mode_packet(MODE_TO_CODE[option]))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        return ok

    async def _async_on_client_ready(self) -> None:
        """Send the APK's clock command before the initial parameter read."""
        async with self._clock_sync_lock:
            if self._clock_synced or self._clock_sync_started:
                return
            self._clock_sync_started = await self._async_send_clock_command()
            if not self._clock_sync_started:
                _LOGGER.warning("Fluval clock sync failed after connect for %s", self.address)

    async def _async_on_client_state_ready(self, state: dict[int, object]) -> None:
        """Finish APK initialization after the initial parameter read."""
        async with self._clock_sync_lock:
            if self._clock_synced or not self._clock_sync_started:
                return
            if not await self._async_finish_clock_sync(state):
                _LOGGER.warning("Fluval timezone sync failed after connect for %s", self.address)

    async def async_sync_clock(self, *, force: bool = False) -> bool:
        """Run the APK's clock, state-read, and timezone initialization sequence."""
        if self._clock_synced and not force:
            return True

        async with self._clock_sync_lock:
            if self._clock_synced and not force:
                return True

            if self.client is None:
                if not await self._async_ensure_client():
                    return False
            elif not await self.client.ensure_connected():
                self._set_diagnostic_error(
                    "clock_sync_failed",
                    self.client.last_error or "Unable to connect for clock sync",
                )
                return False

            self._clock_sync_started = await self._async_send_clock_command()
            if not self._clock_sync_started:
                self._set_diagnostic_error("clock_sync_failed", "Unable to sync lamp clock")
                return False

            try:
                await self.client.request_state()
            except (TimeoutError, BleakError) as err:
                _LOGGER.debug("Unable to read Fluval state during clock sync", exc_info=err)

            return await self._async_finish_clock_sync(self.client.observed_state)

    async def _async_send_clock_command(self) -> bool:
        """Send only the fixture clock command used before the APK state read."""
        if self._uses_wifi_protocol():
            packet = protocol.wifi_clock_packet()
        elif self._uses_plant_pro_protocol():
            # FluvalConnect treats Plant Pro as a mesh light and writes the
            # raw 0xCD + local date/time frame to its FFF2 SPP endpoint.
            packet = protocol.mesh_clock_packet()
        else:
            packet = protocol.old_clock_packet()
        return await self._async_send_packet(packet, verify=False)

    async def _async_finish_clock_sync(self, state: dict[int, object]) -> bool:
        """Apply the APK's FACEBD timezone follow-up and record completion."""
        if self._uses_wifi_protocol() and protocol.WIFI_TZ_OFFSET_KEY in state:
            if not await self._async_send_packet(protocol.wifi_timezone_packet(), verify=False):
                self._set_diagnostic_error("clock_sync_failed", "Unable to sync lamp timezone")
                return False

        self._clock_synced = True
        self._clock_sync_started = False
        self.diagnostics.update(
            {
                "status": "clock_synced",
                "clock_synced_at": datetime.now(UTC).isoformat(),
                "last_error": None,
            }
        )
        for handler in self.updates_connect:
            handler()
        return True

    def _uses_plant_pro_protocol(self) -> bool:
        """Return true for the live Plant Pro 4.0 SPP-over-BLE profile."""
        return bool(self.client is not None and getattr(self.client, "plant_pro_spp", False) is True)

    def _uses_wifi_protocol(self) -> bool:
        """Prefer the live GATT profile over advertisement heuristics."""
        if self.client is not None and getattr(self.client, "command_write_uuid", None):
            if self._uses_plant_pro_protocol():
                self.facebd = False
                return False
            if getattr(self.client, "wifi_facebd", False):
                self.facebd = True
                return True
            write_uuid = self.client.command_write_uuid.lower()
            if write_uuid.startswith("facebd"):
                self.facebd = True
                return True
            if write_uuid.startswith(("00001001", "0000fff2")):
                self.facebd = False
                return False

        return self.facebd

    def _native_mode_packet(self, mode: str) -> bytes:
        """Build the mode command for the active fixture protocol."""
        mode_code = MODE_TO_CODE[mode]
        if self._uses_wifi_protocol():
            return protocol.wifi_mode_packet(mode_code)
        if self._uses_plant_pro_protocol():
            return protocol.spp_mode_packet(mode_code)
        return protocol.old_mode_packet(mode_code)

    async def _async_prepare_command(self) -> bool:
        """Resolve the BLE device and connect far enough to know the protocol."""
        if not await self._async_ensure_client() or self.client is None:
            self._set_diagnostic_error("device_not_found", "BLE device is not available")
            return False
        client = self.client
        ok = await client.ensure_connected()
        if not ok:
            self._set_diagnostic_error(
                "connect_failed",
                client.last_error or "Unable to connect to BLE device",
            )
        return ok

    async def _async_send_packet(self, packet: bytes, *, verify: bool = True) -> bool:
        """Send one already-built command packet to the controller."""
        if not await self._async_ensure_client() or self.client is None:
            _LOGGER.warning("Cannot send Fluval state before BLE device is available")
            return False
        client = self.client

        _LOGGER.debug(
            "Sending Fluval packet via %s (facebd=%s raw=%s): %s",
            client.command_write_uuid,
            self.facebd,
            client.raw_facebd,
            packet.hex(),
        )
        expected_state = self._expected_state_for_packet(packet)
        if not await client.send_now(packet, expected_state=expected_state, verify=verify):
            self._set_diagnostic_error(
                "write_failed",
                client.last_error or "BLE write failed",
            )
            return False

        self.diagnostics.update(
            {
                "status": ("last_write_verified" if client.last_write_verified else "last_write_unverified"),
                "last_write_at": datetime.now(UTC).isoformat(),
                "last_write_packet": packet.hex(),
                "last_write_targets": list(client.last_write_targets),
                "last_write_verified": client.last_write_verified,
                "connection_profile": client.profile,
                "command_write_uuid": client.command_write_uuid,
                "last_expected_state": dict(client.last_expected_state),
                "last_confirmed_state": dict(client.last_confirmed_state),
                "last_verification_mismatches": dict(client.last_verification_mismatches),
                "last_error": None,
            }
        )

        self.touch_seen(notify=False)
        for handler in self.updates_component:
            handler()
        for handler in self.updates_connect:
            handler()
        return True

    def _expected_state_for_packet(self, packet: bytes) -> dict[int, Any] | None:
        """Return exact supported FACEBD values expected after a command."""
        if self.client is None or not self.client.raw_facebd:
            return None
        try:
            decoded = protocol.decode_cbor_update(packet)
        except ValueError:
            return None
        if not decoded:
            return None
        if self._uses_plant_pro_protocol():
            supported_keys = {
                protocol.SPP_MODE_KEY,
                protocol.SPP_SWITCH_KEY,
                *(protocol.SPP_CHANNEL_KEYS[index] for index, _channel in enumerate(self.numbers())),
                protocol.SPP_AUTO_SUNRISE_KEY,
                protocol.SPP_AUTO_SUNSET_KEY,
                protocol.SPP_AUTO_SLEEP_KEY,
                protocol.SPP_AUTO_DAY_LEVELS_KEY,
                protocol.SPP_AUTO_NIGHT_LEVELS_KEY,
                protocol.SPP_PRO_SCHEDULE_KEY,
                protocol.SPP_EFFECT_KEY,
                protocol.SPP_EFFECT_SCHEDULE_KEY,
            }
        else:
            supported_keys = {
                protocol.WIFI_MODE_KEY,
                protocol.WIFI_SWITCH_KEY,
                protocol.WIFI_DST_KEY,
                *(protocol.WIFI_CHANNEL_KEYS[index] for index, _channel in enumerate(self.numbers())),
            }
        return {key: value for key, value in decoded.items() if key in supported_keys}

    async def async_refresh_state(self) -> bool:
        """Resolve the controller and request its current state."""
        if not await self._async_ensure_client() or self.client is None:
            return False
        client = self.client

        try:
            await client.request_state()
        except (TimeoutError, BleakError) as err:
            _LOGGER.debug("Unable to refresh Fluval state", exc_info=err)
            return False

        return True

    async def async_collect_diagnostics(self) -> dict[str, Any]:
        """Collect a practical snapshot without changing the BLE session."""
        now = datetime.now(UTC)
        report: dict[str, Any] = {
            "status": "ok",
            "checked_at": now.isoformat(),
            "configured_mac": self.address,
            "name": self.name,
            "model": self.model_name,
            "lamp_profile": self.lamp_profile,
            "channel_count": self._resolved_channel_count(),
            "facebd": self.facebd,
            "connected": self.connected,
            "controls_available": self.controls_available,
            "schedule_mode": self.schedule_mode,
            "connection_options": {
                "ping_interval": self._ping_interval,
                "active_time": self._active_time,
            },
            "values": dict(self.values),
            "connection_info": dict(self.conn_info),
            "last_diagnostics": dict(self.diagnostics),
            "active_connection": {
                "source": self.conn_info.get("active_connection_source_address"),
                "source_name": self.conn_info.get("active_connection_source"),
                "source_type": self.conn_info.get("active_connection_source_type"),
                "connected_at": self.conn_info.get("active_connection_connected_at"),
                "gatt_connected": self.connected,
            },
            "latest_advertisement": {
                "source": self.conn_info.get("advertisement_source_address"),
                "source_name": self.conn_info.get("advertisement_source"),
                "source_type": self.conn_info.get("advertisement_source_type"),
                "rssi": self.conn_info.get("rssi"),
                "received_at": self.conn_info.get("rssi_updated_at"),
            },
        }

        if self.client is not None:
            report["gatt"] = {
                "profile": self.client.profile,
                "wifi_facebd": self.client.wifi_facebd,
                "plant_pro_spp": self.client.plant_pro_spp,
                "raw_facebd": self.client.raw_facebd,
                "command_write_uuid": self.client.command_write_uuid,
                "notify_uuids": list(self.client.notify_uuids),
                "last_error": self.client.last_error,
                "last_write_targets": list(self.client.last_write_targets),
                "last_write_verified": self.client.last_write_verified,
            }

        if self.hass is not None:
            service_info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
            if service_info is None:
                service_info = bluetooth.async_last_service_info(self.hass, self.address)
            report["ha_ble_cache"] = service_info is not None
            if service_info is not None:
                report["advertisement_name"] = service_info.device.name
                report["advertisement_rssi"] = service_info.advertisement.rssi
                report["advertisement_service_uuids"] = list(service_info.advertisement.service_uuids)
                report["service_data"] = dict(service_info.advertisement.service_data)
                report["manufacturer_data"] = dict(service_info.advertisement.manufacturer_data)

        return report

    def _channel_values(self) -> list[int]:
        """Return supported channel values in Fluval app order."""
        return [self.values[channel] for channel in self.numbers()]

    def _new_client(self, device: BLEDevice) -> Client:
        """Create a client that refreshes HA's preferred BLE route on reconnect."""
        return Client(
            device,
            self.set_connected,
            self.decode_update_packet,
            ping_interval=self._ping_interval,
            active_time=self._active_time,
            device_provider=self._connectable_ble_device,
            connection_ready_callback=self._record_active_connection_source,
            ready_callback=self._async_on_client_ready,
            state_ready_callback=self._async_on_client_state_ready,
        )

    async def _async_ensure_client(self) -> bool:
        """Create or refresh a client using HA's best connectable BLE route."""
        if not self.address:
            return False

        device = await self._async_find_device()

        if device is None:
            return self.client is not None

        self._update_from_ble_device(device)
        if self.client is None:
            self.client = self._new_client(device)
        else:
            self.client.device = device
        return True

    async def _async_find_device(self) -> BLEDevice | None:
        """Find the configured device through HA, including ESPHome proxies."""
        if self.hass is not None:
            return self._connectable_ble_device()

        for attempt in range(1, BLE_LOOKUP_RETRIES + 1):
            try:
                device = await BleakScanner.find_device_by_address(self.address, timeout=BLE_LOOKUP_TIMEOUT)
            except (TimeoutError, BleakError) as err:
                _LOGGER.debug(
                    "Unable to resolve Fluval device by address, attempt %s",
                    attempt,
                    exc_info=err,
                )
                await asyncio.sleep(attempt)
                continue
            if device is not None:
                return device

        return None

    def _connectable_ble_device(self) -> BLEDevice | None:
        """Ask HA for the best local adapter or ESPHome proxy route."""
        if self.hass is not None:
            device = bluetooth.async_ble_device_from_address(
                self.hass,
                self.address,
                connectable=True,
            )
            if device is not None:
                return device
            service_info = bluetooth.async_last_service_info(
                self.hass,
                self.address,
                connectable=True,
            )
            if service_info is not None:
                return service_info.device
        return self.client.device if self.client is not None else None

    def _set_diagnostic_error(self, status: str, message: str) -> None:
        """Store command failures for downloadable diagnostics."""
        self.diagnostics.update(
            {
                "status": status,
                "last_error": message,
                "last_error_at": datetime.now(UTC).isoformat(),
                "configured_mac": self.address,
                "known_connection_info": dict(self.conn_info),
            }
        )
        for handler in self.updates_connect:
            handler()

    def _update_from_ble_device(self, device: BLEDevice) -> None:
        """Populate metadata from a directly resolved BLEDevice."""
        self.address = device.address
        self.conn_info["mac"] = device.address
        details = device.details if isinstance(device.details, dict) else {}
        props = details.get("props", {})
        self.touch_seen(rssi=props.get("RSSI"), notify=False)

        service_uuids = list(props.get("UUIDs", self.conn_info.get("service_uuids", [])))
        self.conn_info["service_uuids"] = service_uuids
        self.facebd = self._uses_facebd_protocol(
            device.name,
            service_uuids,
            props.get("ServiceData", {}),
            props.get("ManufacturerData", {}),
        )
        self._notify_diagnostics_throttled()

    def _uses_facebd_protocol(
        self,
        name: str | None,
        service_uuids: list[str],
        service_data: dict,
        manufacturer_data: dict,
    ) -> bool:
        """Return true only when advertisements expose the FACEBD protocol.

        Fluval manufacturer data is shared by classic and FACEBD controllers,
        so it is vendor evidence for discovery but never protocol evidence.
        """
        if any(uuid.lower().startswith("facebd") for uuid in service_uuids):
            return True

        if any(str(uuid).lower().startswith("facebd") for uuid in service_data):
            return True

        return False

    def decode_update_packet(self, data: bytes | bytearray) -> bool:
        """Decode the received Fluval packet and sort into values."""
        if data and data[0] == protocol.SPP_STATUS_HEADER:
            try:
                cbor = protocol.decode_cbor_update(data)
            except ValueError as err:
                _LOGGER.debug("Ignoring unsupported Plant Pro CBOR packet", exc_info=err)
                return False
            if cbor is not None:
                return self._decode_plant_pro_update(cbor)
            return False

        is_cbor_map = bool(data and data[0] >> 5 == 5)
        if is_cbor_map:
            try:
                cbor = protocol.decode_cbor_map(data)
            except ValueError as err:
                _LOGGER.debug("Ignoring unsupported Fluval CBOR packet", exc_info=err)
                return False

            if cbor is not None:
                return self._decode_wifi_update(cbor)
            return False

        channel_count = self._resolved_channel_count()
        decoded = protocol.decode_old_state_packet(data, channel_count=channel_count)
        if decoded is None:
            _LOGGER.debug("Ignoring invalid classic Fluval state packet: %s", data.hex())
            return False

        mode = int(decoded["mode"])
        body = decoded["body"]
        self.values["mode"] = MODES[mode]

        if self.values["mode"] == "manual":
            self.values["led_on_off"] = bool(decoded["power"])
            if self.supports_classic_effects():
                self.values["effect"] = self._native_effect_name(int(decoded["effect_id"]))
            presets = [list(preset) for preset in decoded["presets"]]
            self.values["native_manual_presets"] = presets
            self.diagnostics.update(
                {
                    "native_manual_presets": presets,
                    "native_manual_presets_readback_at": datetime.now(UTC).isoformat(),
                }
            )
            # Wire scale is 0-1000 (percent * 10); HA entities use 0-100.
            channels = decoded["channels"]
            self._channel_count_hint = channel_count
            for index, raw in enumerate(channels):
                self.values[f"channel_{index + 1}"] = max(0, min(100, round(raw / 10)))
            for index in range(len(channels), 5):
                self.values[f"channel_{index + 1}"] = 0
        elif self.values["mode"] == "automatic":
            auto_schedule = protocol.decode_old_auto_schedule(body, channel_count=channel_count)
            self._record_native_schedule_readback(protocol_name="classic", auto=auto_schedule)
            self._record_native_effect_schedule_readback(
                protocol_name="classic",
                windows=protocol.decode_old_effect_schedule(body, channel_count=channel_count),
            )
        elif self.values["mode"] == "professional":
            pro_schedule = protocol.decode_old_pro_schedule(body, channel_count=channel_count)
            self._record_native_schedule_readback(protocol_name="classic", professional=pro_schedule)
            self._record_native_effect_schedule_readback(
                protocol_name="classic",
                windows=protocol.decode_old_effect_schedule(body, channel_count=channel_count),
            )

        _LOGGER.debug(
            "led: %s mode: %s channels: %s / %s / %s / %s / %s",
            self.values["led_on_off"],
            self.values["mode"],
            self.values["channel_1"],
            self.values["channel_2"],
            self.values["channel_3"],
            self.values["channel_4"],
            self.values["channel_5"],
        )

        for handler in self.updates_component:
            handler()
        return True

    def _decode_wifi_update(self, data: dict[int, Any]) -> bool:
        """Decode a FACEBD WiFi-over-BLE CBOR state update."""
        updated = False
        if protocol.WIFI_FIRMWARE_VERSION_KEY in data:
            updated = self._store_firmware_version(data[protocol.WIFI_FIRMWARE_VERSION_KEY]) or updated

        if protocol.WIFI_MODE_KEY in data:
            mode = data[protocol.WIFI_MODE_KEY]
            if isinstance(mode, int) and 0 <= mode < len(MODES):
                self.values["mode"] = MODES[mode]
                updated = True

        if protocol.WIFI_SWITCH_KEY in data:
            self.values["led_on_off"] = bool(data[protocol.WIFI_SWITCH_KEY])
            updated = True

        if protocol.WIFI_DST_KEY in data and isinstance(data[protocol.WIFI_DST_KEY], bool):
            self.values["daylight_saving_time"] = data[protocol.WIFI_DST_KEY]
            self.diagnostics["daylight_saving_time"] = data[protocol.WIFI_DST_KEY]
            updated = True

        if (
            self.supports_facebd_effects()
            and protocol.WIFI_MANUAL_KEY in data
            and isinstance(data[protocol.WIFI_MANUAL_KEY], int)
        ):
            effect_code = data[protocol.WIFI_MANUAL_KEY]
            self.values["effect"] = self._native_effect_name(effect_code) if effect_code else None
            updated = True

        present = 0
        for channel, key in zip(NUMBERS, protocol.WIFI_CHANNEL_KEYS, strict=False):
            if key in data and isinstance(data[key], int):
                self.values[channel] = max(0, min(100, int(data[key])))
                present += 1
                updated = True
        if isinstance(data.get(protocol.WIFI_CHANNEL_KEYS[4]), int):
            self._channel_count_hint = 5
        elif present >= 4:
            self._channel_count_hint = 4

        unambiguous_facebd_schedule_keys = (
            protocol.WIFI_AUTO_SUNSET_KEY,
            protocol.WIFI_AUTO_SLEEP_KEY,
            protocol.WIFI_AUTO_DAY_LEVELS_KEY,
            protocol.WIFI_AUTO_NIGHT_LEVELS_KEY,
            protocol.WIFI_PRO_COUNT_KEY,
            protocol.WIFI_PRO_TIMES_KEY,
            protocol.WIFI_PRO_LEVELS_KEY,
            protocol.WIFI_SCHEDULED_EFFECT_KEY,
        )
        has_auto_sunrise = isinstance(data.get(protocol.WIFI_AUTO_SUNRISE_KEY), list)
        if has_auto_sunrise or any(key in data for key in unambiguous_facebd_schedule_keys):
            auto_schedule = protocol.decode_wifi_auto_schedule(data)
            pro_schedule = protocol.decode_wifi_pro_schedule(data, channel_count=self._resolved_channel_count())
            updated = (
                self._record_native_schedule_readback(
                    protocol_name="facebd",
                    auto=auto_schedule,
                    professional=pro_schedule,
                )
                or updated
            )
            updated = (
                self._record_native_effect_schedule_readback(
                    protocol_name="facebd",
                    windows=protocol.decode_wifi_effect_schedule(data),
                )
                or updated
            )

        if updated:
            for handler in self.updates_component:
                handler()
        return updated

    def _decode_plant_pro_update(self, data: dict[int, Any]) -> bool:
        """Decode a Plant Pro 4.0 D2 status map."""
        updated = False
        if protocol.SPP_FIRMWARE_VERSION_KEY in data:
            updated = self._store_firmware_version(data[protocol.SPP_FIRMWARE_VERSION_KEY]) or updated

        if protocol.SPP_MODE_KEY in data:
            mode = data[protocol.SPP_MODE_KEY]
            if isinstance(mode, int) and 0 <= mode < len(MODES):
                self.values["mode"] = MODES[mode]
                updated = True

        if protocol.SPP_SWITCH_KEY in data:
            self.values["led_on_off"] = bool(data[protocol.SPP_SWITCH_KEY])
            updated = True

        present = 0
        for channel, key in zip(NUMBERS, protocol.SPP_CHANNEL_KEYS, strict=False):
            if key in data and isinstance(data[key], int):
                self.values[channel] = max(0, min(100, int(data[key])))
                present += 1
                updated = True
        if present:
            self._channel_count_hint = 5 if present >= 5 else 4

        if protocol.SPP_EFFECT_KEY in data and isinstance(data[protocol.SPP_EFFECT_KEY], int):
            effect_code = data[protocol.SPP_EFFECT_KEY]
            self.values["effect"] = self._native_effect_name(effect_code) if effect_code else None
            updated = True

        auto_schedule = protocol.decode_spp_auto_schedule(data)
        pro_schedule = protocol.decode_spp_pro_schedule(data)
        if self._record_native_schedule_readback(
            protocol_name="plant_pro",
            auto=auto_schedule,
            professional=pro_schedule,
        ):
            updated = True
        if auto_schedule is not None:
            self.diagnostics["plant_pro_auto_schedule"] = auto_schedule
        if pro_schedule is not None:
            self.diagnostics["plant_pro_pro_schedule"] = pro_schedule

        effect_schedule = protocol.decode_spp_effect_schedule(data)
        if self._record_native_effect_schedule_readback(
            protocol_name="plant_pro",
            windows=effect_schedule,
        ):
            updated = True

        if updated:
            for handler in self.updates_component:
                handler()
        return updated

    def _store_firmware_version(self, value: Any) -> bool:
        """Store a locally reported fixture firmware version."""
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False

        firmware_version = str(value)
        changed = firmware_version != self.firmware_version
        self.firmware_version = firmware_version
        self.diagnostics["firmware_version"] = firmware_version
        return changed
