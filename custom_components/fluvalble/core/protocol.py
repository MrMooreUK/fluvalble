"""Packet builders for Fluval light protocols."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from . import encryption

MAX_CBOR_CONTAINER_ITEMS = 64
MAX_CBOR_BYTE_STRING_LENGTH = 4096
MAX_CBOR_NESTING_DEPTH = 8

WIFI_MODE_KEY = 103
WIFI_SWITCH_KEY = 104
WIFI_MANUAL_KEY = 109
WIFI_CHANNEL_KEYS = (110, 111, 112, 113, 114)

OLD_READ_PARAMS = bytes((0x68, 0x05))
OLD_MODE = 0x02
OLD_SWITCH = 0x03
OLD_ALL_ZONE = 0x04


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
        packet.extend((scaled & 0xFF, scaled >> 8))
    return old_packet(packet)


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
            packet.extend(_cbor_uint(value))
    return bytes(packet)


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


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _cbor_uint(value: int) -> bytes:
    if value < 0:
        raise ValueError("CBOR helper only supports unsigned integers")
    if value < 24:
        return bytes((value,))
    if value <= 0xFF:
        return bytes((0x18, value))
    if value <= 0xFFFF:
        return bytes((0x19, value >> 8, value & 0xFF))
    if value <= 0xFFFFFFFF:
        return bytes((0x1A, *value.to_bytes(4, "big")))
    return bytes((0x1B, *value.to_bytes(8, "big")))


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
