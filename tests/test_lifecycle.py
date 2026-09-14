"""Tests for config-entry lifecycle cleanup."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant import config_entries

from custom_components.fluvalble import (
    DOMAIN,
    FluvalRuntimeData,
    _store_entry_runtime_data,
    _async_update_listener,
    _register_legacy_options_reload,
    entry_runtime_data,
)
from custom_components.fluvalble import binary_sensor, button, light, number, select, sensor, switch


def test_unload_cleans_runtime_without_preview_support():
    async def run():
        from custom_components.fluvalble import async_unload_entry

        device = SimpleNamespace(
            cancel_reachability_refresh=MagicMock(),
            async_cancel_channel_mode_restore=AsyncMock(),
            client=SimpleNamespace(stop=AsyncMock()),
        )
        runtime = FluvalRuntimeData(device=device)
        entry = SimpleNamespace(entry_id="test_entry", runtime_data=runtime)
        hass = SimpleNamespace(
            data={DOMAIN: {"test_entry": runtime}},
            config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True)),
        )
        assert await async_unload_entry(hass, entry)
        device.cancel_reachability_refresh.assert_called_once()
        device.async_cancel_channel_mode_restore.assert_awaited_once()
        device.client.stop.assert_awaited_once()
        assert "test_entry" not in hass.data[DOMAIN]

    asyncio.run(run())


def test_current_options_flow_does_not_register_second_reload_listener():
    """Current HA owns the reload, so setup must not add another path."""
    entry = SimpleNamespace(
        add_update_listener=MagicMock(),
        async_on_unload=MagicMock(),
    )

    _register_legacy_options_reload(entry)

    assert hasattr(config_entries, "OptionsFlowWithReload")
    entry.add_update_listener.assert_not_called()
    entry.async_on_unload.assert_not_called()


def test_runtime_data_falls_back_to_hass_data_on_home_assistant_2024_1():
    """Legacy ConfigEntry objects have no runtime_data slot."""

    class LegacyConfigEntry:
        __slots__ = ("entry_id",)

        def __init__(self):
            self.entry_id = "entry_1"

    entry = LegacyConfigEntry()
    hass = SimpleNamespace(data={DOMAIN: {}})
    runtime = FluvalRuntimeData()

    _store_entry_runtime_data(hass, entry, runtime)

    assert not hasattr(entry, "runtime_data")
    assert entry_runtime_data(hass, entry) is runtime


def test_runtime_data_uses_config_entry_slot_when_available():
    entry = SimpleNamespace(entry_id="entry_1", runtime_data=None)
    hass = SimpleNamespace(data={DOMAIN: {}})
    runtime = FluvalRuntimeData()

    _store_entry_runtime_data(hass, entry, runtime)

    assert entry.runtime_data is runtime
    assert entry_runtime_data(hass, entry) is runtime


def test_all_entity_platforms_support_legacy_runtime_storage():
    asyncio.run(_async_test_all_entity_platforms_support_legacy_runtime_storage())


async def _async_test_all_entity_platforms_support_legacy_runtime_storage():
    entry = SimpleNamespace(entry_id="entry_1")
    runtime = FluvalRuntimeData()
    hass = SimpleNamespace(data={DOMAIN: {entry.entry_id: runtime}})

    for platform_module, platform in (
        (binary_sensor, "binary_sensor"),
        (button, "button"),
        (light, "light"),
        (number, "number"),
        (select, "select"),
        (sensor, "sensor"),
        (switch, "switch"),
    ):
        add_entities = MagicMock()
        await platform_module.async_setup_entry(hass, entry, add_entities)
        add_entities.assert_not_called()
        assert runtime.pending_add_entities[platform] is add_entities


def test_legacy_options_flow_registers_one_reload_listener(monkeypatch):
    """Supported older HA versions retain one listener-based reload path."""
    remove_listener = MagicMock()
    entry = SimpleNamespace(
        options={"active_time": 30},
        add_update_listener=MagicMock(return_value=remove_listener),
        async_on_unload=MagicMock(),
    )
    monkeypatch.delattr(config_entries, "OptionsFlowWithReload")

    _register_legacy_options_reload(entry)

    entry.add_update_listener.assert_called_once()
    entry.async_on_unload.assert_called_once_with(remove_listener)

    listener = entry.add_update_listener.call_args.args[0]
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=AsyncMock()))
    entry.entry_id = "entry_1"
    entry.data = {"model": "Plant 3.0"}
    asyncio.run(listener(hass, entry))
    hass.config_entries.async_reload.assert_not_awaited()
    entry.options = {"active_time": 0}
    asyncio.run(listener(hass, entry))
    asyncio.run(listener(hass, entry))
    hass.config_entries.async_reload.assert_awaited_once_with("entry_1")


def test_legacy_options_listener_reloads_once():
    """The compatibility listener delegates one reload to Home Assistant."""
    asyncio.run(_async_test_legacy_options_listener_reloads_once())


async def _async_test_legacy_options_listener_reloads_once():
    reload_entry = AsyncMock()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=reload_entry))
    entry = SimpleNamespace(entry_id="entry_1")

    await _async_update_listener(hass, entry)

    reload_entry.assert_awaited_once_with("entry_1")


@pytest.mark.parametrize("old, expected", [(0, 120), (30, 30), (600, 600)])
def test_connection_window_migration_preserves_other_options(old, expected):
    from custom_components.fluvalble import _migrate_connection_window

    entry = SimpleNamespace(options={"active_time": old, "lamp_profile": "aquasky"})
    update = MagicMock()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    assert _migrate_connection_window(hass, entry) == expected
    if old == 0:
        update.assert_called_once_with(entry, options={"active_time": 120, "lamp_profile": "aquasky"})
    else:
        update.assert_not_called()


def test_setup_does_not_load_retired_cards():
    import inspect
    from custom_components.fluvalble import async_setup_entry

    assert "_register_static_paths" not in inspect.getsource(async_setup_entry)
