"""Fluval classic BLE framing, matching FluvalConnect ``EncodeUtil``."""

from __future__ import annotations

import random
from typing import Final

IV: Final = 0x54
PLAINTEXT_CHUNK: Final = 15


def encode_message(source: bytearray | bytes, *, key: int | None = None) -> bytearray:
    """Encode one plaintext chunk using the APK's native envelope."""
    payload = bytes(source)
    use_key = random.randint(0, 255) if key is None else key & 0xFF
    encoded = bytearray((IV, (len(payload) + 1) ^ IV, IV ^ use_key))
    encoded.extend(value ^ use_key for value in payload)
    return encoded


def decode_message(source: bytes | bytearray) -> bytes:
    """Decode one APK envelope using the key embedded in its header."""
    if len(source) < 3:
        return b""
    key = source[0] ^ source[2]
    return bytes(value ^ key for value in source[3:])


def encode_message_chunks(source: bytearray | bytes, *, key: int | None = None) -> list[bytearray]:
    """Chunk plaintext at 15 bytes and encode each chunk independently."""
    payload = bytes(source)
    return [
        encode_message(payload[offset : offset + PLAINTEXT_CHUNK], key=key)
        for offset in range(0, len(payload), PLAINTEXT_CHUNK)
    ]


def encrypt(source: bytearray | bytes) -> bytearray:
    """Backward-compatible wrapper using the APK's random-key encoder."""
    return encode_message(source)


def decrypt(source: bytes | bytearray) -> bytes:
    """Backward-compatible wrapper around the APK decoder."""
    return decode_message(source)


def add_crc(source: bytearray) -> bytearray:
    """Append the classic command XOR checksum in place."""
    checksum = 0
    for value in source:
        checksum ^= value
    source.append(checksum)
    return source


def is_valid_fluval_frame(data: bytes | bytearray) -> bool:
    """Return whether data is one complete checksummed classic frame."""
    if len(data) < 3 or data[0] != 0x68:
        return False
    checksum = 0
    for value in data:
        checksum ^= value
    return checksum == 0
