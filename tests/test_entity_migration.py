"""Tests for entity cleanup performed during config-entry setup."""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.const import Platform

from custom_components.fluvalble import PLATFORMS, _remove_retired_channel_entities


def test_number_platform_is_replaced_by_native_colour_light():
    assert Platform.LIGHT in PLATFORMS
    assert Platform.NUMBER not in PLATFORMS


def test_only_retired_channel_number_entities_are_removed(monkeypatch):
    channel = SimpleNamespace(
        entity_id="number.fluval_channel_1",
        domain="number",
        unique_id="AABBCCDDEEFF_channel_1",
    )
    unrelated = SimpleNamespace(
        entity_id="number.fluval_transition",
        domain="number",
        unique_id="AABBCCDDEEFF_transition",
    )
    light = SimpleNamespace(
        entity_id="light.fluval_light",
        domain="light",
        unique_id="AABBCCDDEEFF_light",
    )
    registry = MagicMock()
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = MagicMock(return_value=registry)
    entity_registry.async_entries_for_config_entry = MagicMock(return_value=[channel, unrelated, light])
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry,
    )

    _remove_retired_channel_entities(
        MagicMock(),
        SimpleNamespace(entry_id="entry_1"),
    )

    registry.async_remove.assert_called_once_with(channel.entity_id)
