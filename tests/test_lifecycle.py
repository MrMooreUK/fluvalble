"""Tests for config-entry lifecycle cleanup."""

import asyncio
import sys
from types import SimpleNamespace
import types
from unittest.mock import AsyncMock, MagicMock

from custom_components.fluvalble import DOMAIN, FluvalRuntimeData, _register_static_paths, async_unload_entry


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
