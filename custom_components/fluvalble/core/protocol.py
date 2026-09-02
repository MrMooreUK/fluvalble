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
WIFI_AUTO_PREVIEW_KEY = 119
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
SPP_SCHEDULE_PREVIEW_KEY = 51
SPP_MIN_PRO_POINTS = 4
SPP_MAX_PRO_POINTS = 12
SPP_MAX_EFFECT_WINDOWS = 7

OLD_READ_PARAMS = bytes((0x68, 0x05))
OLD_MODE = 0x02
OLD_SWITCH = 0x03
OLD_ALL_ZONE = 0x04
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
    """Build the FACEBD WiFi-over-BLE packet for the five color channels."""
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


def wifi_auto_schedule_packet(
    *,
    sunrise: tuple[int, int, int],
    sunset: tuple[int, int, int],
    sleep: tuple[int, int] | None,
    day_levels: Iterable[int],
    night_levels: Iterable[int],
    channel_count: int = 4,
) -> bytes:
    """Build the FluvalConnect FACEBD native Auto schedule map.

    Keys 114/115 contain start/end minutes, key 116 is the optional sleep
    minute (65535 means disabled), and keys 117/118 contain channel levels.
    The public schedule API expresses sunrise as start+ramp and sunset as
    end+ramp, matching the mesh fixture API, so convert that representation to
    the FACEBD controller's absolute minute pairs here.
    """
    if channel_count not in (4, 5):
        raise ValueError("FACEBD Fluval schedules require four or five channels")
    sunrise_start = _minute_of_day(sunrise[0], sunrise[1])
    sunrise_end = min(1439, sunrise_start + _clamp_ramp(sunrise[2]))
    sunset_end = _minute_of_day(sunset[0], sunset[1])
    sunset_start = max(0, sunset_end - _clamp_ramp(sunset[2]))
    sleep_minute = 0xFFFF if sleep is None else _minute_of_day(sleep[0], sleep[1])
    return cbor_map(
        {
            WIFI_AUTO_SUNRISE_KEY: [sunrise_start, sunrise_end],
            WIFI_AUTO_SUNSET_KEY: [sunset_start, sunset_end],
            WIFI_AUTO_SLEEP_KEY: sleep_minute,
            WIFI_AUTO_DAY_LEVELS_KEY: _level_bytes(day_levels, count=channel_count),
            WIFI_AUTO_NIGHT_LEVELS_KEY: _level_bytes(night_levels, count=channel_count),
        }
    )


def wifi_pro_schedule_packet(points: Iterable[dict[str, Any]], *, channel_count: int = 4) -> bytes:
    """Build the FluvalConnect FACEBD native Pro schedule map (keys 120-122)."""
    normalized = _normalized_points(points, channel_count=channel_count)
    _validate_pro_point_count(
        len(normalized),
        minimum=WIFI_MIN_PRO_POINTS,
        maximum=WIFI_MAX_PRO_POINTS,
        label="FACEBD",
    )
    times = [minute for minute, _levels in normalized]
    levels = bytes(level for _minute, values in normalized for level in values)
    return cbor_map(
        {
            WIFI_PRO_COUNT_KEY: len(normalized),
            WIFI_PRO_TIMES_KEY: times,
            WIFI_PRO_LEVELS_KEY: levels,
        }
    )


def wifi_auto_preview_packet(minute: int | None) -> bytes:
    """Build FACEBD native preview command; 1440 stops preview in the APK."""
    return cbor_map({WIFI_AUTO_PREVIEW_KEY: 1440 if minute is None else int(minute) % 1440})


def spp_schedule_preview_packet(minute: int | None) -> bytes:
    """Build the APK's Plant Pro/MESH native schedule-preview command."""
    return spp_command({SPP_SCHEDULE_PREVIEW_KEY: 1440 if minute is None else int(minute) % 1440})


def wifi_effect_schedule_packet(windows: Iterable[dict[str, Any]]) -> bytes:
    """Build the APK-native FACEBD timed-effect byte string in CBOR key 123."""
    return cbor_map(
        {
            WIFI_SCHEDULED_EFFECT_KEY: _effect_schedule_blob(
                windows,
                maximum=WIFI_MAX_EFFECT_WINDOWS,
                maximum_effect_id=11,
                label="FACEBD",
            )
        }
    )


def decode_wifi_auto_schedule(data: Mapping[int, Any]) -> dict[str, Any] | None:
    """Decode FACEBD native Auto fields into the integration schedule shape."""
    sunrise = _decode_minute_pair(data.get(WIFI_AUTO_SUNRISE_KEY), sunrise=True)
    sunset = _decode_minute_pair(data.get(WIFI_AUTO_SUNSET_KEY), sunrise=False)
    sleep = _decode_minute(data.get(WIFI_AUTO_SLEEP_KEY))
    day_levels = _decode_levels(data.get(WIFI_AUTO_DAY_LEVELS_KEY), minimum=4)
    night_levels = _decode_levels(data.get(WIFI_AUTO_NIGHT_LEVELS_KEY), minimum=4)
    if all(value is None for value in (sunrise, sunset, sleep, day_levels, night_levels)):
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
    count = data.get(WIFI_PRO_COUNT_KEY)
    times = data.get(WIFI_PRO_TIMES_KEY)
    levels = data.get(WIFI_PRO_LEVELS_KEY)
    if not isinstance(count, int) or not isinstance(times, list) or not isinstance(levels, bytes):
        return None
    if count < 0 or len(times) != count or len(levels) != count * channel_count:
        return None
    points: list[dict[str, Any]] = []
    for index, minute in enumerate(times):
        if not isinstance(minute, int) or not 0 <= minute < 1440:
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
    """Build a Plant Pro 4.0 SPP power packet."""
    return spp_command({SPP_SWITCH_KEY: is_on})


def spp_mode_packet(mode: int) -> bytes:
    """Build a Plant Pro 4.0 SPP mode packet."""
    return spp_command({SPP_MODE_KEY: mode})


def spp_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build a Plant Pro 4.0 SPP five-channel packet."""
    packet = {key: _clamp_percent(value) for key, value in zip(SPP_CHANNEL_KEYS, values, strict=False)}
    packet[SPP_MANUAL_KEY] = 0
    return spp_command(packet)


def spp_single_zone_packet(channel_index: int, value: int) -> bytes:
    """Build the APK Plant Pro/MESH packet for one manual color channel."""
    if not 0 <= channel_index < len(SPP_CHANNEL_KEYS):
        raise ValueError("Plant Pro channel index must be between 0 and 4")
    return spp_command(
        {
            SPP_CHANNEL_KEYS[channel_index]: _clamp_percent(value),
            SPP_MANUAL_KEY: 0,
        }
    )


def spp_effect_packet(effect_id: int) -> bytes:
    """Build a Plant Pro native-effect packet recovered from FluvalConnect."""
    if not 0 <= effect_id <= 4:
        raise ValueError("Plant Pro effect ID must be between 0 and 4")
    return spp_command({SPP_EFFECT_KEY: effect_id})


def spp_find_packet() -> bytes:
    """Build the APK-native Plant Pro/mesh identify command."""
    return spp_command({FIND_KEY: "find"})


def spp_auto_schedule_packet(
    *,
    sunrise: tuple[int, int, int],
    sunset: tuple[int, int, int],
    sleep: tuple[int, int] | None,
    day_levels: Iterable[int],
    night_levels: Iterable[int],
) -> bytes:
    """Build the Plant Pro Auto schedule stored in CBOR keys 8-12."""
    sunrise_data = bytes(_validate_time_with_ramp(sunrise, "sunrise"))
    sunset_data = bytes(_validate_time_with_ramp(sunset, "sunset"))
    sleep_data = bytes((0xFF, 0xFF) if sleep is None else _validate_time(sleep, "sleep"))
    day_data = bytes(_validate_levels(day_levels, "day_levels"))
    night_data = bytes(_validate_levels(night_levels, "night_levels"))
    return spp_command(
        {
            SPP_AUTO_SUNRISE_KEY: sunrise_data,
            SPP_AUTO_SUNSET_KEY: sunset_data,
            SPP_AUTO_SLEEP_KEY: sleep_data,
            SPP_AUTO_DAY_LEVELS_KEY: day_data,
            SPP_AUTO_NIGHT_LEVELS_KEY: night_data,
        }
    )


def spp_pro_schedule_packet(points: Iterable[dict[str, Any]]) -> bytes:
    """Build the Plant Pro Pro-mode multi-point schedule in CBOR key 13."""
    normalized = list(points)
    _validate_pro_point_count(
        len(normalized),
        minimum=SPP_MIN_PRO_POINTS,
        maximum=SPP_MAX_PRO_POINTS,
        label="Plant Pro",
    )
    blob = bytearray((len(normalized),))
    for point in normalized:
        hour, minute = _validate_time((point["hour"], point["minute"]), "point")
        levels = _validate_levels(point["levels"], "point levels")
        blob.extend((hour, minute, *levels))
    return spp_command({SPP_PRO_SCHEDULE_KEY: bytes(blob)})


def spp_effect_schedule_packet(windows: Iterable[dict[str, Any]]) -> bytes:
    """Build seven fixed Plant Pro timed-effect slots in CBOR key 15."""
    blob = _effect_schedule_blob(
        windows,
        maximum=SPP_MAX_EFFECT_WINDOWS,
        maximum_effect_id=4,
        label="Plant Pro",
        fixed_slots=True,
    )
    return spp_command({SPP_EFFECT_SCHEDULE_KEY: blob})


def spp_command(values: Mapping[int, Any]) -> bytes:
    """Build an unencrypted Plant Pro 4.0 SPP command frame."""
    return bytes((SPP_COMMAND_HEADER,)) + cbor_map(values)


def old_read_params_packet() -> bytes:
    """Build the old BLE parameter read packet."""
    return old_packet(OLD_READ_PARAMS)


def old_switch_packet(is_on: bool) -> bytes:
    """Build the old BLE on/off packet."""
    return old_packet(bytes((0x68, OLD_SWITCH, 0x01 if is_on else 0x00)))


def old_auto_schedule_packet(
    *,
    sunrise: tuple[int, int, int],
    sunset: tuple[int, int, int],
    sleep: tuple[int, int] | None,
    day_levels: Iterable[int],
    night_levels: Iterable[int],
    channel_count: int,
) -> bytes:
    """Build classic ``6807`` Auto payload exactly as FluvalConnect exports it."""
    if channel_count not in (4, 5):
        raise ValueError("Classic Fluval schedules require four or five channels")
    sunrise_start = _minute_of_day(sunrise[0], sunrise[1])
    sunrise_end = min(1439, sunrise_start + _clamp_ramp(sunrise[2]))
    sunset_end = _minute_of_day(sunset[0], sunset[1])
    sunset_start = max(0, sunset_end - _clamp_ramp(sunset[2]))
    payload = bytearray((*_hour_minute(sunrise_start), *_hour_minute(sunrise_end)))
    payload.extend(_level_bytes(day_levels, count=channel_count))
    payload.extend((*_hour_minute(sunset_start), *_hour_minute(sunset_end)))
    payload.extend(_level_bytes(night_levels, count=channel_count))
    if sleep is not None:
        payload.extend((1, *_time_bytes(sleep[0], sleep[1])))
    return old_packet(bytes((0x68, OLD_AUTO_SCHEDULE)) + payload)


def old_pro_schedule_packet(points: Iterable[dict[str, Any]], *, channel_count: int) -> bytes:
    """Build classic ``6810`` Pro payload (count + hour/minute/channel points)."""
    if channel_count not in (4, 5):
        raise ValueError("Classic Fluval schedules require four or five channels")
    normalized = _normalized_points(points, channel_count=channel_count)
    _validate_pro_point_count(
        len(normalized),
        minimum=OLD_MIN_PRO_POINTS,
        maximum=OLD_MAX_PRO_POINTS,
        label="Classic Fluval",
    )
    payload = bytearray((len(normalized),))
    for minute, levels in normalized:
        payload.extend((*_hour_minute(minute), *levels))
    return old_packet(bytes((0x68, OLD_PRO_SCHEDULE)) + payload)


def old_effect_schedule_packet(windows: Iterable[dict[str, Any]]) -> bytes:
    """Build classic ``6811`` timed weather-effect windows from the APK."""
    blob = _effect_schedule_blob(
        windows,
        maximum=OLD_MAX_EFFECT_WINDOWS,
        maximum_effect_id=11,
        label="Classic Fluval",
    )
    return old_packet(bytes((0x68, OLD_SCHEDULED_EFFECT)) + blob)


def _validate_pro_point_count(count: int, *, minimum: int, maximum: int, label: str) -> None:
    """Enforce the Professional-schedule limits exposed by FluvalConnect."""
    if not minimum <= count <= maximum:
        raise ValueError(f"{label} schedule requires {minimum}-{maximum} points")


def old_auto_preview_packet(levels: Iterable[int] | None) -> bytes:
    """Build classic host-generated preview frame or the ``680C`` stop frame."""
    if levels is None:
        return old_packet(bytes((0x68, OLD_AUTO_PREVIEW_STOP)))
    payload = bytearray((0x68, OLD_AUTO_PREVIEW))
    for value in levels:
        scaled = _clamp_percent(value) * 10
        payload.extend(((scaled >> 8) & 0xFF, scaled & 0xFF))
    return old_packet(payload)


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
        decoded.update(
            {
                "power": bool(body[1] & 0x01),
                "effect_id": body[2],
                "channels": [body[offset] | (body[offset + 1] << 8) for offset in range(3, 3 + channel_count * 2, 2)],
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


def decode_old_auto_schedule(body: bytes, *, channel_count: int) -> dict[str, Any] | None:
    """Decode the body of a classic mode-1 ``6805`` response."""
    base_length = channel_count * 2 + 9
    if channel_count not in (4, 5) or len(body) < base_length or body[0] != 1:
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
    return {
        "sunrise": _ramp_dict(sunrise_start, max(0, sunrise_end - sunrise_start)),
        "sunset": _ramp_dict(sunset_end, max(0, sunset_end - sunset_start)),
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
    if len(body) < 2 + count * stride:
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
    """Build the old BLE all-channel packet."""
    packet = bytearray((0x68, OLD_ALL_ZONE))
    for value in values:
        scaled = _clamp_percent(value) * 10
        packet.extend((scaled & 0xFF, scaled >> 8))
    return old_packet(packet)


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


def old_packet(packet: bytes) -> bytes:
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


def encrypted_old_packet(packet: bytes) -> bytearray:
    """Wrap an old protocol packet in the original integration encryption."""
    return encryption.encrypt(encryption.add_crc(bytearray(packet)))


def cbor_map(values: Mapping[int, Any]) -> bytes:
    """Encode the tiny CBOR subset used by Fluval WiFi/mesh BLE light commands."""
    if len(values) > 23:
        raise ValueError("CBOR helper only supports small maps")

    packet = bytearray((0xA0 | len(values),))
    for key, value in values.items():
        packet.extend(_cbor_uint(key))
        packet.extend(_cbor_value(value))
    return bytes(packet)


def decode_spp_auto_schedule(data: dict[int, Any]) -> dict[str, Any] | None:
    """Decode Plant Pro Auto schedule keys 8-12 from a D2 state map."""
    sunrise = data.get(SPP_AUTO_SUNRISE_KEY)
    sunset = data.get(SPP_AUTO_SUNSET_KEY)
    sleep = data.get(SPP_AUTO_SLEEP_KEY)
    day_levels = data.get(SPP_AUTO_DAY_LEVELS_KEY)
    night_levels = data.get(SPP_AUTO_NIGHT_LEVELS_KEY)
    if not (
        isinstance(sunrise, bytes)
        and len(sunrise) >= 3
        and isinstance(sunset, bytes)
        and len(sunset) >= 3
        and isinstance(sleep, bytes)
        and len(sleep) >= 2
        and isinstance(day_levels, bytes)
        and len(day_levels) >= 5
        and isinstance(night_levels, bytes)
        and len(night_levels) >= 5
    ):
        return None
    return {
        "sunrise": f"{sunrise[0]:02d}:{sunrise[1]:02d}",
        "sunrise_ramp": sunrise[2],
        "sunset": f"{sunset[0]:02d}:{sunset[1]:02d}",
        "sunset_ramp": sunset[2],
        "sleep": None if sleep[0] == 0xFF else f"{sleep[0]:02d}:{sleep[1]:02d}",
        "day_levels": list(day_levels[:5]),
        "night_levels": list(night_levels[:5]),
    }


def decode_spp_pro_schedule(data: dict[int, Any]) -> list[dict[str, Any]] | None:
    """Decode the Plant Pro key-13 Pro schedule."""
    blob = data.get(SPP_PRO_SCHEDULE_KEY)
    if not isinstance(blob, bytes) or not blob:
        return None
    count = blob[0]
    if count > SPP_MAX_PRO_POINTS or len(blob) < 1 + (count * 7):
        return None
    return [
        {
            "time": f"{blob[1 + index * 7]:02d}:{blob[2 + index * 7]:02d}",
            "levels": list(blob[3 + index * 7 : 8 + index * 7]),
        }
        for index in range(count)
    ]


def decode_spp_effect_schedule(data: dict[int, Any]) -> list[dict[str, Any]] | None:
    """Decode the Plant Pro key-15 seven-slot timed-effect schedule."""
    blob = data.get(SPP_EFFECT_SCHEDULE_KEY)
    if not isinstance(blob, bytes) or len(blob) != SPP_MAX_EFFECT_WINDOWS * 6:
        return None
    return _decode_effect_schedule_blob(
        blob,
        maximum=SPP_MAX_EFFECT_WINDOWS,
        maximum_effect_id=4,
    )


def _effect_schedule_blob(
    windows: Iterable[dict[str, Any]],
    *,
    maximum: int,
    maximum_effect_id: int,
    label: str,
    fixed_slots: bool = False,
) -> bytes:
    """Encode the APK's shared six-byte timed-effect window records."""
    normalized = list(windows)
    if len(normalized) > maximum:
        raise ValueError(f"{label} supports at most {maximum} effect windows")
    blob = bytearray(maximum * 6 if fixed_slots else len(normalized) * 6)
    for index, window in enumerate(normalized):
        start_h, start_m = _validate_time((window["start_hour"], window["start_minute"]), "start")
        end_h, end_m = _validate_time((window["end_hour"], window["end_minute"]), "end")
        effect_id = int(window["effect_id"])
        if not 1 <= effect_id <= maximum_effect_id:
            raise ValueError(f"{label} effect window ID must be between 1 and {maximum_effect_id}")
        weekdays = list(window.get("weekdays", []))
        if len(weekdays) != 7 or any(not isinstance(value, bool) for value in weekdays):
            raise ValueError(f"{label} effect weekdays must contain seven booleans")
        flags = sum((1 << day) for day, enabled in enumerate(weekdays) if enabled)
        if bool(window.get("enabled", True)):
            flags |= 0x80
        offset = index * 6
        blob[offset : offset + 6] = bytes((flags, start_h, start_m, end_h, end_m, effect_id))
    return bytes(blob)


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


def decode_cbor_map(data: bytes) -> dict[Any, Any] | None:
    """Decode the CBOR maps the FACEBD controllers use for light state."""
    if not data or data[0] >> 5 != 5:
        return None

    try:
        value, offset = _read_cbor_value(data, 0)
    except (UnicodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if offset != len(data):
        return None
    return value


def decode_cbor_update(data: bytes) -> dict[Any, Any] | None:
    """Decode a raw CBOR map or a Plant Pro D1/D2 CBOR frame."""
    if not data:
        return None
    if data[0] in (SPP_COMMAND_HEADER, SPP_STATUS_HEADER):
        return decode_cbor_map(data[1:])
    return decode_cbor_map(data)


def _clock_payload(now: datetime | None = None) -> bytes:
    """Return Y M D W h m s used by old and mesh clock sync."""
    moment = (now or datetime.now().astimezone()).astimezone()
    # Fluval week: Sunday = 0
    weekday = (moment.weekday() + 1) % 7
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


def _time_bytes(hour: int, minute: int) -> bytes:
    return bytes((max(0, min(23, int(hour))), max(0, min(59, int(minute)))))


def _validate_time(value: tuple[int, int], label: str) -> tuple[int, int]:
    hour, minute = (int(item) for item in value)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"Plant Pro {label} time is outside the 24-hour range")
    return hour, minute


def _validate_time_with_ramp(value: tuple[int, int, int], label: str) -> tuple[int, int, int]:
    hour, minute = _validate_time((value[0], value[1]), label)
    ramp = int(value[2])
    if not 0 <= ramp <= 240:
        raise ValueError(f"Plant Pro {label} ramp must be between 0 and 240 minutes")
    return hour, minute, ramp


def _validate_levels(values: Iterable[int], label: str) -> list[int]:
    levels = [int(value) for value in values]
    if len(levels) != 5 or any(not 0 <= value <= 100 for value in levels):
        raise ValueError(f"Plant Pro {label} must contain five values from 0 to 100")
    return levels


def _clamp_ramp(value: int) -> int:
    return max(0, min(240, int(value)))


def _minute_of_day(hour: int, minute: int) -> int:
    return max(0, min(23, int(hour))) * 60 + max(0, min(59, int(minute)))


def _hour_minute(minute: int) -> tuple[int, int]:
    normalized = max(0, min(1439, int(minute)))
    return normalized // 60, normalized % 60


def _checked_minute(hour: int, minute: int) -> int | None:
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _ramp_dict(minute: int, ramp: int) -> dict[str, int]:
    return {"hour": minute // 60, "minute": minute % 60, "ramp": ramp}


def _decode_minute(value: Any) -> dict[str, int] | None:
    if not isinstance(value, int) or value == 0xFFFF:
        return None
    if not 0 <= value < 1440:
        return None
    return {"hour": value // 60, "minute": value % 60}


def _decode_minute_pair(value: Any, *, sunrise: bool) -> dict[str, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    start, end = value
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end < 1440:
        return None
    return _ramp_dict(start if sunrise else end, end - start)


def _normalized_points(points: Iterable[dict[str, Any]], *, channel_count: int) -> list[tuple[int, list[int]]]:
    normalized: list[tuple[int, list[int]]] = []
    for point in points:
        minute = int(point.get("minute", 0)) % 1440
        levels = [_clamp_percent(int(point.get(f"channel_{index}", 0))) for index in range(1, channel_count + 1)]
        normalized.append((minute, levels))
    if len(normalized) > 255:
        raise ValueError("Fluval Pro schedule supports at most 255 points")
    return normalized


def _level_bytes(values: Iterable[int], *, count: int = 5) -> bytes:
    levels = [_clamp_percent(value) for value in values]
    levels = [*levels[:count], *([0] * max(0, count - len(levels)))]
    return bytes(levels[:count])


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


def _decode_levels(value: Any, *, minimum: int = 5) -> list[int] | None:
    if not isinstance(value, bytes) or len(value) < minimum:
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
