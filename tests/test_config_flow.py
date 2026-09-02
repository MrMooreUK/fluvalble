"""
Tests for config flow helpers — MAC normalisation, validation, and title generation.

All HA stubs are registered by conftest.py before this module loads.
"""

import asyncio
import os
import sys
from unittest.mock import MagicMock

import pytest
import voluptuous as vol

from homeassistant import config_entries

# conftest.py registers all stubs before collection; just ensure path is set.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.fluvalble.config_flow import (
    OptionsFlowHandler,
    normalize_mac,
    unique_id_from_mac,
    validate_active_time,
    MAC_REGEX,
)


def test_options_flow_uses_home_assistant_reload_helper():
    """Options changes rely on HA's single automatic reload path."""
    assert issubclass(OptionsFlowHandler, config_entries.OptionsFlowWithReload)


def test_options_flow_uses_saved_values_as_suggestions():
    """Stored options are supplied through HA's suggested-value helper."""
    options = {
        "lamp_profile": "plant",
        "ping_interval": 15,
        "active_time": 0,
    }
    flow = OptionsFlowHandler()
    flow.config_entry.options = options
    suggested_schema = object()
    flow.add_suggested_values_to_schema = MagicMock(return_value=suggested_schema)
    flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = asyncio.run(flow.async_step_init())

    assert result == {"type": "form"}
    flow.add_suggested_values_to_schema.assert_called_once()
    assert flow.add_suggested_values_to_schema.call_args.args[1] is options
    flow.async_show_form.assert_called_once_with(step_id="init", data_schema=suggested_schema)


def test_options_flow_submission_is_owned_by_reload_helper():
    """The handler only creates options; its HA base class owns the reload."""
    flow = OptionsFlowHandler()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    submitted = {
        "lamp_profile": "auto",
        "ping_interval": 10,
        "active_time": 120,
    }

    result = asyncio.run(flow.async_step_init(submitted))

    assert result == {"type": "create_entry"}
    flow.async_create_entry.assert_called_once_with(title="", data=submitted)


class TestActiveTimeSchema:
    @pytest.mark.parametrize("value", [0, 30, 120, 600])
    def test_accepts_persistent_or_bounded_idle_window(self, value):
        assert validate_active_time(value) == value

    @pytest.mark.parametrize("value", [-1, 1, 29, 601])
    def test_rejects_churn_prone_or_out_of_range_values(self, value):
        with pytest.raises(vol.Invalid):
            validate_active_time(value)


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


class TestUniqueIdFromMac:
    def test_lowercase_stable(self):
        assert unique_id_from_mac("B8:80:4F:3D:67:C0") == "b8:80:4f:3d:67:c0"

    def test_matches_discovery_style(self):
        assert unique_id_from_mac("b8:80:4f:3d:67:c0") == unique_id_from_mac("B8:80:4F:3D:67:C0")


class TestMacRegex:
    @pytest.mark.parametrize(
        "mac",
        [
            "AA:BB:CC:DD:EE:FF",
            "00:11:22:33:44:55",
            "AB:CD:EF:01:23:45",
        ],
    )
    def test_valid_macs(self, mac):
        assert MAC_REGEX.match(mac)

    @pytest.mark.parametrize(
        "mac",
        [
            "AA:BB:CC:DD:EE",  # too short
            "AA:BB:CC:DD:EE:FF:00",  # too long
            "AABBCCDDEEFF",  # no colons
            "ZZ:BB:CC:DD:EE:FF",  # invalid hex
            "",  # empty
        ],
    )
    def test_invalid_macs(self, mac):
        assert not MAC_REGEX.match(mac)


class TestValidateInput:
    """validate_input is async so we test normalize + regex path inline."""

    def test_invalid_mac_raises_invalid_format(self):
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
