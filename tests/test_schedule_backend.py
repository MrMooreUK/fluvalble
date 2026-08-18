"""Tests for saved schedules and the HA-managed auto scheduler."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.fluvalble import (
    DOMAIN,
    FluvalRuntimeData,
    _async_apply_auto_schedule,
    _async_apply_startup_schedule,
    _async_load_schedule,
    _async_load_schedule_data,
    _async_run_auto_schedule,
    _async_save_schedule,
    _validate_schedule_points,
    async_set_schedule_mode,
)
from custom_components.fluvalble.core.device import Device


class _MemoryStore:
    data = None

    def __init__(self, *args, **kwargs):
        pass

    async def async_load(self):
        return self.__class__.data

    async def async_save(self, data):
        self.__class__.data = data


class _FakeHass:
    def __init__(self, device=None):
        runtime = FluvalRuntimeData(device=device)
        self.data = {DOMAIN: {"entry_1": runtime}}


def _make_device():
    device = Device(
        "AquaSky3.0_Test",
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": "AquaSky Bluetooth LED",
        },
    )
    device.connected = True
    return device


def _schedule_points():
    return [
        {"time": "19:00", "red": 3, "green": 0, "blue": 8, "white": 0},
        {"time": "20:00", "red": 0, "green": 0, "blue": 0, "white": 0},
    ]


def test_schedule_validator_rejects_malformed_points():
    with pytest.raises(vol.Invalid):
        _validate_schedule_points([{"time": "not-a-time"}, {"time": "20:00"}])


def test_schedule_validator_limits_schedule_size():
    points = [{"time": "00:00"}, {"time": "00:01"}] * 49
    with pytest.raises(vol.Invalid):
        _validate_schedule_points(points)


def test_schedule_validator_rejects_unknown_fields():
    with pytest.raises(vol.Invalid):
        _validate_schedule_points([{"time": "19:00", "unexpected": 1}, {"time": "20:00"}])


def test_schedule_validator_normalizes_missing_channels():
    validated = _validate_schedule_points([{"time": "19:00", "blue": 8}, {"time": "20:00"}])
    assert validated[0] == {
        "time": "19:00",
        "red": 0,
        "green": 0,
        "blue": 8,
        "white": 0,
        "channel_5": 0,
    }


def test_save_and_load_schedule_data(monkeypatch):
    asyncio.run(_async_test_save_and_load_schedule_data(monkeypatch))


async def _async_test_save_and_load_schedule_data(monkeypatch):
    import custom_components.fluvalble as integration

    _MemoryStore.data = None
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    hass = _FakeHass()
    points = _schedule_points()

    await _async_save_schedule(hass, "entry_1", points, mode="auto")

    assert await _async_load_schedule(hass, "entry_1") == points
    assert await _async_load_schedule_data(hass, "entry_1") == {
        "points": points,
        "mode": "auto",
    }


def test_save_schedule_preserves_existing_mode(monkeypatch):
    asyncio.run(_async_test_save_schedule_preserves_existing_mode(monkeypatch))


async def _async_test_save_schedule_preserves_existing_mode(monkeypatch):
    import custom_components.fluvalble as integration

    _MemoryStore.data = {"schedules": {"entry_1": {"points": [], "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    points = _schedule_points()

    await _async_save_schedule(_FakeHass(), "entry_1", points)

    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "auto"
    assert _MemoryStore.data["schedules"]["entry_1"]["points"] == points


def test_control_schedule_mode_updates_the_saved_schedule(monkeypatch):
    asyncio.run(_async_test_control_schedule_mode_updates_the_saved_schedule(monkeypatch))


async def _async_test_control_schedule_mode_updates_the_saved_schedule(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    hass = _FakeHass(device)
    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    run_auto_schedule = AsyncMock(return_value=True)
    monkeypatch.setattr(integration, "_async_run_auto_schedule", run_auto_schedule)

    await async_set_schedule_mode(hass, "entry_1", "auto")

    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "auto"
    assert device.schedule_mode == "auto"
    run_auto_schedule.assert_awaited_once_with(hass, "entry_1")


def test_load_schedule_supports_legacy_list_records(monkeypatch):
    asyncio.run(_async_test_load_schedule_supports_legacy_list_records(monkeypatch))


async def _async_test_load_schedule_supports_legacy_list_records(monkeypatch):
    import custom_components.fluvalble as integration

    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": points}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    assert await _async_load_schedule_data(_FakeHass(), "entry_1") == {
        "points": points,
        "mode": "manual",
    }


def test_auto_schedule_ignores_manual_mode(monkeypatch):
    asyncio.run(_async_test_auto_schedule_ignores_manual_mode(monkeypatch))


async def _async_test_auto_schedule_ignores_manual_mode(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.async_set_channels = AsyncMock()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    await _async_apply_auto_schedule(_FakeHass(device), "entry_1")

    device.async_set_channels.assert_not_called()
    assert device.diagnostics["auto_schedule_last_result"] == "manual_mode"


def test_auto_schedule_skips_unchanged_values(monkeypatch):
    asyncio.run(_async_test_auto_schedule_skips_unchanged_values(monkeypatch))


async def _async_test_auto_schedule_skips_unchanged_values(monkeypatch):
    import homeassistant.util.dt as dt_util
    import custom_components.fluvalble as integration

    device = _make_device()
    device.values.update({"channel_1": 3, "channel_2": 0, "channel_3": 8, "channel_4": 0})
    device.conn_info["last_seen"] = datetime(2026, 1, 1, 19, 0, tzinfo=UTC)
    device.async_set_channels = AsyncMock()
    handler = MagicMock()
    device.updates_connect.append(handler)
    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    dt_util.now.return_value = datetime(2026, 1, 1, 19, 0, tzinfo=UTC)
    dt_util.utcnow.return_value = datetime(2026, 1, 1, 19, 0, tzinfo=UTC)

    await _async_apply_auto_schedule(_FakeHass(device), "entry_1")

    device.async_set_channels.assert_not_called()
    assert device.diagnostics["status"] == "auto_schedule_skipped"
    assert device.diagnostics["auto_schedule_last_result"] == "unchanged"
    handler.assert_called_once()


def test_auto_schedule_applies_interpolated_values(monkeypatch):
    asyncio.run(_async_test_auto_schedule_applies_interpolated_values(monkeypatch))


async def _async_test_auto_schedule_applies_interpolated_values(monkeypatch):
    import homeassistant.util.dt as dt_util
    import custom_components.fluvalble as integration

    device = _make_device()
    device.async_set_channels = AsyncMock(return_value=True)
    device.conn_info["last_seen"] = datetime(2026, 1, 1, 19, 30, tzinfo=UTC)
    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    dt_util.now.return_value = datetime(2026, 1, 1, 19, 30, tzinfo=UTC)
    dt_util.utcnow.return_value = datetime(2026, 1, 1, 19, 30, tzinfo=UTC)

    await _async_apply_auto_schedule(_FakeHass(device), "entry_1")

    device.async_set_channels.assert_awaited_once_with(
        {
            "channel_1": 2,
            "channel_2": 0,
            "channel_3": 4,
            "channel_4": 0,
            "channel_5": 0,
        },
        force=False,
    )
    assert device.diagnostics["status"] == "auto_schedule_applied"
    assert device.diagnostics["auto_schedule_time"] == "19:30"


def test_auto_schedule_retries_when_cached_values_are_stale(monkeypatch):
    asyncio.run(_async_test_auto_schedule_retries_when_cached_values_are_stale(monkeypatch))


async def _async_test_auto_schedule_retries_when_cached_values_are_stale(monkeypatch):
    import homeassistant.util.dt as dt_util
    import custom_components.fluvalble as integration

    device = _make_device()
    device.connected = False
    device.values.update({"channel_1": 3, "channel_2": 0, "channel_3": 8, "channel_4": 0})
    device.async_set_channels = AsyncMock(return_value=True)
    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    dt_util.now.return_value = datetime(2026, 1, 1, 19, 0, tzinfo=UTC)
    dt_util.utcnow.return_value = datetime(2026, 1, 1, 19, 0, tzinfo=UTC)

    await _async_apply_auto_schedule(_FakeHass(device), "entry_1")

    device.async_set_channels.assert_awaited_once_with(
        {"channel_1": 3, "channel_2": 0, "channel_3": 8, "channel_4": 0, "channel_5": 0},
        force=True,
    )


def test_auto_schedule_records_failed_writes(monkeypatch):
    asyncio.run(_async_test_auto_schedule_records_failed_writes(monkeypatch))


async def _async_test_auto_schedule_records_failed_writes(monkeypatch):
    import homeassistant.util.dt as dt_util
    import custom_components.fluvalble as integration

    device = _make_device()
    device.diagnostics["last_error"] = "No Fluval BLE write target accepted the command"
    device.async_set_channels = AsyncMock(return_value=False)
    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    dt_util.now.return_value = datetime(2026, 1, 1, 19, 30, tzinfo=UTC)

    await _async_apply_auto_schedule(_FakeHass(device), "entry_1")

    assert device.diagnostics["status"] == "auto_schedule_failed"
    assert device.diagnostics["auto_schedule_last_result"] == "failed"
    assert device.diagnostics["auto_schedule_last_error"] == "No Fluval BLE write target accepted the command"


def test_auto_schedule_retries_an_unverified_facebd_write(monkeypatch):
    asyncio.run(_async_test_auto_schedule_retries_an_unverified_facebd_write(monkeypatch))


async def _async_test_auto_schedule_retries_an_unverified_facebd_write(
    monkeypatch,
):
    import custom_components.fluvalble as integration
    import homeassistant.util.dt as dt_util

    device = _make_device()
    device.client = MagicMock(raw_facebd=True, last_write_verified=False)
    device.async_set_channels = AsyncMock(return_value=True)
    _MemoryStore.data = {
        "schedules": {
            "entry_1": {
                "points": _schedule_points(),
                "mode": "auto",
            }
        }
    }
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    dt_util.now.return_value = datetime(2026, 1, 1, 19, 30, tzinfo=UTC)
    dt_util.utcnow.return_value = datetime(2026, 1, 1, 19, 30, tzinfo=UTC)

    assert not await _async_apply_auto_schedule(_FakeHass(device), "entry_1")

    assert device.diagnostics["status"] == "auto_schedule_unverified"
    assert device.diagnostics["auto_schedule_last_result"] == "unverified"
    assert device.diagnostics["auto_schedule_last_error"] == "The AquaSky did not confirm the requested channel state"


def test_auto_schedule_pauses_during_channel_test(monkeypatch):
    asyncio.run(_async_test_auto_schedule_pauses_during_channel_test(monkeypatch))


async def _async_test_auto_schedule_pauses_during_channel_test(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.channel_test_active = True
    device.async_set_channels = AsyncMock()
    _MemoryStore.data = {
        "schedules": {
            "entry_1": {
                "points": _schedule_points(),
                "mode": "auto",
            }
        }
    }
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    assert await _async_apply_auto_schedule(_FakeHass(device), "entry_1")

    device.async_set_channels.assert_not_awaited()
    assert device.diagnostics["auto_schedule_last_result"] == "channel_test_active"


def test_auto_schedule_records_unexpected_exception(monkeypatch):
    asyncio.run(_async_test_auto_schedule_records_unexpected_exception(monkeypatch))


async def _async_test_auto_schedule_records_unexpected_exception(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    monkeypatch.setattr(
        integration,
        "_async_apply_auto_schedule",
        AsyncMock(side_effect=RuntimeError("storage unavailable")),
    )

    await _async_run_auto_schedule(_FakeHass(device), "entry_1")

    assert device.diagnostics["status"] == "auto_schedule_failed"
    assert device.diagnostics["auto_schedule_last_result"] == "exception"


def test_startup_schedule_waits_for_the_bluetooth_device(monkeypatch):
    asyncio.run(_async_test_startup_schedule_waits_for_the_bluetooth_device(monkeypatch))


async def _async_test_startup_schedule_waits_for_the_bluetooth_device(monkeypatch):
    import custom_components.fluvalble as integration

    hass = _FakeHass()
    device = _make_device()
    apply = AsyncMock(return_value=True)

    async def make_device_available(_seconds):
        hass.data[DOMAIN]["entry_1"].device = device

    monkeypatch.setattr(integration, "_async_run_auto_schedule", apply)
    monkeypatch.setattr(integration.asyncio, "sleep", make_device_available)

    await _async_apply_startup_schedule(hass, "entry_1")

    apply.assert_awaited_once_with(hass, "entry_1")
    assert device.diagnostics["auto_schedule_startup_attempt"] == 2
