"""Tests for config-entry lifecycle cleanup."""

import asyncio
import sys
from types import SimpleNamespace
import types
from unittest.mock import AsyncMock, MagicMock

from homeassistant import config_entries

from custom_components.fluvalble import (
    DOMAIN,
    FluvalRuntimeData,
    _async_update_listener,
    _register_legacy_options_reload,
    _register_static_paths,
    async_unload_entry,
)


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


def test_legacy_options_flow_registers_one_reload_listener(monkeypatch):
    """Supported older HA versions retain one listener-based reload path."""
    remove_listener = MagicMock()
    entry = SimpleNamespace(
        add_update_listener=MagicMock(return_value=remove_listener),
        async_on_unload=MagicMock(),
    )
    monkeypatch.delattr(config_entries, "OptionsFlowWithReload")

    _register_legacy_options_reload(entry)

    entry.add_update_listener.assert_called_once_with(_async_update_listener)
    entry.async_on_unload.assert_called_once_with(remove_listener)


def test_legacy_options_listener_reloads_once():
    """The compatibility listener delegates one reload to Home Assistant."""
    asyncio.run(_async_test_legacy_options_listener_reloads_once())


async def _async_test_legacy_options_listener_reloads_once():
    reload_entry = AsyncMock()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=reload_entry))
    entry = SimpleNamespace(entry_id="entry_1")

    await _async_update_listener(hass, entry)

    reload_entry.assert_awaited_once_with("entry_1")


def test_unload_stops_software_preview_task():
    """A reload must not leave the software preview writing to BLE."""
    asyncio.run(_async_test_unload_stops_software_preview_task())


async def _async_test_unload_stops_software_preview_task():
    preview_task = MagicMock()
    device = SimpleNamespace(
        preview_task=preview_task,
        native_preview_active=False,
        cancel_reachability_refresh=MagicMock(),
        async_stop_preview=AsyncMock(return_value=True),
        client=None,
    )
    runtime = FluvalRuntimeData(device=device)
    entry = SimpleNamespace(entry_id="entry_1", runtime_data=runtime)
    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: runtime}},
        config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True)),
    )

    assert await async_unload_entry(hass, entry)

    device.cancel_reachability_refresh.assert_called_once_with()
    device.async_stop_preview.assert_awaited_once_with()
    assert entry.entry_id not in hass.data[DOMAIN]


def test_static_path_prefers_current_home_assistant_api(monkeypatch):
    """Use the collection-based API while retaining the legacy fallback."""
    asyncio.run(_async_test_static_path_prefers_current_home_assistant_api(monkeypatch))


async def _async_test_static_path_prefers_current_home_assistant_api(monkeypatch):
    class StaticPathConfig:
        def __init__(self, url_path, path, cache_headers):
            self.url_path = url_path
            self.path = path
            self.cache_headers = cache_headers

    http_module = types.ModuleType("homeassistant.components.http")
    http_module.StaticPathConfig = StaticPathConfig
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http_module)

    register_many = AsyncMock()
    register_one = AsyncMock()
    hass = SimpleNamespace(
        data={DOMAIN: {}},
        http=SimpleNamespace(
            async_register_static_paths=register_many,
            async_register_static_path=register_one,
        ),
    )

    await _register_static_paths(hass)

    register_many.assert_awaited_once()
    register_one.assert_not_awaited()
    config = register_many.await_args.args[0][0]
    assert config.url_path == "/fluvalble"
    assert config.cache_headers is False
