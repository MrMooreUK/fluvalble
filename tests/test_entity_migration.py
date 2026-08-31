"""Tests for entity cleanup performed during config-entry setup."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.const import Platform

from custom_components.fluvalble import PLATFORMS, _remove_retired_entities


def test_retired_platforms_are_replaced_by_native_colour_light():
    assert Platform.LIGHT in PLATFORMS
    assert Platform.NUMBER not in PLATFORMS
    assert Platform.SWITCH not in PLATFORMS


def test_retired_platform_and_diagnostic_entities_are_removed(monkeypatch):
    channel = SimpleNamespace(
        entity_id="number.fluval_channel_1",
        domain="number",
        unique_id="AABBCCDDEEFF_channel_1",
    )
    legacy_number = SimpleNamespace(
        entity_id="number.fluval_transition",
        domain="number",
        unique_id="AABBCCDDEEFF_transition",
    )
    legacy_switch = SimpleNamespace(
        entity_id="switch.fluval_led",
        domain="switch",
        unique_id="AABBCCDDEEFF_led_on_off",
    )
    light = SimpleNamespace(
        entity_id="light.fluval_light",
        domain="light",
        unique_id="AABBCCDDEEFF_light",
    )
    diagnostics = SimpleNamespace(
        entity_id="sensor.fluval_diagnostics",
        domain="sensor",
        unique_id="AABBCCDDEEFF_diagnostics",
    )
    refresh = SimpleNamespace(
        entity_id="button.fluval_refresh_diagnostics",
        domain="button",
        unique_id="AABBCCDDEEFF_refresh_diagnostics",
    )
    channel_test = SimpleNamespace(
        entity_id="button.fluval_test_led_channels",
        domain="button",
        unique_id="AABBCCDDEEFF_test_led_channels",
    )
    registry = MagicMock()
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = MagicMock(return_value=registry)
    entity_registry.async_entries_for_config_entry = MagicMock(
        return_value=[channel, legacy_number, legacy_switch, light, diagnostics, refresh, channel_test]
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )

    _remove_retired_entities(
        MagicMock(),
        SimpleNamespace(entry_id="entry_1"),
    )

    assert [call.args[0] for call in registry.async_remove.call_args_list] == [
        channel.entity_id,
        legacy_number.entity_id,
        legacy_switch.entity_id,
        diagnostics.entity_id,
        refresh.entity_id,
        channel_test.entity_id,
    ]
