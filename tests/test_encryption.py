"""
Unit tests for the Fluval BLE encryption module.

The encryption module is pure Python with no external deps so it is imported
directly from its file path to avoid loading the full HA package hierarchy.
"""
import importlib.util
import os
import sys

# conftest.py registers all stubs (bleak, homeassistant) before this file
# is imported — so custom_components can be loaded through sys.path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.fluvalble.core import encryption


class TestAddCrc:
    def test_empty_packet(self):
        data = bytearray()
        result = encryption.add_crc(data)
        assert result == bytearray([0x00])

    def test_single_byte(self):
        data = bytearray([0x68])
        result = encryption.add_crc(data)
        # CRC = XOR of all bytes = 0x68
        assert result[-1] == 0x68

    def test_two_bytes(self):
        data = bytearray([0x68, 0x05])
        result = encryption.add_crc(data)
        # CRC = 0x68 ^ 0x05 = 0x6D
        assert result[-1] == 0x6D

    def test_crc_appended_in_place(self):
        data = bytearray([0x01, 0x02, 0x03])
        original_len = len(data)
        result = encryption.add_crc(data)
        assert len(result) == original_len + 1
        assert result is data  # mutates in place and returns same object


class TestEncrypt:
    def test_structure(self):
        """Encrypted packet must have IV + length + key prefix then payload."""
        payload = bytearray([0x68, 0x05, 0x6D])
        result = encryption.encrypt(payload)
        assert result[0] == 0x54  # IV
        assert result[2] == 0x54  # key (rand=0 → key=IV)
        assert len(result) == 3 + len(payload)

    def test_length_field(self):
        payload = bytearray([0xAA, 0xBB])
        result = encryption.encrypt(payload)
        # length byte = (len(payload) + 1) XOR 0x54
        expected_length_byte = (len(payload) + 1) ^ 0x54
        assert result[1] == expected_length_byte

    def test_payload_unchanged_with_rand_zero(self):
        """With rand=0 the payload should pass through unchanged."""
        payload = bytearray([0x11, 0x22, 0x33])
        result = encryption.encrypt(payload)
        assert list(result[3:]) == list(payload)


class TestDecrypt:
    def test_round_trip(self):
        """encrypt → decrypt should return the original payload."""
        original = bytearray([0x68, 0x04, 0x00, 0x64, 0x00, 0x64])
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)
        assert list(decrypted) == list(original)

    def test_short_packet(self):
        """Decrypt a minimal 3-byte packet (no payload) returns empty bytes."""
        packet = bytearray([0x54, 0x01 ^ 0x54, 0x54])
        result = encryption.decrypt(packet)
        assert result == bytearray()

    def test_key_derivation(self):
        """Key = source[0] XOR source[2]; payload bytes XOR that key."""
        # Construct a packet manually: IV=0x10, key_byte=0x30, payload=[0x40]
        # XOR key = 0x10 ^ 0x30 = 0x20; decrypted byte = 0x40 ^ 0x20 = 0x60
        packet = bytearray([0x10, 0xFF, 0x30, 0x40])
        result = encryption.decrypt(packet)
        assert result[0] == 0x60


class TestAddCrcAndEncryptIntegration:
    def test_command_mode_manual(self):
        """CMD_MODE = manual (0x68, 0x02, 0x00) should survive add_crc + encrypt + decrypt."""
        cmd = bytearray([0x68, 0x02, 0x00])
        with_crc = encryption.add_crc(bytearray(cmd))  # copy so we can compare
        encrypted = encryption.encrypt(with_crc)
        decrypted = encryption.decrypt(encrypted)
        assert list(decrypted) == list(with_crc)

    def test_command_switch_on(self):
        """CMD_SWITCH on (0x68, 0x03, 0x01) round trip."""
        cmd = bytearray([0x68, 0x03, 0x01])
        with_crc = encryption.add_crc(bytearray(cmd))
        encrypted = encryption.encrypt(with_crc)
        decrypted = encryption.decrypt(encrypted)
        assert list(decrypted) == list(with_crc)
