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

from .client import Client
from .discovery import (
    CONF_MODEL,
    FLUVAL_MANUFACTURER_IDS,
    detect_model,
)
from . import protocol

_LOGGER = logging.getLogger(__name__)

NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4", "channel_5"]
SELECTS = ["mode"]
SENSORS = ["rssi", "last_seen"]
DIAGNOSTICS = ["diagnostics"]
AQUASKY_NUMBERS = ["channel_1", "channel_2", "channel_3", "channel_4"]
CHANNEL_NAMES = {
    "channel_1": "Red",
    "channel_2": "Green",
    "channel_3": "Blue",
    "channel_4": "White",
    "channel_5": "Violet",
}
MODES = ["manual", "automatic", "professional"]
MODE_TO_CODE = {mode: index for index, mode in enumerate(MODES)}
DIAGNOSTIC_UPDATE_INTERVAL = 5
BLE_LOOKUP_TIMEOUT = 10
BLE_LOOKUP_RETRIES = 3
PREVIEW_STEP_SECONDS = 2
TRANSITION_STEP_SECONDS = 30
DAY_MINUTES = 24 * 60


class Attribute(TypedDict, total=False):
    """Attributes used by enitites like binary_sensor and number."""

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
        self.address = (config_data.get("mac") or (device.address if device else "")).upper()
        self.client: Client | None = None
        self._ping_interval = ping_interval
        self._active_time = active_time
        self.connected = False
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

    def update_ble(self, device: BLEDevice, advertisment: AdvertisementData):
        """Update BLE metadata."""
        self.address = device.address
        self.conn_info["mac"] = device.address
        self.conn_info["last_seen"] = datetime.now(UTC)
        self.conn_info["rssi"] = advertisment.rssi
        self.conn_info["service_uuids"] = list(advertisment.service_uuids)
        self.conn_info["service_data"] = {key: bytes(value).hex() for key, value in advertisment.service_data.items()}
        self.facebd = self._uses_facebd_protocol(
            device.name,
            advertisment.service_uuids,
            advertisment.service_data,
            advertisment.manufacturer_data,
        )

        if self.client is None:
            self.client = Client(
                device,
                self.set_connected,
                self.decode_update_packet,
                ping_interval=self._ping_interval,
                active_time=self._active_time,
            )
        else:
            self.client.device = device

        self._notify_diagnostics_throttled()

    def set_connected(self, connected: bool):
        """Set the connection status."""
        self.connected = connected

        for handler in self.updates_connect:
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
        if "aquasky" in (self.model or "").lower() or "aquasky" in (self.name or "").lower():
            return list(AQUASKY_NUMBERS)
        return list(NUMBERS)

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
        if attr in CHANNEL_NAMES:
            return CHANNEL_NAMES[attr]
        return attr.replace("_", " ").title()

    def selects(self) -> list[str]:
        """List of select boxes provided by the device."""
        return list(SELECTS)

    def sensors(self) -> list[str]:
        """List of diagnostics sensors provided by the device."""
        return list(SENSORS) + list(DIAGNOSTICS)

    def attribute(self, attr: str) -> Attribute:
        """Provide attributes to the entities like switches, numbers etc."""
        _LOGGER.debug("XXX -> attr: %s", attr)
        if attr == "connection":
            return Attribute(is_on=self.connected, extra=self.conn_info)
        if attr.startswith("channel_"):
            return Attribute(min=0, max=100, step=1, value=self.values[attr])
        if attr == "mode":
            return Attribute(options=MODES, default=self.values[attr])
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
    ) -> bool:
        """Set multiple channel values, optionally ramping over time."""
        channels = self.numbers()
        targets = {channel: max(0, min(100, int(values.get(channel, self.values[channel])))) for channel in channels}
        if not targets:
            return False

        if all(int(self.values.get(channel, -1)) == value for channel, value in targets.items()):
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
            return await self._async_send_channel_state(old_values)

        steps = max(1, int(transition / max(1, step_seconds)))
        start_values = {channel: int(old_values[channel]) for channel in channels}
        for step in range(1, steps + 1):
            ratio = step / steps
            for channel in channels:
                start = start_values[channel]
                end = targets[channel]
                self.values[channel] = round(start + ((end - start) * ratio))
            if not await self._async_send_channel_state(old_values):
                self.values = old_values
                return False
            if step < steps:
                await asyncio.sleep(step_seconds)

        return True

    async def _async_send_channel_state(self, old_values: dict[str, Any]) -> bool:
        """Send the current channel values to the controller."""
        if self._uses_wifi_protocol():
            if any(self._channel_values()) and not self.values["led_on_off"]:
                self.values["led_on_off"] = True
                if not await self._async_send_packet(protocol.wifi_switch_packet(True)):
                    self.values = old_values
                    return False
            ok = await self._async_send_packet(protocol.wifi_all_zone_packet(self._channel_values()))
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

    def _uses_wifi_protocol(self) -> bool:
        """Prefer the live GATT profile over advertisement heuristics."""
        if self.client is not None and self.client.command_write_uuid:
            write_uuid = self.client.command_write_uuid.lower()
            if write_uuid.startswith("facebd80"):
                # WiFi-over-BLE CBOR path used by the working probe script.
                self.facebd = True
                return True
            if write_uuid.startswith("facebd"):
                # FACEBD BLE write path still uses raw (unencrypted) framing.
                self.facebd = True
                return True
            if write_uuid.startswith(("00001001", "0000fff2")):
                self.facebd = False
                return False

        return self.facebd

    async def _async_prepare_command(self) -> bool:
        """Resolve the BLE device and connect far enough to know the protocol."""
        if not await self._async_ensure_client():
            self._set_diagnostic_error("device_not_found", "BLE device is not available")
            return False
        ok = await self.client.ensure_connected()
        if not ok:
            self._set_diagnostic_error(
                "connect_failed",
                self.client.last_error or "Unable to connect to BLE device",
            )
        return ok

    async def _async_send_packet(self, packet: bytes) -> bool:
        """Send one already-built command packet to the controller."""
        if not await self._async_ensure_client():
            _LOGGER.warning("Cannot send Fluval state before BLE device is available")
            return False

        _LOGGER.debug(
            "Sending Fluval packet via %s (facebd=%s raw=%s): %s",
            self.client.command_write_uuid,
            self.facebd,
            self.client.raw_facebd,
            packet.hex(),
        )
        if not await self.client.send_now(packet):
            self._set_diagnostic_error(
                "write_failed",
                self.client.last_error or "BLE write failed",
            )
            return False

        self.diagnostics.update(
            {
                "status": "last_write_ok",
                "last_write_at": datetime.now(UTC).isoformat(),
                "last_write_packet": packet.hex(),
                "last_write_targets": list(self.client.last_write_targets),
                "last_error": None,
            }
        )

        for handler in self.updates_component:
            handler()
        for handler in self.updates_connect:
            handler()
        return True

    async def async_refresh_state(self) -> bool:
        """Resolve the controller and request its current state."""
        if not await self._async_ensure_client():
            return False

        try:
            await self.client.request_state()
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
        if self.address:
            try:
                direct_device = await BleakScanner.find_device_by_address(self.address, timeout=BLE_LOOKUP_TIMEOUT)
            except (TimeoutError, BleakError) as err:
                report["direct_scan_error"] = f"{type(err).__name__}: {err}"

        report["direct_scan_found"] = direct_device is not None
        if direct_device is not None:
            report["direct_scan_device"] = self._ble_device_report(direct_device)
            self._update_from_ble_device(direct_device)
            if self.client is None:
                self.client = Client(
                    direct_device,
                    self.set_connected,
                    self.decode_update_packet,
                    ping_interval=self._ping_interval,
                    active_time=self._active_time,
                )

        report["refresh_state_attempted"] = False
        report["refresh_state_ok"] = False
        if direct_device is not None or self.client is not None:
            report["refresh_state_attempted"] = True
            report["refresh_state_ok"] = await self.async_refresh_state()

        report["status"] = "ok" if report.get("direct_scan_found") else "not_found"
        report["updated_connection_info"] = dict(self.conn_info)
        self.diagnostics = report

        for handler in self.updates_connect:
            handler()

        return report

    def _channel_values(self) -> list[int]:
        """Return the current channel values in Fluval app order."""
        return [self.values[channel] for channel in NUMBERS]

    async def _async_ensure_client(self) -> bool:
        """Create a BLE client from the configured MAC when HA has not populated one."""
        if self.client is not None:
            return True

        if not self.address:
            return False

        device = await self._async_find_device()

        if device is None:
            return False

        self._update_from_ble_device(device)
        self.client = Client(
            device,
            self.set_connected,
            self.decode_update_packet,
            ping_interval=self._ping_interval,
            active_time=self._active_time,
        )
        return True

    async def _async_find_device(self) -> BLEDevice | None:
        """Find the configured BLE device using HA cache first, then active scan."""
        if self.hass is not None:
            service_info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
            if service_info is None:
                service_info = bluetooth.async_last_service_info(self.hass, self.address)
            if service_info is not None:
                self.update_ble(service_info.device, service_info.advertisement)
                return service_info.device

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
        """Return true when advertisements match the newer FACEBD controllers."""
        if any(uuid.lower().startswith("facebd") for uuid in service_uuids):
            return True

        if any(str(uuid).lower().startswith("facebd") for uuid in service_data):
            return True

        manufacturer_ids = {int(key) for key in manufacturer_data}
        return bool(FLUVAL_MANUFACTURER_IDS.intersection(manufacturer_ids))

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

    def decode_update_packet(self, data: bytearray):
        """Decode the received Fluval packet and sort into values."""
        is_cbor_map = bool(data and data[0] >> 5 == 5)
        if is_cbor_map:
            try:
                cbor = protocol.decode_cbor_map(data)
            except ValueError as err:
                _LOGGER.debug("Ignoring unsupported Fluval CBOR packet", exc_info=err)
                return

            if cbor is not None:
                self._decode_wifi_update(cbor)
            return

        if len(data) < 13:
            _LOGGER.debug("Ignoring short Fluval update packet: %s", data.hex())
            return
        if data[0] != 0x68:
            _LOGGER.debug("Ignoring non-state Fluval packet: %s", data.hex())
            return

        if data[2] == 0x00:
            self.values["mode"] = MODES[0]
        elif data[2] == 0x01:
            self.values["mode"] = MODES[1]
        elif data[2] == 0x02:
            self.values["mode"] = MODES[2]

        self.values["led_on_off"] = data[3] > 0x00

        if self.values["mode"] == "manual":
            self.values["channel_1"] = (data[6] << 8) | (data[5] & 0xFF)
            self.values["channel_2"] = (data[8] << 8) | (data[7] & 0xFF)
            self.values["channel_3"] = (data[10] << 8) | (data[9] & 0xFF)
            self.values["channel_4"] = (data[12] << 8) | (data[11] & 0xFF)
            if len(data) > 14:
                self.values["channel_5"] = (data[14] << 8) | (data[13] & 0xFF)
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

    def _decode_wifi_update(self, data: dict[int, Any]):
        """Decode a FACEBD WiFi-over-BLE CBOR state update."""
        if protocol.WIFI_MODE_KEY in data:
            mode = data[protocol.WIFI_MODE_KEY]
            if isinstance(mode, int) and 0 <= mode < len(MODES):
                self.values["mode"] = MODES[mode]

        if protocol.WIFI_SWITCH_KEY in data:
            self.values["led_on_off"] = bool(data[protocol.WIFI_SWITCH_KEY])

        for channel, key in zip(NUMBERS, protocol.WIFI_CHANNEL_KEYS, strict=False):
            if key in data and isinstance(data[key], int):
                self.values[channel] = max(0, min(100, int(data[key])))

        for handler in self.updates_component:
            handler()
