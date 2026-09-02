"""Tests for entity cleanup performed during config-entry setup."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.const import Platform

import custom_components.fluvalble as integration
from custom_components.fluvalble import (
    PLATFORMS,
    _cleanup_duplicate_devices,
    _migrate_legacy_registry_entries,
)


def test_retired_platforms_are_replaced_by_native_colour_light():
    assert Platform.LIGHT in PLATFORMS
    assert Platform.NUMBER not in PLATFORMS
    assert Platform.SWITCH in PLATFORMS


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
    dst_switch = SimpleNamespace(
        entity_id="switch.fluval_daylight_saving_time",
        domain="switch",
        unique_id="AABBCCDDEEFF_daylight_saving_time",
    )
    schedule_mode = SimpleNamespace(
        entity_id="select.fluval_schedule_mode",
        domain="select",
        unique_id="AABBCCDDEEFF_schedule_mode",
    )
    mode = SimpleNamespace(
        entity_id="select.fluval_mode",
        domain="select",
        unique_id="AABBCCDDEEFF_mode",
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
        return_value=[
            channel,
            legacy_number,
            legacy_switch,
            dst_switch,
            schedule_mode,
            mode,
            light,
            diagnostics,
            refresh,
            channel_test,
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )

    device_registry = MagicMock()
    monkeypatch.setattr(integration.dr, "async_get", MagicMock(return_value=device_registry), raising=False)
    monkeypatch.setattr(
        integration.dr,
        "async_entries_for_config_entry",
        MagicMock(return_value=[]),
        raising=False,
    )

    _migrate_legacy_registry_entries(
        MagicMock(),
        SimpleNamespace(entry_id="entry_1"),
        "AA:BB:CC:DD:EE:FF",
    )

    assert [call.args[0] for call in registry.async_remove.call_args_list] == [
        channel.entity_id,
        legacy_number.entity_id,
        legacy_switch.entity_id,
        schedule_mode.entity_id,
        diagnostics.entity_id,
        refresh.entity_id,
        channel_test.entity_id,
    ]


def test_mac_is_removed_from_legacy_serial_number(monkeypatch):
    device_entry = SimpleNamespace(id="device_1", serial_number="AA:BB:CC:DD:EE:FF")
    device_registry = MagicMock()
    entity_registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.async_get = MagicMock(return_value=MagicMock())
    entity_registry_module.async_entries_for_config_entry = MagicMock(return_value=[])
    monkeypatch.setattr(integration.dr, "async_get", MagicMock(return_value=device_registry), raising=False)
    monkeypatch.setattr(
        integration.dr,
        "async_entries_for_config_entry",
        MagicMock(return_value=[device_entry]),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module)

    _migrate_legacy_registry_entries(
        MagicMock(),
        SimpleNamespace(entry_id="entry_1"),
        "AA:BB:CC:DD:EE:FF",
    )

    device_registry.async_update_device.assert_called_once_with("device_1", serial_number=None)


def test_duplicate_device_rows_are_safely_consolidated(monkeypatch):
    canonical = SimpleNamespace(
        id="canonical",
        identifiers={("fluvalble", "AA:BB:CC:DD:EE:FF")},
        connections=set(),
        config_entries={"entry_1"},
    )
    duplicate = SimpleNamespace(
        id="duplicate",
        identifiers={("fluvalble", "legacy")},
        connections=set(),
        config_entries={"entry_1"},
    )
    own_entity = SimpleNamespace(
        entity_id="sensor.legacy",
        device_id="duplicate",
        config_entry_id="entry_1",
    )
    device_registry = MagicMock()
    entity_registry = MagicMock()
    entity_registry.entities = {own_entity.entity_id: own_entity}
    entity_registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.async_get = MagicMock(return_value=entity_registry)
    entity_registry_module.async_entries_for_config_entry = MagicMock(return_value=[own_entity])
    monkeypatch.setattr(integration.dr, "async_get", MagicMock(return_value=device_registry), raising=False)
    monkeypatch.setattr(
        integration.dr,
        "async_entries_for_config_entry",
        MagicMock(return_value=[canonical, duplicate]),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module)

    _cleanup_duplicate_devices(MagicMock(), SimpleNamespace(entry_id="entry_1"), "AA:BB:CC:DD:EE:FF")

    entity_registry.async_update_entity.assert_called_once_with("sensor.legacy", device_id="canonical")
    device_registry.async_remove_device.assert_called_once_with("duplicate")


def test_duplicate_device_owned_by_another_entry_is_preserved(monkeypatch):
    canonical = SimpleNamespace(
        id="canonical",
        identifiers={("fluvalble", "AA:BB:CC:DD:EE:FF")},
        connections=set(),
        config_entries={"entry_1"},
    )
    duplicate = SimpleNamespace(
        id="duplicate",
        identifiers={("fluvalble", "legacy")},
        connections=set(),
        config_entries={"entry_1", "other_entry"},
    )
    device_registry = MagicMock()
    entity_registry = MagicMock()
    entity_registry.entities = {}
    entity_registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry_module.async_get = MagicMock(return_value=entity_registry)
    entity_registry_module.async_entries_for_config_entry = MagicMock(return_value=[])
    monkeypatch.setattr(integration.dr, "async_get", MagicMock(return_value=device_registry), raising=False)
    monkeypatch.setattr(
        integration.dr,
        "async_entries_for_config_entry",
        MagicMock(return_value=[canonical, duplicate]),
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", entity_registry_module)

    _cleanup_duplicate_devices(MagicMock(), SimpleNamespace(entry_id="entry_1"), "AA:BB:CC:DD:EE:FF")

    device_registry.async_remove_device.assert_not_called()
