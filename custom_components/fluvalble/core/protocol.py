"""Packet builders for Fluval light protocols."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from . import encryption

WIFI_TZ_OFFSET_KEY = 101
WIFI_CLOCK_MS_KEY = 102
WIFI_MODE_KEY = 103
WIFI_SWITCH_KEY = 104
WIFI_MANUAL_KEY = 109
WIFI_CHANNEL_KEYS = (110, 111, 112, 113, 114)

OLD_READ_PARAMS = bytes((0x68, 0x05))
OLD_MODE = 0x02
OLD_SWITCH = 0x03
OLD_ALL_ZONE = 0x04
OLD_CLOCK = 0x0E

# Mesh clock opcode (full mesh command path is a later PR)
MESH_OPCODE_CLOCK = 0xCD


def wifi_switch_packet(is_on: bool) -> bytes:
    """Build the FACEBD WiFi-over-BLE on/off packet."""
    return cbor_map({WIFI_SWITCH_KEY: is_on})


def wifi_mode_packet(mode: int) -> bytes:
    """Build the FACEBD WiFi-over-BLE mode packet."""
    return cbor_map({WIFI_MODE_KEY: mode})


def wifi_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build the FACEBD WiFi-over-BLE packet for the five color channels."""
    packet = {WIFI_MANUAL_KEY: 0}
    packet.update({key: _clamp_percent(value) for key, value in zip(WIFI_CHANNEL_KEYS, values, strict=False)})
    return cbor_map(packet)


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
    """Build mesh clock sync (opcode 0xCD + Y M D W h m s)."""
    return bytes((MESH_OPCODE_CLOCK,)) + _clock_payload(now)


def old_read_params_packet() -> bytes:
    """Build the old BLE parameter read packet."""
    return old_packet(OLD_READ_PARAMS)


def old_switch_packet(is_on: bool) -> bytes:
    """Build the old BLE on/off packet."""
    return old_packet(bytes((0x68, OLD_SWITCH, 0x01 if is_on else 0x00)))


def old_mode_packet(mode: int) -> bytes:
    """Build the old BLE mode packet."""
    return old_packet(bytes((0x68, OLD_MODE, mode & 0xFF)))


def old_all_zone_packet(values: Iterable[int]) -> bytes:
    """Build the old BLE all-channel packet."""
    packet = bytearray((0x68, OLD_ALL_ZONE))
    for value in values:
        scaled = _clamp_percent(value) * 10
        # APK helper name says "Little", but it only zero-pads a hex word;
        # the command payload is sent high byte first, e.g. 100% -> 03 E8.
        packet.extend((scaled >> 8, scaled & 0xFF))
    return old_packet(packet)


def old_clock_packet(now: datetime | None = None) -> bytes:
    """Build old BLE clock sync (cmd 0x0E: Y M D W h m s)."""
    return old_packet(bytes((0x68, OLD_CLOCK)) + _clock_payload(now))


def old_packet(packet: bytes) -> bytes:
    """Append the XOR checksum used by the old light protocol."""
    checksum = 0
    for item in packet:
        checksum ^= item
    return bytes(packet) + bytes((checksum,))


def encrypted_old_packet(packet: bytes) -> bytearray:
    """Wrap an old protocol packet in the original integration encryption."""
    return encryption.encrypt(encryption.add_crc(bytearray(packet)))


def cbor_map(values: dict[int, bool | int]) -> bytes:
    """Encode the tiny CBOR subset used by Fluval WiFi BLE light commands."""
    if len(values) > 23:
        raise ValueError("CBOR helper only supports small maps")

    packet = bytearray((0xA0 | len(values),))
    for key, value in values.items():
        packet.extend(_cbor_uint(key))
        if isinstance(value, bool):
            packet.append(0xF5 if value else 0xF4)
        else:
            packet.extend(_cbor_int(value))
    return bytes(packet)


def decode_cbor_map(data: bytes) -> dict[Any, Any] | None:
    """Decode the CBOR maps the FACEBD controllers use for light state."""
    if not data or data[0] >> 5 != 5:
        return None

    value, _offset = _read_cbor_value(data, 0)
    if not isinstance(value, dict):
        return None
    return value


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


def _read_cbor_value(data: bytes, offset: int) -> tuple[Any, int]:
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
        end = offset + length
        if end > len(data):
            raise ValueError("CBOR byte/text string is truncated")
        raw = data[offset:end]
        if major == 2:
            return bytes(raw), end
        return raw.decode("utf-8", errors="replace"), end
    if major == 4:
        length, offset = _read_cbor_length(data, offset)
        items = []
        for _ in range(length):
            value, offset = _read_cbor_value(data, offset)
            items.append(value)
        return items, offset
    if major == 5:
        length, offset = _read_cbor_length(data, offset)
        result = {}
        for _ in range(length):
            key, offset = _read_cbor_value(data, offset)
            value, offset = _read_cbor_value(data, offset)
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
