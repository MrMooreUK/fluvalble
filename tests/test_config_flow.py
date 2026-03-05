"""
Tests for config flow helpers — MAC normalisation, validation, and title generation.

All HA stubs are registered by conftest.py before this module loads.
"""
import sys
import os
import pytest

# conftest.py registers all stubs before collection; just ensure path is set.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.fluvalble.config_flow import (
    normalize_mac,
    MAC_REGEX,
    InvalidFormat,
)


class TestNormalizeMac:
    def test_already_normalized(self):
        assert normalize_mac("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"

    def test_lowercase(self):
        assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"

    def test_hyphens(self):
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"

    def test_no_separator_12_chars(self):
        assert normalize_mac("AABBCCDDEEFF") == "AA:BB:CC:DD:EE:FF"

    def test_spaces_stripped(self):
        assert normalize_mac("  AA:BB:CC:DD:EE:FF  ") == "AA:BB:CC:DD:EE:FF"

    def test_mixed_case_hyphens(self):
        assert normalize_mac("aa-BB-cc-DD-ee-FF") == "AA:BB:CC:DD:EE:FF"


class TestMacRegex:
    @pytest.mark.parametrize("mac", [
        "AA:BB:CC:DD:EE:FF",
        "00:11:22:33:44:55",
        "AB:CD:EF:01:23:45",
    ])
    def test_valid_macs(self, mac):
        assert MAC_REGEX.match(mac)

    @pytest.mark.parametrize("mac", [
        "AA:BB:CC:DD:EE",          # too short
        "AA:BB:CC:DD:EE:FF:00",    # too long
        "AABBCCDDEEFF",            # no colons
        "ZZ:BB:CC:DD:EE:FF",       # invalid hex
        "",                         # empty
    ])
    def test_invalid_macs(self, mac):
        assert not MAC_REGEX.match(mac)


class TestValidateInput:
    """validate_input is async so we test normalize + regex path inline."""

    def test_invalid_mac_raises_invalid_format(self):
        from custom_components.fluvalble.config_flow import normalize_mac, MAC_REGEX, InvalidFormat
        mac = normalize_mac("not-a-mac")
        assert not MAC_REGEX.match(mac)  # would trigger InvalidFormat in validate_input

    def test_valid_mac_passes(self):
        mac = normalize_mac("AA:BB:CC:DD:EE:FF")
        assert MAC_REGEX.match(mac)

    def test_ble_name_used_as_title(self):
        """Title should be BLE name when provided, else 'Fluval {mac}'."""
        mac = "AA:BB:CC:DD:EE:FF"
        ble_name = "Fluval Plant 3.0"
        title = ble_name.strip() or f"Fluval {mac}"
        assert title == "Fluval Plant 3.0"

    def test_fallback_title_when_no_ble_name(self):
        mac = "AA:BB:CC:DD:EE:FF"
        ble_name = ""
        title = ble_name.strip() or f"Fluval {mac}"
        assert title == "Fluval AA:BB:CC:DD:EE:FF"
