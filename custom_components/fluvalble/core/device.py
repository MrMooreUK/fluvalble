"""A single Fluval BLE connected LED device."""

from collections.abc import Callable
import asyncio
import contextlib
from datetime import UTC, datetime
import logging
from time import monotonic
from typing import Any, TypedDict

from bleak import AdvertisementData, BLEDevice, BleakError, BleakScanner
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from . import (
    CONF_LAMP_PROFILE,
    DEFAULT_LAMP_PROFILE,
    LAMP_PROFILE_AQUASKY,
    LAMP_PROFILE_AQUASKY3,
    LAMP_PROFILE_AUTO,
    LAMP_PROFILE_PLANT,
)
from .client import Client
from .discovery import (
    CONF_MODEL,
    detect_model,
)
from . import protocol

_LOGGER = logging.getLogger(__name__)

NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4", "channel_5"]
SELECTS = ["mode", "schedule_mode"]
SENSORS = ["rssi", "last_seen"]
DIAGNOSTICS = ["diagnostics"]
AQUASKY_NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4"]
CHANNEL_NAMES_AQUASKY = {
    "channel_1": "Red",
    "channel_2": "Green",
    "channel_3": "Blue",
    "channel_4": "White",
    "channel_5": "Violet",
}
CHANNEL_NAMES_PLANT = {
    "channel_1": "Rose",
    "channel_2": "Blue",
    "channel_3": "Cold White",
    "channel_4": "Pure White",
    "channel_5": "Warm White",
}
# Back-compat alias used by tests / schedule helpers
CHANNEL_NAMES = CHANNEL_NAMES_AQUASKY
MODES = ["manual", "automatic", "professional"]
MODE_TO_CODE = {mode: index for index, mode in enumerate(MODES)}
SCHEDULE_MODES = ["manual", "auto"]
DIAGNOSTIC_UPDATE_INTERVAL = 5
BLE_LOOKUP_TIMEOUT = 10
BLE_LOOKUP_RETRIES = 3
PREVIEW_STEP_SECONDS = 2
TRANSITION_STEP_SECONDS = 30
DAY_MINUTES = 24 * 60
CHANNEL_TEST_LEVEL = 100
CHANNEL_TEST_HOLD_SECONDS = 2


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
        hass: HomeAssistant | None = None,
        config_data: dict[str, Any] | None = None,
        ping_interval: int = 10,
        active_time: int = 120,
    ) -> None:
        """Initialize the device."""
        config_data = config_data or {}
        self.hass = hass
        self.name = name or (device.name if device else None) or "Fluval"
        self.model = config_data.get(CONF_MODEL) or detect_model(
            (device.name if device else None) or name, advertisement
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
        self.channel_test_active = False
        self.conn_info = {
            "mac": self.address,
            "model": self.model,
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
        self.diagnostics: dict[str, Any] = {
            "status": "not_run",
            "configured_mac": self.address,
        }
        self.preview_task: asyncio.Task | None = None
        self.preview_restore_values: dict[str, int] | None = None
        self._clock_synced = False
        self._clock_sync_lock = asyncio.Lock()

        if device and advertisement:
            self.update_ble(device, advertisement)

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

    def update_ble(self, device: BLEDevice, advertisement: AdvertisementData):
        """Update BLE metadata."""
        self.address = device.address
        self.conn_info["mac"] = device.address
        self.conn_info["last_seen"] = datetime.now(UTC)
        self.conn_info["rssi"] = advertisement.rssi
        self.conn_info["service_uuids"] = list(advertisement.service_uuids)
        self.conn_info["service_data"] = {key: bytes(value).hex() for key, value in advertisement.service_data.items()}
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

    def set_connected(self, connected: bool):
        """Set the connection status."""
        self.connected = connected
        if not connected:
            # Allow clock sync again on the next successful connect (#8).
            self._clock_synced = False

        for handler in self.updates_connect:
            handler()
        for handler in self.updates_component:
            handler()

    def _notify_diagnostics_throttled(self):
        """Notify diagnostic entities at most once per interval."""
        now = monotonic()
        if now - self._last_diagnostic_update < DIAGNOSTIC_UPDATE_INTERVAL:
            return

        self._last_diagnostic_update = now
        for handler in self.updates_connect:
            handler()

    def numbers(self) -> list[str]:
        """List of numbers provided by the device."""
        if self._resolved_channel_count() == 4:
            return list(AQUASKY_NUMBERS)
        return list(NUMBERS)

    def _resolved_channel_count(self) -> int:
        """Return 4 or 5 channels from profile, packet hint, or name heuristics."""
        profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
        if profile == LAMP_PROFILE_AQUASKY:
            return 4
        if profile in (LAMP_PROFILE_PLANT, LAMP_PROFILE_AQUASKY3):
            return 5
        if self._channel_count_hint in (4, 5):
            return self._channel_count_hint
        if self.facebd or any(
            str(uuid).lower().startswith("0000fff0") for uuid in self.conn_info.get("service_uuids", [])
        ):
            return 5

        model_l = (self.model or "").lower()
        name_l = (self.name or "").lower()
        combined = f"{model_l} {name_l}"

        if any(token in combined for token in ("plant", "marine", "reef")):
            return 5
        # AquaSky 3.x / FACEBD-era names are 5-channel; only classic 2.0 is 4.
        if "aquasky" in combined:
            if any(token in combined for token in ("3.0", "3_", "aquasky3", "3.0 bluetooth")):
                return 5
            if any(token in combined for token in ("2.0", "2_", "aquasky2")):
                return 4
            # Ambiguous "AquaSky" without version -> 4 (classic default).
            return 4
        return 5

    def _channel_labels(self) -> dict[str, str]:
        """Return channel labels for the active lamp profile."""
        profile = (self.lamp_profile or LAMP_PROFILE_AUTO).lower()
        if profile == LAMP_PROFILE_PLANT:
            return CHANNEL_NAMES_PLANT
        if profile in (LAMP_PROFILE_AQUASKY, LAMP_PROFILE_AQUASKY3):
            return CHANNEL_NAMES_AQUASKY
        model_l = (self.model or "").lower()
        name_l = (self.name or "").lower()
        if "plant" in model_l or "plant" in name_l or "marine" in model_l or "reef" in model_l:
            return CHANNEL_NAMES_PLANT
        return CHANNEL_NAMES_AQUASKY

    def master_brightness(self) -> int:
        """Overall brightness as the brightest supported channel."""
        chans = self.numbers()
        return max((self.values.get(ch, 0) for ch in chans), default=0)

    async def async_set_master_brightness(self, level: int) -> bool:
        """Scale all supported channels to level, preserving ratios."""
        level = min(100, max(0, round(level / 10) if level > 100 else int(level)))
        chans = self.numbers()
        old_values = dict(self.values)
        current_max = max((self.values.get(ch, 0) for ch in chans), default=0)
        if current_max <= 0:
            for ch in chans:
                self.values[ch] = level
        else:
            factor = level / current_max
            for ch in chans:
                self.values[ch] = min(100, max(0, round(self.values.get(ch, 0) * factor)))

        if not await self.async_set_value(chans[0], self.values[chans[0]]):
            self.values = old_values
            return False
        return True

    def entity_name(self, attr: str) -> str:
        """Return a user-facing entity suffix for this device attribute."""
        labels = self._channel_labels()
        if attr in labels:
            return labels[attr]
        if attr == "test_led_channels":
            return "Test LED Channels"
        return attr.replace("_", " ").title()

    def selects(self) -> list[str]:
        """List of select boxes provided by the device."""
        return list(SELECTS)

    def sensors(self) -> list[str]:
        """List of diagnostics sensors provided by the device."""
        return list(SENSORS) + list(DIAGNOSTICS)

    def attribute(self, attr: str) -> Attribute:
        """Provide attributes to the entities like switches, numbers etc."""
        if attr == "connection":
            return Attribute(is_on=self.connected, extra=self.conn_info)
        if attr.startswith("channel_"):
            return Attribute(min=0, max=100, step=1, value=self.values[attr])
        if attr == "mode":
            return Attribute(options=MODES, default=self.values[attr])
        if attr == "schedule_mode":
            return Attribute(options=SCHEDULE_MODES, default=self.schedule_mode)
        if attr == "led_on_off":
            return Attribute(is_on=self.values[attr])
        if attr == "rssi":
            return Attribute(
                value=self.conn_info.get("rssi"),
                native_unit_of_measurement="dBm",
            )
        if attr == "last_seen":
            return Attribute(value=self.conn_info.get("last_seen"))
        if attr == "diagnostics":
            return Attribute(
                value=self.diagnostics.get("status"),
                extra=self.diagnostics,
            )
        return Attribute()

    def register_update(self, attr: str, handler: Callable):
        """Register handlers for updates."""
        if attr in ("connection", "rssi", "last_seen"):
            self.updates_connect.append(handler)
        elif attr in DIAGNOSTICS:
            self.updates_connect.append(handler)
        else:
            self.updates_component.append(handler)

    def deregister_update(self, attr: str, handler: Callable):
        """Remove a previously registered update handler."""
        target = (
            self.updates_connect
            if attr in ("connection", "rssi", "last_seen", *DIAGNOSTICS)
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
        targets = {channel: max(0, min(100, int(values.get(channel, self.values[channel])))) for channel in channels}
        if not targets:
            return False

        if not force and all(int(self.values.get(channel, -1)) == value for channel, value in targets.items()):
            _LOGGER.debug("Skipping Fluval channel write because targets are unchanged: %s", targets)
            return True

        old_values = dict(self.values)
        if not await self._async_prepare_command():
            _LOGGER.warning("Cannot set Fluval channel before BLE device is available")
            self.values = old_values
            return False

        if self.values.get("mode") != "manual":
            if self._uses_wifi_protocol():
                ok = await self._async_send_packet(protocol.wifi_mode_packet(MODE_TO_CODE["manual"]))
            else:
                ok = await self._async_send_packet(protocol.old_mode_packet(MODE_TO_CODE["manual"]))
            if not ok:
                self.values = old_values
                return False
            self.values["mode"] = "manual"

        if transition <= 0:
            for channel, value in targets.items():
                self.values[channel] = value
            return await self._async_send_channel_state(
                old_values,
                force_power=force,
            )

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
            ):
                self.values = old_values
                return False
            if step < steps:
                await asyncio.sleep(step_seconds)

        return True

    async def _async_send_channel_state(
        self,
        old_values: dict[str, Any],
        *,
        force_power: bool = False,
    ) -> bool:
        """Send the current channel values to the controller."""
        if self._uses_wifi_protocol():
            any_channel_on = any(self._channel_values())
            if any_channel_on and (force_power or not self.values["led_on_off"]):
                self.values["led_on_off"] = True
                if not await self._async_send_packet(protocol.wifi_switch_packet(True)):
                    self.values = old_values
                    return False
            ok = await self._async_send_packet(protocol.wifi_all_zone_packet(self._channel_values()))
            if ok and not any_channel_on and (force_power or self.values["led_on_off"]):
                ok = await self._async_send_packet(protocol.wifi_switch_packet(False))
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
        self.preview_task = asyncio.create_task(self._async_preview_schedule(points, duration, step_seconds))
        return True

    async def async_stop_preview(self) -> None:
        """Stop any running physical schedule preview."""
        if self.preview_task and not self.preview_task.done():
            self.preview_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.preview_task
        self.preview_task = None
        if self.preview_restore_values:
            restore_values = self.preview_restore_values
            self.preview_restore_values = None
            await self.async_set_channels(restore_values)

    async def async_test_led_channels(self) -> bool:
        """Test power and each supported channel, then restore prior state."""
        if self.channel_test_active:
            return False
        self.channel_test_active = True
        await self.async_stop_preview()
        original_values = {channel: int(self.values.get(channel, 0)) for channel in self.numbers()}
        original_power = bool(self.values.get("led_on_off"))
        results: list[dict[str, Any]] = []
        error = None
        self.diagnostics.update(
            {
                "status": "channel_test_running",
                "channel_test_started_at": datetime.now(UTC).isoformat(),
                "channel_test_results": results,
            }
        )

        try:
            power_ok = await self.async_set_switch("led_on_off", True)
            results.append(self._channel_test_result("Power", True, power_ok))
            for channel in self.numbers() if power_ok else []:
                targets = {candidate: 0 for candidate in self.numbers()}
                targets[channel] = CHANNEL_TEST_LEVEL
                write_ok = await self.async_set_channels(targets, force=True)
                results.append(
                    self._channel_test_result(
                        self.entity_name(channel),
                        CHANNEL_TEST_LEVEL,
                        write_ok,
                    )
                )
                self.diagnostics.update(
                    {
                        "channel_test_current": self.entity_name(channel),
                        "channel_test_results": list(results),
                    }
                )
                for handler in self.updates_connect:
                    handler()
                if not write_ok:
                    break
                await asyncio.sleep(CHANNEL_TEST_HOLD_SECONDS)
        except Exception as err:  # noqa: BLE001
            error = f"{type(err).__name__}: {err}"
            _LOGGER.exception("Fluval LED channel test failed")
        finally:
            try:
                restore_ok = await self.async_set_channels(
                    original_values,
                    force=True,
                )
                if not original_power:
                    restore_ok = await self.async_set_switch("led_on_off", False) and restore_ok
            except Exception as err:  # noqa: BLE001
                restore_ok = False
                restore_error = f"{type(err).__name__}: {err}"
                error = f"{error}; restore failed: {restore_error}" if error else f"restore failed: {restore_error}"
                _LOGGER.exception("Unable to restore Fluval state after channel test")
            self.channel_test_active = False

        expected_count = len(self.numbers()) + 1
        passed = (
            len(results) == expected_count
            and all(item["write_ok"] and item["verified"] for item in results)
            and error is None
        )
        writes_ok = bool(results) and all(item["write_ok"] for item in results)
        self.diagnostics.update(
            {
                "status": (
                    "channel_test_passed"
                    if passed
                    else ("channel_test_unverified" if writes_ok else "channel_test_failed")
                ),
                "channel_test_completed_at": datetime.now(UTC).isoformat(),
                "channel_test_results": list(results),
                "channel_test_restore_ok": restore_ok,
                "channel_test_error": error,
            }
        )
        for handler in self.updates_connect:
            handler()
        return passed

    def _channel_test_result(
        self,
        channel: str,
        requested: bool | int,
        write_ok: bool,
    ) -> dict[str, Any]:
        """Build a copyable result for one channel-test step."""
        return {
            "channel": channel,
            "requested": requested,
            "write_ok": write_ok,
            "verified": bool(write_ok and self.client and self.client.last_write_verified),
            "confirmed_state": (dict(self.client.last_confirmed_state) if self.client is not None else {}),
            "mismatches": (dict(self.client.last_verification_mismatches) if self.client is not None else {}),
        }

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
        else:
            ok = await self._async_send_packet(protocol.old_switch_packet(value))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        return ok

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
        else:
            ok = await self._async_send_packet(protocol.old_mode_packet(MODE_TO_CODE[option]))

        if not ok:
            self.values = old_values
            for handler in self.updates_component:
                handler()
        return ok

    async def _async_on_client_ready(self) -> None:
        """Run post-connect housekeeping after the BLE link is established."""
        ok = await self.async_sync_clock(force=False)
        if not ok:
            _LOGGER.warning("Fluval clock sync failed after connect for %s", self.address)

    async def async_sync_clock(self, *, force: bool = False) -> bool:
        """Sync the lamp RTC from the Home Assistant host clock (#8)."""
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

            if self._uses_wifi_protocol():
                packets = [protocol.wifi_timezone_packet(), protocol.wifi_clock_packet()]
            elif self._uses_mesh_protocol():
                packets = [protocol.mesh_clock_packet()]
            else:
                packets = [protocol.old_clock_packet()]

            for packet in packets:
                if not await self._async_send_packet(packet):
                    self._set_diagnostic_error("clock_sync_failed", "Unable to sync lamp clock")
                    return False

            self._clock_synced = True
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

    def _uses_mesh_protocol(self) -> bool:
        """Return true when advertisements expose the mesh fff0 service."""
        return any(str(uuid).lower().startswith("0000fff0") for uuid in self.conn_info.get("service_uuids", []))

    def _uses_wifi_protocol(self) -> bool:
        """Prefer the live GATT profile over advertisement heuristics."""
        if self.client is not None and self.client.command_write_uuid:
            if self.client.wifi_facebd:
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

    async def _async_send_packet(self, packet: bytes) -> bool:
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
        if not await client.send_now(packet, expected_state=expected_state):
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
            decoded = protocol.decode_cbor_map(packet)
        except ValueError:
            return None
        if not decoded:
            return None
        supported_keys = {
            protocol.WIFI_MODE_KEY,
            protocol.WIFI_SWITCH_KEY,
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
        """Collect practical BLE diagnostics for this configured device."""
        if self.client is not None:
            await self.client.disconnect()
        now = datetime.now(UTC)
        report: dict[str, Any] = {
            "status": "running",
            "checked_at": now.isoformat(),
            "configured_mac": self.address,
            "name": self.name,
            "known_connection_info": dict(self.conn_info),
            "facebd": self.facebd,
            "connected": self.connected,
            "client_created": self.client is not None,
        }

        if self.hass is not None and self.address:
            service_info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
            if service_info is None:
                service_info = bluetooth.async_last_service_info(self.hass, self.address)

            report["ha_last_service_info_found"] = service_info is not None
            if service_info is not None:
                report["ha_last_service_info"] = self._service_info_report(service_info)
                self.update_ble(service_info.device, service_info.advertisement)

        direct_device = None
        if self.hass is not None:
            direct_device = self._connectable_ble_device()
            report["ha_connectable_route_found"] = direct_device is not None
            if direct_device is not None:
                report["selected_ble_device"] = self._ble_device_report(direct_device)
        elif self.address:
            try:
                direct_device = await BleakScanner.find_device_by_address(self.address, timeout=BLE_LOOKUP_TIMEOUT)
            except (TimeoutError, BleakError) as err:
                report["direct_scan_error"] = f"{type(err).__name__}: {err}"

        report["direct_scan_found"] = direct_device is not None
        if direct_device is not None:
            report["direct_scan_device"] = self._ble_device_report(direct_device)
            self._update_from_ble_device(direct_device)
            if self.client is None:
                self.client = self._new_client(direct_device)

        report["refresh_state_attempted"] = False
        report["refresh_state_ok"] = False
        if direct_device is not None or self.client is not None:
            report["refresh_state_attempted"] = True
            report["refresh_state_ok"] = await self.async_refresh_state()

        report["status"] = "ok" if direct_device is not None else "not_found"
        report["updated_connection_info"] = dict(self.conn_info)
        self.diagnostics = report

        for handler in self.updates_connect:
            handler()

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
            ready_callback=self._async_on_client_ready,
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
        """Store command failures in the diagnostics sensor for quick copying."""
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
        self.conn_info["last_seen"] = datetime.now(UTC)

        details = device.details if isinstance(device.details, dict) else {}
        props = details.get("props", {})
        self.conn_info["rssi"] = props.get("RSSI", self.conn_info.get("rssi"))

        service_uuids = list(props.get("UUIDs", self.conn_info.get("service_uuids", [])))
        self.conn_info["service_uuids"] = service_uuids
        self.facebd = self._uses_facebd_protocol(
            device.name,
            service_uuids,
            props.get("ServiceData", {}),
            props.get("ManufacturerData", {}),
        )
        self._notify_diagnostics_throttled()

    def _ble_device_report(self, device: BLEDevice) -> dict[str, Any]:
        """Return a copyable, JSON-friendly BLEDevice summary."""
        details = device.details if isinstance(device.details, dict) else {}
        props = details.get("props", {})
        return {
            "name": device.name,
            "address": device.address,
            "source": details.get("source"),
            "rssi": props.get("RSSI"),
            "uuids": list(props.get("UUIDs", [])),
            "service_data_keys": list(props.get("ServiceData", {})),
            "manufacturer_data_keys": [str(key) for key in props.get("ManufacturerData", {})],
            "path": details.get("path"),
        }

    def _service_info_report(self, service_info) -> dict[str, Any]:
        """Return a compact HA Bluetooth service info summary."""
        advertisement = service_info.advertisement
        return {
            "name": service_info.name,
            "address": service_info.address,
            "rssi": advertisement.rssi,
            "service_uuids": list(advertisement.service_uuids),
            "service_data": {key: bytes(value).hex() for key, value in advertisement.service_data.items()},
            "manufacturer_data": {
                str(key): bytes(value).hex() for key, value in advertisement.manufacturer_data.items()
            },
            "connectable": getattr(service_info, "connectable", None),
            "source": getattr(service_info, "source", None),
        }

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

    def _build_state_packet(self) -> bytearray:
        """Build a command packet from the current entity state.

        The first bytes mirror the status packet shape decoded below. The Fluval
        protocol is not published, so keeping this in one method makes future
        packet corrections small and easy to test against real hardware.
        """
        packet = bytearray(
            [
                0x68,
                0x18,
                MODE_TO_CODE.get(self.values["mode"], 0),
                0x01 if self.values["led_on_off"] else 0x00,
                0x00,
            ]
        )

        for channel in NUMBERS:
            value = max(0, min(1000, int(self.values[channel])))
            packet.extend([value & 0xFF, value >> 8])

        return packet

    def decode_update_packet(self, data: bytes | bytearray) -> bool:
        """Decode the received Fluval packet and sort into values."""
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

        if len(data) < 13:
            _LOGGER.debug("Ignoring short Fluval update packet: %s", data.hex())
            return False
        if data[0] != 0x68:
            _LOGGER.debug("Ignoring non-state Fluval packet: %s", data.hex())
            return False

        if data[2] == 0x00:
            self.values["mode"] = MODES[0]
        elif data[2] == 0x01:
            self.values["mode"] = MODES[1]
        elif data[2] == 0x02:
            self.values["mode"] = MODES[2]

        self.values["led_on_off"] = data[3] > 0x00

        if self.values["mode"] == "manual":
            # Wire scale is 0-1000 (percent * 10); HA entities use 0-100.
            channels = [
                ((data[6] << 8) | (data[5] & 0xFF)),
                ((data[8] << 8) | (data[7] & 0xFF)),
                ((data[10] << 8) | (data[9] & 0xFF)),
                ((data[12] << 8) | (data[11] & 0xFF)),
            ]
            if len(data) > 14:
                channels.append((data[14] << 8) | (data[13] & 0xFF))
            self._channel_count_hint = 5 if len(channels) >= 5 else 4
            for index, raw in enumerate(channels):
                self.values[f"channel_{index + 1}"] = max(0, min(100, round(raw / 10)))
        else:
            for channel in NUMBERS:
                self.values[channel] = 0

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
        if protocol.WIFI_MODE_KEY in data:
            mode = data[protocol.WIFI_MODE_KEY]
            if isinstance(mode, int) and 0 <= mode < len(MODES):
                self.values["mode"] = MODES[mode]
                updated = True

        if protocol.WIFI_SWITCH_KEY in data:
            self.values["led_on_off"] = bool(data[protocol.WIFI_SWITCH_KEY])
            updated = True

        present = 0
        for channel, key in zip(NUMBERS, protocol.WIFI_CHANNEL_KEYS, strict=False):
            if key in data and isinstance(data[key], int):
                self.values[channel] = max(0, min(100, int(data[key])))
                present += 1
                updated = True
        if present:
            self._channel_count_hint = 5 if present >= 5 else 4

        if updated:
            for handler in self.updates_component:
                handler()
        return updated
