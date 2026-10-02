"""Packet builders for Fluval light protocols."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from . import encryption

MAX_CBOR_CONTAINER_ITEMS = 64
MAX_CBOR_BYTE_STRING_LENGTH = 4096
MAX_CBOR_NESTING_DEPTH = 8

WIFI_DST_KEY = 99
WIFI_FIRMWARE_VERSION_KEY = 100
WIFI_TZ_OFFSET_KEY = 101
WIFI_CLOCK_MS_KEY = 102
FIND_KEY = 52
WIFI_MODE_KEY = 103
WIFI_SWITCH_KEY = 104
WIFI_MANUAL_KEY = 109
WIFI_AUTO_SUNRISE_KEY = 114
# FluvalConnect reuses key 114 by packet context: it is the fifth manual
# channel as an integer, and the Auto-schedule sunrise window as a minute pair.
WIFI_CHANNEL_KEYS = (110, 111, 112, 113, WIFI_AUTO_SUNRISE_KEY)
WIFI_AUTO_SUNSET_KEY = 115
WIFI_AUTO_SLEEP_KEY = 116
WIFI_AUTO_DAY_LEVELS_KEY = 117
WIFI_AUTO_NIGHT_LEVELS_KEY = 118
WIFI_PRO_COUNT_KEY = 120
WIFI_PRO_TIMES_KEY = 121
WIFI_PRO_LEVELS_KEY = 122
WIFI_SCHEDULED_EFFECT_KEY = 123
WIFI_MIN_PRO_POINTS = 4
WIFI_MAX_PRO_POINTS = 12
WIFI_MAX_EFFECT_WINDOWS = 7

SPP_COMMAND_HEADER = 0xD1
SPP_STATUS_HEADER = 0xD2
SPP_READ_PARAMS_PACKET = bytes((0xD0, 0xFF))
SPP_FIRMWARE_VERSION_KEY = 0
SPP_MODE_KEY = 1
SPP_SWITCH_KEY = 2
SPP_CHANNEL_KEYS = (3, 4, 5, 6, 7)
SPP_AUTO_SUNRISE_KEY = 8
SPP_AUTO_SUNSET_KEY = 9
SPP_AUTO_SLEEP_KEY = 10
SPP_AUTO_DAY_LEVELS_KEY = 11
SPP_AUTO_NIGHT_LEVELS_KEY = 12
SPP_PRO_SCHEDULE_KEY = 13
SPP_EFFECT_KEY = 14
SPP_MANUAL_KEY = SPP_EFFECT_KEY
SPP_EFFECT_SCHEDULE_KEY = 15
SPP_MIN_PRO_POINTS = 4
SPP_MAX_PRO_POINTS = 12
SPP_MAX_EFFECT_WINDOWS = 7

OLD_READ_PARAMS = bytes((0x68, 0x05))
OLD_MODE = 0x02
OLD_SWITCH = 0x03
OLD_ALL_ZONE = 0x04
OLD_SAVE_PRESET = 0x06
OLD_AUTO_SCHEDULE = 0x07
OLD_WEATHER_EFFECT = 0x0A
OLD_AUTO_PREVIEW = 0x0B
OLD_AUTO_PREVIEW_STOP = 0x0C
OLD_CLOCK = 0x0E
OLD_FIND = 0x0F
OLD_PRO_SCHEDULE = 0x10
OLD_SCHEDULED_EFFECT = 0x11
OLD_MIN_PRO_POINTS = 4
OLD_MAX_PRO_POINTS = 10
OLD_MAX_EFFECT_WINDOWS = 7

# Mesh / Plant Pro clock opcode recovered from FluvalConnect.
MESH_OPCODE_CLOCK = 0xCD


def wifi_switch_packet(is_on: bool) -> bytes:
    """Build the FACEBD WiFi-over-BLE on/off packet."""
    return cbor_map({WIFI_SWITCH_KEY: is_on})


def wifi_dst_packet(enabled: bool) -> bytes:
    """Build FluvalConnect's FACEBD daylight-saving toggle packet."""
    return cbor_map({WIFI_DST_KEY: enabled})


def wifi_mode_packet(mode: int) -> bytes:
    """Build the FACEBD WiFi-over-BLE mode packet."""
    return cbor_map({WIFI_MODE_KEY: mode})


def wifi_effect_packet(effect_id: int) -> bytes:
    """Build the APK-native FACEBD weather-effect packet.

    FluvalConnect's ``createLightWeatherValue`` writes the selected weather ID
    to CBOR key 109 for its WiFi/FACEBD transport. Static channel writes use
    the same key with value zero to leave the effect.
    """
    if not 0 <= effect_id <= 11:
        raise ValueError("FACEBD Fluval effect ID must be between 0 and 11")
    return cbor_map({WIFI_MANUAL_KEY: effect_id})


def wifi_find_packet() -> bytes:
    """Build the APK-native FACEBD identify command."""
    return cbor_map({FIND_KEY: "find"})


def wifi_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build a FACEBD WiFi-over-BLE all-channel packet."""
    packet = {WIFI_MANUAL_KEY: 0}
    packet.update({key: _clamp_percent(value) for key, value in zip(WIFI_CHANNEL_KEYS, values, strict=False)})
    return cbor_map(packet)


def wifi_single_zone_packet(channel_index: int, value: int) -> bytes:
    """Build the APK FACEBD packet for one manual color channel."""
    if not 0 <= channel_index < len(WIFI_CHANNEL_KEYS):
        raise ValueError("FACEBD Fluval channel index must be between 0 and 4")
    return cbor_map(
        {
            WIFI_CHANNEL_KEYS[channel_index]: _clamp_percent(value),
            WIFI_MANUAL_KEY: 0,
        }
    )


def wifi_clock_packet(now: datetime | None = None) -> bytes:
    """Build FACEBD clock sync (milliseconds since Unix epoch)."""
    moment = now or datetime.now().astimezone()
    millis = int(moment.timestamp() * 1000)
    return cbor_map({WIFI_CLOCK_MS_KEY: millis})


def wifi_timezone_packet(now: datetime | None = None) -> bytes:
    """Build FACEBD timezone offset in minutes from UTC."""
    moment = now or datetime.now().astimezone()
    offset = moment.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset is not None else 0
    return cbor_map({WIFI_TZ_OFFSET_KEY: minutes})


def mesh_clock_packet(now: datetime | None = None) -> bytes:
    """Build mesh/Plant Pro clock sync (0xCD + Y M D W h m s)."""
    return bytes((MESH_OPCODE_CLOCK,)) + _clock_payload(now)


def decode_wifi_auto_schedule(
    data: Mapping[int, Any],
    *,
    channel_count: int = 4,
) -> dict[str, Any] | None:
    """Decode FACEBD native Auto fields into the integration schedule shape."""
    if channel_count not in (4, 5) or not all(
        key in data
        for key in (
            WIFI_AUTO_SUNRISE_KEY,
            WIFI_AUTO_SUNSET_KEY,
            WIFI_AUTO_SLEEP_KEY,
            WIFI_AUTO_DAY_LEVELS_KEY,
            WIFI_AUTO_NIGHT_LEVELS_KEY,
        )
    ):
        return None
    sunrise = _decode_minute_pair(data.get(WIFI_AUTO_SUNRISE_KEY), sunrise=True)
    sunset = _decode_minute_pair(data.get(WIFI_AUTO_SUNSET_KEY), sunrise=False)
    raw_sleep = data.get(WIFI_AUTO_SLEEP_KEY)
    sleep = _decode_minute(raw_sleep)
    day_levels = _decode_levels(data.get(WIFI_AUTO_DAY_LEVELS_KEY), exact=channel_count)
    night_levels = _decode_levels(data.get(WIFI_AUTO_NIGHT_LEVELS_KEY), exact=channel_count)
    if (
        sunrise is None
        or sunset is None
        or (raw_sleep != 0xFFFF and sleep is None)
        or day_levels is None
        or night_levels is None
    ):
        return None
    return {
        "sunrise": sunrise,
        "sunset": sunset,
        "sleep": sleep,
        "day_levels": day_levels,
        "night_levels": night_levels,
    }


def decode_wifi_pro_schedule(data: Mapping[int, Any], *, channel_count: int = 4) -> list[dict[str, Any]] | None:
    """Decode FACEBD count/times/levels fields into normalized Pro points."""
    if channel_count not in (4, 5):
        return None
    count = data.get(WIFI_PRO_COUNT_KEY)
    times = data.get(WIFI_PRO_TIMES_KEY)
    levels = data.get(WIFI_PRO_LEVELS_KEY)
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not isinstance(times, list)
        or not isinstance(levels, bytes)
    ):
        return None
    if (
        not WIFI_MIN_PRO_POINTS <= count <= WIFI_MAX_PRO_POINTS
        or len(times) != count
        or len(levels) != count * channel_count
    ):
        return None
    points: list[dict[str, Any]] = []
    for index, minute in enumerate(times):
        if isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute < 1440:
            return None
        values = levels[index * channel_count : (index + 1) * channel_count]
        if any(value > 100 for value in values):
            return None
        point: dict[str, Any] = {"minute": minute}
        point.update({f"channel_{channel}": value for channel, value in enumerate(values, start=1)})
        points.append(point)
    return points


def decode_wifi_effect_schedule(data: Mapping[int, Any]) -> list[dict[str, Any]] | None:
    """Decode FACEBD key 123 into normalized timed-effect windows."""
    blob = data.get(WIFI_SCHEDULED_EFFECT_KEY)
    if not isinstance(blob, bytes):
        return None
    return _decode_effect_schedule_blob(
        blob,
        maximum=WIFI_MAX_EFFECT_WINDOWS,
        maximum_effect_id=11,
    )


def spp_switch_packet(is_on: bool) -> bytes:
    """Build a current-controller FFF0/SPP power packet."""
    return spp_command({SPP_SWITCH_KEY: is_on})


def spp_mode_packet(mode: int) -> bytes:
    """Build a current-controller FFF0/SPP mode packet."""
    return spp_command({SPP_MODE_KEY: mode})


def spp_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build a current-controller FFF0/SPP all-channel packet."""
    packet = {key: _clamp_percent(value) for key, value in zip(SPP_CHANNEL_KEYS, values, strict=False)}
    packet[SPP_MANUAL_KEY] = 0
    return spp_command(packet)


def spp_single_zone_packet(channel_index: int, value: int) -> bytes:
    """Build the APK Plant Pro/MESH packet for one manual color channel."""
    if not 0 <= channel_index < len(SPP_CHANNEL_KEYS):
        raise ValueError("FFF0/SPP channel index must be between 0 and 4")
    return spp_command(
        {
            SPP_CHANNEL_KEYS[channel_index]: _clamp_percent(value),
            SPP_MANUAL_KEY: 0,
        }
    )


def spp_effect_packet(effect_id: int, *, maximum_effect_id: int = 4) -> bytes:
    """Build a current-controller native-effect packet."""
    if not 0 <= effect_id <= maximum_effect_id:
        raise ValueError(f"FFF0/SPP effect ID must be between 0 and {maximum_effect_id}")
    return spp_command({SPP_EFFECT_KEY: effect_id})


def spp_find_packet() -> bytes:
    """Build the APK-native current-controller identify command."""
    return spp_command({FIND_KEY: "find"})


def spp_command(values: Mapping[int, Any]) -> bytes:
    """Build an unencrypted current-controller FFF0/SPP command frame."""
    return bytes((SPP_COMMAND_HEADER,)) + cbor_map(values)


def old_read_params_packet() -> bytes:
    """Build the old BLE parameter read packet."""
    return old_packet(OLD_READ_PARAMS)


def old_switch_packet(is_on: bool) -> bytes:
    """Build the old BLE on/off packet."""
    return old_packet(bytes((0x68, OLD_SWITCH, 0x01 if is_on else 0x00)))


def decode_old_state_packet(packet: bytes | bytearray, *, channel_count: int) -> dict[str, Any] | None:
    """Validate and decode an APK-native classic ``6805`` state response."""
    if channel_count not in (4, 5) or len(packet) < 5:
        return None
    if bytes(packet[:2]) != OLD_READ_PARAMS or _xor_checksum(packet) != 0:
        return None

    body = bytes(packet[2:-1])
    mode = body[0]
    decoded: dict[str, Any] = {"mode": mode, "body": body}

    if mode == 0:
        if len(body) != channel_count * 6 + 3:
            return None
        preset_offset = 3 + channel_count * 2
        channels = [body[offset] | (body[offset + 1] << 8) for offset in range(3, preset_offset, 2)]
        presets = [
            list(body[preset_offset + slot * channel_count : preset_offset + (slot + 1) * channel_count])
            for slot in range(4)
        ]
        if any(value > 1000 for value in channels) or any(value > 100 for preset in presets for value in preset):
            return None
        decoded.update(
            {
                "power": bool(body[1] & 0x01),
                "effect_id": body[2],
                "channels": channels,
                "presets": presets,
            }
        )
        return decoded

    if mode == 1:
        base_length = channel_count * 2 + 9
        return decoded if len(body) in {base_length, base_length + 3, base_length + 6, base_length + 9} else None

    if mode == 2 and len(body) >= 2:
        base_length = 2 + body[1] * (channel_count + 2)
        return decoded if len(body) in {base_length, base_length + 6} else None

    return None


def old_receive_frame_ready(payload: bytes | bytearray) -> bool:
    """Return whether the APK-style classic receive cache holds a full frame."""
    if not encryption.is_valid_fluval_frame(payload):
        return False
    if len(payload) < 3 or payload[1] != OLD_READ_PARAMS[1]:
        return True
    return any(decode_old_state_packet(payload, channel_count=count) is not None for count in (4, 5))


def decode_old_auto_schedule(body: bytes, *, channel_count: int) -> dict[str, Any] | None:
    """Decode the body of a classic mode-1 ``6805`` response."""
    base_length = channel_count * 2 + 9
    if (
        channel_count not in (4, 5)
        or len(body) not in {base_length, base_length + 3, base_length + 6, base_length + 9}
        or body[0] != 1
    ):
        return None
    offset = 1
    sunrise_start = _checked_minute(body[offset], body[offset + 1])
    sunrise_end = _checked_minute(body[offset + 2], body[offset + 3])
    if sunrise_start is None or sunrise_end is None:
        return None
    offset += 4
    day_levels = list(body[offset : offset + channel_count])
    offset += channel_count
    sunset_start = _checked_minute(body[offset], body[offset + 1])
    sunset_end = _checked_minute(body[offset + 2], body[offset + 3])
    if sunset_start is None or sunset_end is None or any(level > 100 for level in day_levels):
        return None
    offset += 4
    night_levels = list(body[offset : offset + channel_count])
    if any(level > 100 for level in night_levels):
        return None
    offset += channel_count
    sleep = None
    remainder = len(body) - offset
    if remainder in (3, 9) and body[offset]:
        sleep_minute = _checked_minute(body[offset + 1], body[offset + 2])
        if sleep_minute is None:
            return None
        sleep = {"hour": sleep_minute // 60, "minute": sleep_minute % 60}
    sunrise_ramp = (sunrise_end - sunrise_start) % 1440
    sunset_ramp = (sunset_end - sunset_start) % 1440
    if sunrise_ramp > 240 or sunset_ramp > 240:
        return None
    return {
        "sunrise": _ramp_dict(sunrise_start, sunrise_ramp),
        "sunset": _ramp_dict(sunset_end, sunset_ramp),
        "sleep": sleep,
        "day_levels": day_levels,
        "night_levels": night_levels,
    }


def decode_old_pro_schedule(body: bytes, *, channel_count: int) -> list[dict[str, Any]] | None:
    """Decode the body of a classic mode-2 ``6805`` response."""
    if channel_count not in (4, 5) or len(body) < 2 or body[0] != 2:
        return None
    count = body[1]
    stride = channel_count + 2
    schedule_length = 2 + count * stride
    if not OLD_MIN_PRO_POINTS <= count <= OLD_MAX_PRO_POINTS or len(body) not in {
        schedule_length,
        schedule_length + 6,
    }:
        return None
    points: list[dict[str, Any]] = []
    for index in range(count):
        offset = 2 + index * stride
        minute = _checked_minute(body[offset], body[offset + 1])
        levels = body[offset + 2 : offset + stride]
        if minute is None or any(level > 100 for level in levels):
            return None
        point: dict[str, Any] = {"minute": minute}
        point.update({f"channel_{channel}": level for channel, level in enumerate(levels, start=1)})
        points.append(point)
    return points


def decode_old_effect_schedule(body: bytes, *, channel_count: int) -> list[dict[str, Any]] | None:
    """Decode the one classic effect slot embedded in ``6805`` mode state."""
    if channel_count not in (4, 5) or not body:
        return None
    if body[0] == 1:
        base_length = channel_count * 2 + 9
        remainder = len(body) - base_length
        if remainder not in (6, 9):
            return None
    elif body[0] == 2 and len(body) >= 2:
        base_length = 2 + body[1] * (channel_count + 2)
        if len(body) - base_length != 6:
            return None
    else:
        return None
    return _decode_effect_schedule_blob(
        body[-6:],
        maximum=1,
        maximum_effect_id=11,
    )


def old_mode_packet(mode: int) -> bytes:
    """Build the old BLE mode packet."""
    return old_packet(bytes((0x68, OLD_MODE, mode & 0xFF)))


def old_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build the APK-native classic ``6804`` all-channel packet."""
    packet = bytearray((0x68, OLD_ALL_ZONE))
    for value in values:
        scaled = _clamp_percent(value) * 10
        # Despite its name, the APK's integerToHexLittle() only zero-pads the
        # hexadecimal word; hexStringToBytes() then emits the high byte first.
        packet.extend((scaled >> 8, scaled & 0xFF))
    return old_packet(packet)


def old_save_manual_preset_packet(slot_index: int) -> bytes:
    """Save the current classic channel state to APK preset index 0 through 3."""
    if isinstance(slot_index, bool) or not isinstance(slot_index, int) or not 0 <= slot_index <= 3:
        raise ValueError("Classic manual preset index must be between 0 and 3")
    return old_packet(bytes((0x68, OLD_SAVE_PRESET, slot_index)))


def old_weather_effect_packet(effect_id: int) -> bytes:
    """Build the APK-native classic weather-effect packet."""
    if not 1 <= effect_id <= 11:
        raise ValueError("Classic Fluval effect ID must be between 1 and 11")
    return old_packet(bytes((0x68, OLD_WEATHER_EFFECT, effect_id)))


def old_find_packet() -> bytes:
    """Build the APK-native classic identify command (``680F``)."""
    return old_packet(bytes((0x68, OLD_FIND)))


def old_clock_packet(now: datetime | None = None) -> bytes:
    """Build old BLE clock sync (cmd 0x0E: Y M D W h m s)."""
    return old_packet(bytes((0x68, OLD_CLOCK)) + _clock_payload(now))


def old_packet(packet: bytes | bytearray) -> bytes:
    """Append the XOR checksum used by the old light protocol."""
    checksum = 0
    for item in packet:
        checksum ^= item
    return bytes(packet) + bytes((checksum,))


def _xor_checksum(packet: Iterable[int]) -> int:
    """Return the classic protocol XOR across a complete packet."""
    checksum = 0
    for item in packet:
        checksum ^= item
    return checksum


def encrypted_old_packet(packet: bytes | bytearray) -> bytearray:
    """Encode one complete APK classic packet without changing its checksum."""
    return encrypted_old_frames(packet)[0]


def encrypted_old_frames(packet: bytes | bytearray) -> list[bytearray]:
    """Validate, chunk, and encode one already-checksummed classic frame."""
    if not is_valid_old_command_packet(packet):
        raise ValueError("Classic Fluval writes require one complete APK command frame")
    return encryption.encode_message_chunks(packet, key=None)


def is_valid_old_command_packet(packet: bytes | bytearray) -> bool:
    """Validate the framing and shape of every classic command exposed by the APK."""
    if not encryption.is_valid_fluval_frame(packet) or len(packet) < 3:
        return False
    command = packet[1]
    length = len(packet)
    if command in (OLD_READ_PARAMS[1], OLD_AUTO_PREVIEW_STOP, OLD_FIND):
        return length == 3
    if command in (OLD_MODE, OLD_SWITCH, OLD_SAVE_PRESET, OLD_WEATHER_EFFECT):
        return length == 4
    if command in (OLD_ALL_ZONE, OLD_AUTO_PREVIEW):
        return length in (11, 13)
    if command == OLD_CLOCK:
        return length == 10
    if command == OLD_AUTO_SCHEDULE:
        return length in (19, 21, 22, 24)
    if command == OLD_PRO_SCHEDULE and length >= 4:
        point_count = packet[2]
        return OLD_MIN_PRO_POINTS <= point_count <= OLD_MAX_PRO_POINTS and length in (
            4 + point_count * 6,
            4 + point_count * 7,
        )
    if command == OLD_SCHEDULED_EFFECT:
        return (length - 3) % 6 == 0 and 0 <= (length - 3) // 6 <= OLD_MAX_EFFECT_WINDOWS
    return False


def cbor_map(values: Mapping[int, Any]) -> bytes:
    """Encode the tiny CBOR subset used by Fluval WiFi/mesh BLE light commands."""
    if len(values) > 23:
        raise ValueError("CBOR helper only supports small maps")

    packet = bytearray((0xA0 | len(values),))
    for key, value in values.items():
        packet.extend(_cbor_uint(key))
        packet.extend(_cbor_value(value))
    return bytes(packet)


def decode_spp_auto_schedule(data: dict[int, Any], *, channel_count: int = 5) -> dict[str, Any] | None:
    """Decode current FFF0/SPP Auto schedule keys 8-12 from D2 state."""
    if channel_count not in (4, 5):
        return None
    sunrise = data.get(SPP_AUTO_SUNRISE_KEY)
    sunset = data.get(SPP_AUTO_SUNSET_KEY)
    sleep = data.get(SPP_AUTO_SLEEP_KEY)
    day_levels = data.get(SPP_AUTO_DAY_LEVELS_KEY)
    night_levels = data.get(SPP_AUTO_NIGHT_LEVELS_KEY)
    if not (
        isinstance(sunrise, bytes)
        and len(sunrise) == 3
        and isinstance(sunset, bytes)
        and len(sunset) == 3
        and isinstance(sleep, bytes)
        and len(sleep) == 2
        and isinstance(day_levels, bytes)
        and len(day_levels) == channel_count
        and isinstance(night_levels, bytes)
        and len(night_levels) == channel_count
    ):
        return None
    if (
        sunrise[0] > 23
        or sunrise[1] > 59
        or sunrise[2] > 240
        or sunset[0] > 23
        or sunset[1] > 59
        or sunset[2] > 240
        or (sleep != b"\xff\xff" and (sleep[0] > 23 or sleep[1] > 59))
        or any(level > 100 for level in day_levels)
        or any(level > 100 for level in night_levels)
    ):
        return None
    return {
        "sunrise": f"{sunrise[0]:02d}:{sunrise[1]:02d}",
        "sunrise_ramp": sunrise[2],
        "sunset": f"{sunset[0]:02d}:{sunset[1]:02d}",
        "sunset_ramp": sunset[2],
        "sleep": None if sleep[0] == 0xFF else f"{sleep[0]:02d}:{sleep[1]:02d}",
        "day_levels": list(day_levels[:channel_count]),
        "night_levels": list(night_levels[:channel_count]),
    }


def decode_spp_pro_schedule(
    data: dict[int, Any],
    *,
    channel_count: int = 5,
) -> list[dict[str, Any]] | None:
    """Decode the current FFF0/SPP key-13 Pro schedule."""
    if channel_count not in (4, 5):
        return None
    blob = data.get(SPP_PRO_SCHEDULE_KEY)
    if not isinstance(blob, bytes) or not blob:
        return None
    count = blob[0]
    record_size = 2 + channel_count
    if not SPP_MIN_PRO_POINTS <= count <= SPP_MAX_PRO_POINTS or len(blob) != 1 + (count * record_size):
        return None
    points = []
    for index in range(count):
        offset = 1 + index * record_size
        hour = blob[offset]
        minute = blob[offset + 1]
        levels = blob[offset + 2 : offset + record_size]
        if hour > 23 or minute > 59 or any(level > 100 for level in levels):
            return None
        points.append({"time": f"{hour:02d}:{minute:02d}", "levels": list(levels)})
    return points


def decode_spp_effect_schedule(
    data: dict[int, Any],
    *,
    maximum_effect_id: int = 4,
) -> list[dict[str, Any]] | None:
    """Decode the current FFF0/SPP key-15 timed-effect schedule."""
    blob = data.get(SPP_EFFECT_SCHEDULE_KEY)
    if not isinstance(blob, bytes) or len(blob) != SPP_MAX_EFFECT_WINDOWS * 6:
        return None
    return _decode_effect_schedule_blob(
        blob,
        maximum=SPP_MAX_EFFECT_WINDOWS,
        maximum_effect_id=maximum_effect_id,
    )


def _decode_effect_schedule_blob(
    blob: bytes,
    *,
    maximum: int,
    maximum_effect_id: int,
) -> list[dict[str, Any]] | None:
    """Decode the APK's shared six-byte timed-effect window records."""
    if len(blob) % 6 or len(blob) > maximum * 6:
        return None
    windows = []
    for offset in range(0, len(blob), 6):
        flags, start_h, start_m, end_h, end_m, effect_id = blob[offset : offset + 6]
        if not any((flags, start_h, start_m, end_h, end_m, effect_id)):
            continue
        if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
            return None
        if not 1 <= effect_id <= maximum_effect_id:
            return None
        windows.append(
            {
                "enabled": bool(flags & 0x80),
                "weekdays": [bool(flags & (1 << day)) for day in range(7)],
                "start": f"{start_h:02d}:{start_m:02d}",
                "end": f"{end_h:02d}:{end_m:02d}",
                "effect_id": effect_id,
            }
        )
    return windows


def decode_cbor_map(data: bytes | bytearray) -> dict[Any, Any] | None:
    """Decode the CBOR maps the FACEBD controllers use for light state."""
    if not data or data[0] >> 5 != 5:
        return None

    try:
        value, offset = _read_cbor_value(bytes(data), 0)
    except (UnicodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if offset != len(data):
        return None
    return value


def decode_cbor_update(data: bytes | bytearray) -> dict[Any, Any] | None:
    """Decode a raw CBOR map or a current-controller D1/D2 frame."""
    if not data:
        return None
    if data[0] in (SPP_COMMAND_HEADER, SPP_STATUS_HEADER):
        return decode_cbor_map(data[1:])
    return decode_cbor_map(data)


def _clock_payload(now: datetime | None = None) -> bytes:
    """Return Y M D W h m s used by old and mesh clock sync."""
    moment = (now or datetime.now().astimezone()).astimezone()
    # FluvalConnect TimeUtil.getWeeks(): Monday = 1 through Sunday = 7.
    weekday = moment.isoweekday()
    return bytes(
        (
            moment.year % 100,
            moment.month,
            moment.day,
            weekday,
            moment.hour,
            moment.minute,
            moment.second,
        )
    )


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _checked_minute(hour: int, minute: int) -> int | None:
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _ramp_dict(minute: int, ramp: int) -> dict[str, int]:
    return {"hour": minute // 60, "minute": minute % 60, "ramp": ramp}


def _decode_minute(value: Any) -> dict[str, int] | None:
    if isinstance(value, bool) or not isinstance(value, int) or value == 0xFFFF:
        return None
    if not 0 <= value < 1440:
        return None
    return {"hour": value // 60, "minute": value % 60}


def _decode_minute_pair(value: Any, *, sunrise: bool) -> dict[str, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    start, end = value
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or not 0 <= start < 1440
        or not 0 <= end < 1440
    ):
        return None
    ramp = (end - start) % 1440
    if ramp > 240:
        return None
    return _ramp_dict(start if sunrise else end, ramp)


def _decode_time_ramp(value: Any) -> dict[str, int] | None:
    if not isinstance(value, bytes) or len(value) < 3:
        return None
    hour, minute, ramp = value[:3]
    if hour > 23 or minute > 59:
        return None
    return {"hour": hour, "minute": minute, "ramp": ramp}


def _decode_sleep_time(value: Any) -> dict[str, int] | None:
    if not isinstance(value, bytes) or len(value) < 2:
        return None
    hour, minute = value[:2]
    if (hour, minute) == (0xFF, 0xFF):
        return None
    if hour > 23 or minute > 59:
        return None
    return {"hour": hour, "minute": minute}


def _decode_levels(value: Any, *, exact: int) -> list[int] | None:
    if not isinstance(value, bytes) or len(value) != exact:
        return None
    levels = list(value)
    if any(level > 100 for level in levels):
        return None
    return levels


def _cbor_bytes(value: bytes) -> bytes:
    return _cbor_major(2, len(value)) + value


def _cbor_value(value: Any) -> bytes:
    if isinstance(value, bool):
        return bytes((0xF5 if value else 0xF4,))
    if isinstance(value, bytes):
        return _cbor_bytes(value)
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _cbor_major(3, len(encoded)) + encoded
    if isinstance(value, (list, tuple)):
        return _cbor_major(4, len(value)) + b"".join(_cbor_value(item) for item in value)
    if isinstance(value, int):
        return _cbor_int(value)
    raise TypeError(f"Unsupported Fluval CBOR value: {type(value).__name__}")


def _cbor_int(value: int) -> bytes:
    if value >= 0:
        return _cbor_uint(value)
    # Major type 1: negative integer -1 - n
    return _cbor_major(1, -1 - value)


def _cbor_uint(value: int) -> bytes:
    if value < 0:
        raise ValueError("CBOR helper only supports unsigned integers")
    return _cbor_major(0, value)


def _cbor_major(major: int, value: int) -> bytes:
    if value < 24:
        return bytes(((major << 5) | value,))
    if value <= 0xFF:
        return bytes(((major << 5) | 24, value))
    if value <= 0xFFFF:
        return bytes(((major << 5) | 25, value >> 8, value & 0xFF))
    if value <= 0xFFFFFFFF:
        return bytes(((major << 5) | 26, *value.to_bytes(4, "big")))
    return bytes(((major << 5) | 27, *value.to_bytes(8, "big")))


def _read_cbor_value(data: bytes, offset: int, depth: int = 0) -> tuple[Any, int]:
    if depth > MAX_CBOR_NESTING_DEPTH:
        raise ValueError("CBOR nesting is too deep")
    if offset >= len(data):
        raise ValueError("Unexpected end of CBOR data")

    item = data[offset]
    major = item >> 5

    if item == 0xF4:
        return False, offset + 1
    if item == 0xF5:
        return True, offset + 1

    if major == 0:
        return _read_cbor_uint(data, offset)
    if major == 1:
        value, offset = _read_cbor_length(data, offset)
        return -1 - value, offset
    if major in (2, 3):
        length, offset = _read_cbor_length(data, offset)
        if length > MAX_CBOR_BYTE_STRING_LENGTH:
            raise ValueError("CBOR byte/text string is too large")
        end = offset + length
        if end > len(data):
            raise ValueError("CBOR byte/text string is truncated")
        raw = data[offset:end]
        if major == 2:
            return bytes(raw), end
        return raw.decode("utf-8", errors="replace"), end
    if major == 4:
        length, offset = _read_cbor_length(data, offset)
        if length > MAX_CBOR_CONTAINER_ITEMS:
            raise ValueError("CBOR array has too many items")
        items = []
        for _ in range(length):
            value, offset = _read_cbor_value(data, offset, depth + 1)
            items.append(value)
        return items, offset
    if major == 5:
        length, offset = _read_cbor_length(data, offset)
        if length > MAX_CBOR_CONTAINER_ITEMS:
            raise ValueError("CBOR map has too many items")
        result = {}
        for _ in range(length):
            key, offset = _read_cbor_value(data, offset, depth + 1)
            value, offset = _read_cbor_value(data, offset, depth + 1)
            if not isinstance(key, (bool, bytes, int, str, type(None))):
                raise ValueError("CBOR map key is not hashable")
            result[key] = value
        return result, offset
    if major == 7:
        if item == 0xF6:
            return None, offset + 1
        if item == 0xF9:
            return None, offset + 3
        if item == 0xFA:
            return None, offset + 5
        if item == 0xFB:
            return None, offset + 9

    raise ValueError(f"Unsupported CBOR item 0x{item:02x}")


def _read_cbor_uint(data: bytes, offset: int) -> tuple[int, int]:
    item = data[offset]
    major = item >> 5
    if major != 0:
        raise ValueError(f"Expected unsigned CBOR integer, got 0x{item:02x}")
    return _read_cbor_length(data, offset)


def _read_cbor_length(data: bytes, offset: int) -> tuple[int, int]:
    """Read a CBOR additional-info length or unsigned integer."""
    item = data[offset]
    additional = item & 0x1F
    if additional < 24:
        return additional, offset + 1
    if additional == 24:
        _require_length(data, offset, 2)
        return data[offset + 1], offset + 2
    if additional == 25:
        _require_length(data, offset, 3)
        return int.from_bytes(data[offset + 1 : offset + 3], "big"), offset + 3
    if additional == 26:
        _require_length(data, offset, 5)
        return int.from_bytes(data[offset + 1 : offset + 5], "big"), offset + 5
    if additional == 27:
        _require_length(data, offset, 9)
        return int.from_bytes(data[offset + 1 : offset + 9], "big"), offset + 9
    raise ValueError(f"Unsupported CBOR integer length {additional}")


def _require_length(data: bytes, offset: int, needed: int) -> None:
    if offset + needed > len(data):
        raise ValueError("CBOR value is truncated")
