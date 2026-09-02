"""Tests for saved schedules and fixture-native scheduling."""

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.fluvalble import (
    DOMAIN,
    FluvalRuntimeData,
    _async_schedule_payload,
    _async_save_effect_schedule,
    _async_load_schedule,
    _async_load_schedule_data,
    _async_migrate_legacy_auto_schedule,
    _async_save_schedule,
    _validate_native_auto_schedule,
    _validate_native_effect_windows,
    _validate_native_pro_points,
    _async_upload_native_schedule,
    _native_schedule_readback,
    _normalize_effect_schedule,
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
        {"time": "08:00", "red": 0, "green": 0, "blue": 0, "white": 0},
        {"time": "12:00", "red": 10, "green": 10, "blue": 10, "white": 10},
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


def test_native_auto_schedule_validator_normalizes_fixture_payload():
    schedule = _validate_native_auto_schedule(
        {
            "sunrise": "08:00",
            "sunrise_ramp": 60,
            "sunset": "20:30",
            "sunset_ramp": 45,
            "sleep": "23:15",
            "day": {
                "red": 80,
                "blue": 70,
                "cool_white": 60,
                "warm_white": 50,
                "amber": 40,
            },
            "night": {
                "red": 0,
                "blue": 5,
                "cool_white": 0,
                "warm_white": 0,
                "amber": 0,
            },
        }
    )

    assert schedule["sunrise"] == (8, 0, 60)
    assert schedule["sunset"] == (20, 30, 45)
    assert schedule["day_levels"] == [80, 70, 60, 50, 40]


def test_native_pro_and_effect_validators_normalize_service_objects():
    points = _validate_native_pro_points(
        [
            {
                "time": "08:00",
                "red": 0,
                "blue": 0,
                "cool_white": 0,
                "warm_white": 0,
                "amber": 0,
            },
            {
                "time": "12:30",
                "red": 80,
                "blue": 70,
                "cool_white": 60,
                "warm_white": 50,
                "amber": 40,
            },
            {
                "time": "20:00",
                "red": 0,
                "blue": 0,
                "cool_white": 0,
                "warm_white": 0,
                "amber": 0,
            },
            {
                "time": "22:00",
                "red": 0,
                "blue": 0,
                "cool_white": 0,
                "warm_white": 0,
                "amber": 0,
            },
        ]
    )
    windows = _validate_native_effect_windows(
        [
            {
                "start": "12:00",
                "end": "12:10",
                "effect": "Thunderstorm",
                "weekdays": ["monday", "wednesday", "friday"],
            }
        ]
    )

    assert points == [
        {"hour": 8, "minute": 0, "levels": [0, 0, 0, 0, 0]},
        {"hour": 12, "minute": 30, "levels": [80, 70, 60, 50, 40]},
        {"hour": 20, "minute": 0, "levels": [0, 0, 0, 0, 0]},
        {"hour": 22, "minute": 0, "levels": [0, 0, 0, 0, 0]},
    ]
    assert windows[0]["effect_id"] == 1
    assert windows[0]["weekdays"] == [True, False, True, False, True, False, False]


def test_native_effect_validator_accepts_classic_and_facebd_weather_catalog():
    windows = _validate_native_effect_windows(
        [
            {
                "start": "22:00",
                "end": "22:10",
                "effect": "Crescent moon",
            }
        ]
    )

    assert windows[0]["effect_id"] == 11
    assert windows[0]["weekdays"] == [True] * 7


def test_native_effect_validator_matches_apk_weekday_rules():
    with pytest.raises(vol.Invalid, match="only one effect window"):
        _validate_native_effect_windows(
            [
                {
                    "start": "12:00",
                    "end": "12:10",
                    "effect": "Thunderstorm",
                    "weekdays": ["monday"],
                },
                {
                    "start": "13:00",
                    "end": "13:10",
                    "effect": "Lightning",
                    "weekdays": ["monday"],
                },
            ]
        )

    with pytest.raises(vol.Invalid, match="at least one weekday"):
        _validate_native_effect_windows([{"start": "12:00", "end": "12:10", "effect": "Thunderstorm", "weekdays": []}])

    with pytest.raises(vol.Invalid, match="cannot both be 00:00"):
        _validate_native_effect_windows([{"start": "00:00", "end": "00:00", "effect": "Thunderstorm"}])


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
        "effect_windows": None,
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
    asyncio.run(_async_test_removed_ha_auto_mode_is_rejected(monkeypatch))


async def _async_test_removed_ha_auto_mode_is_rejected(monkeypatch):
    import custom_components.fluvalble as integration
    from homeassistant.exceptions import HomeAssistantError

    device = _make_device()
    hass = _FakeHass(device)
    _MemoryStore.data = {"schedules": {"entry_1": {"points": _schedule_points(), "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    with pytest.raises(HomeAssistantError, match="Unsupported fixture schedule mode"):
        await async_set_schedule_mode(hass, "entry_1", "auto")


def test_native_schedule_mode_uploads_once_to_the_fixture(monkeypatch):
    asyncio.run(_async_test_native_schedule_mode_uploads_once_to_the_fixture(monkeypatch))


async def _async_test_native_schedule_mode_uploads_once_to_the_fixture(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=True)
    hass = _FakeHass(device)
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    await async_set_schedule_mode(hass, "entry_1", "native")

    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "native"
    device.async_set_native_pro_schedule.assert_awaited_once_with(points, activate=True)


def test_native_schedule_upload_rejects_more_than_twelve_points():
    asyncio.run(_async_test_native_schedule_upload_rejects_more_than_twelve_points())


async def _async_test_native_schedule_upload_rejects_more_than_twelve_points():
    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=True)
    points = [{"time": f"{hour:02d}:00"} for hour in range(13)]

    assert not await _async_upload_native_schedule(_FakeHass(device), "entry_1", points)
    device.async_set_native_pro_schedule.assert_not_awaited()
    assert device.diagnostics["native_schedule_last_result"] == "invalid_point_count"


def test_failed_native_mode_upload_does_not_replace_working_mode(monkeypatch):
    asyncio.run(_async_test_failed_native_mode_upload_does_not_replace_working_mode(monkeypatch))


async def _async_test_failed_native_mode_upload_does_not_replace_working_mode(monkeypatch):
    import custom_components.fluvalble as integration
    from homeassistant.exceptions import HomeAssistantError

    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=False)
    device.command_error_message = MagicMock(return_value="write failed")
    hass = _FakeHass(device)
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "manual"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    with pytest.raises(HomeAssistantError, match="write failed"):
        await async_set_schedule_mode(hass, "entry_1", "native")

    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "manual"


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
        "effect_windows": None,
    }


def test_effect_schedule_normalizes_submitted_and_fixture_shapes():
    submitted = _normalize_effect_schedule(
        [
            {
                "start_hour": 12,
                "start_minute": 5,
                "end_hour": 12,
                "end_minute": 15,
                "effect_id": 2,
                "weekdays": [True, False, True, False, False, False, False],
                "enabled": True,
            }
        ]
    )

    assert submitted == [
        {
            "start": "12:05",
            "end": "12:15",
            "effect": "Lightning",
            "weekdays": ["monday", "wednesday"],
            "enabled": True,
        }
    ]
    assert _normalize_effect_schedule([]) == []
    assert _normalize_effect_schedule([{"start": "12:00"}]) is None


def test_saving_effect_schedule_preserves_professional_curve(monkeypatch):
    asyncio.run(_async_test_saving_effect_schedule_preserves_professional_curve(monkeypatch))


async def _async_test_saving_effect_schedule_preserves_professional_curve(monkeypatch):
    import custom_components.fluvalble as integration

    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "native"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    await _async_save_effect_schedule(
        _FakeHass(),
        "entry_1",
        [
            {
                "start_hour": 12,
                "start_minute": 0,
                "end_hour": 12,
                "end_minute": 10,
                "effect_id": 1,
                "weekdays": [True, False, False, False, False, False, False],
                "enabled": True,
            }
        ],
    )

    assert _MemoryStore.data["schedules"]["entry_1"] == {
        "points": points,
        "mode": "native",
        "effect_windows": [
            {
                "start": "12:00",
                "end": "12:10",
                "effect": "Thunderstorm",
                "weekdays": ["monday"],
                "enabled": True,
            }
        ],
    }


def test_manual_schedule_mode_disables_fixture_scheduler(monkeypatch):
    asyncio.run(_async_test_manual_schedule_mode_disables_fixture_scheduler(monkeypatch))


async def _async_test_manual_schedule_mode_disables_fixture_scheduler(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.values["mode"] = "professional"
    device.async_select_option = AsyncMock(return_value=True)
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "native"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    await async_set_schedule_mode(_FakeHass(device), "entry_1", "manual")

    device.async_select_option.assert_awaited_once_with("mode", "manual")
    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "manual"


def test_legacy_auto_schedule_migrates_to_fixture(monkeypatch):
    asyncio.run(_async_test_legacy_auto_schedule_migrates_to_fixture(monkeypatch))


async def _async_test_legacy_auto_schedule_migrates_to_fixture(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.async_set_native_pro_schedule = AsyncMock(return_value=True)
    points = _schedule_points()
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    await _async_migrate_legacy_auto_schedule(_FakeHass(device), "entry_1")

    device.async_set_native_pro_schedule.assert_awaited_once_with(points, activate=True)
    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "native"


def test_legacy_schedule_over_fixture_limit_becomes_manual(monkeypatch):
    asyncio.run(_async_test_legacy_schedule_over_fixture_limit_becomes_manual(monkeypatch))


async def _async_test_legacy_schedule_over_fixture_limit_becomes_manual(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    points = [{"time": f"{hour:02d}:00"} for hour in range(13)]
    _MemoryStore.data = {"schedules": {"entry_1": {"points": points, "mode": "auto"}}}
    monkeypatch.setattr(integration, "Store", _MemoryStore)

    await _async_migrate_legacy_auto_schedule(_FakeHass(device), "entry_1")

    assert _MemoryStore.data["schedules"]["entry_1"]["mode"] == "manual"
    assert device.diagnostics["native_schedule_last_result"] == "legacy_schedule_requires_edit"


def test_integration_has_no_recurring_ha_schedule_executor():
    import custom_components.fluvalble as integration

    source = inspect.getsource(integration)
    assert "async_track_time_interval" not in source
    assert "_async_run_auto_schedule" not in source


def test_schedule_card_exposes_fixture_native_auto_editor():
    source = (
        Path(__file__).parents[1] / "custom_components" / "fluvalble" / "www" / "fluvalble-schedule-card.js"
    ).read_text(encoding="utf-8")

    assert 'callService("set_native_auto_schedule"' in source
    assert "Save Auto to fixture" in source
    assert "Load Auto from fixture" in source
    assert "sunrise_ramp" in source
    assert "day_levels" in source


def test_fixture_schedule_readback_normalizes_protocol_shapes():
    device = _make_device()
    device.values.update(
        {
            "mode": "professional",
            "native_auto_schedule": {
                "sunrise": {"hour": 8, "minute": 0, "ramp": 60},
                "sunset": {"hour": 20, "minute": 30, "ramp": 45},
                "sleep": {"hour": 23, "minute": 15},
                "day_levels": [80, 70, 60, 50],
                "night_levels": [0, 5, 0, 0],
            },
            "native_pro_schedule": [
                {"time": "08:00", "levels": [10, 20, 30, 40, 50]},
                {"minute": 750, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
            ],
            "native_effect_schedule": [
                {
                    "start": "12:00",
                    "end": "12:10",
                    "effect": "Lightning",
                    "weekdays": [True, False, True, False, False, False, False],
                    "enabled": True,
                }
            ],
        }
    )
    device.conn_info["service_uuids"] = ["facebd00-0000-1000-8000-00805f9b34fb"]
    device.facebd = True
    device.diagnostics.update(
        {
            "native_schedule_protocol": "facebd",
            "native_schedule_readback_at": "2026-08-31T18:00:00+00:00",
        }
    )

    readback = _native_schedule_readback(device)

    assert readback["available"] is True
    assert readback["protocol"] == "facebd"
    assert readback["auto"] == {
        "sunrise": "08:00",
        "sunrise_ramp": 60,
        "sunset": "20:30",
        "sunset_ramp": 45,
        "sleep": "23:15",
        "day_levels": [80, 70, 60, 50],
        "night_levels": [0, 5, 0, 0],
    }
    assert readback["professional"] == [
        {"time": "08:00", "red": 10, "green": 20, "blue": 30, "white": 40, "channel_5": 50},
        {"time": "12:30", "red": 1, "green": 2, "blue": 3, "white": 4, "channel_5": 0},
    ]
    assert readback["effects"] == [
        {
            "start": "12:00",
            "end": "12:10",
            "effect": "Lightning",
            "weekdays": ["monday", "wednesday"],
            "enabled": True,
        }
    ]
    assert readback["channels"] == ["Red", "Green", "Blue", "White"]
    assert readback["effect_options"] == [
        "Thunderstorm",
        "Lightning",
        "Sun and lightning",
        "Colour cycle",
        "Mostly sunny",
        "Partly sunny",
        "Partly cloudy",
        "Mostly cloudy",
        "Full moon",
        "Half moon",
        "Crescent moon",
    ]
    assert readback["effect_readback_complete"] is True


def test_schedule_payload_refreshes_fixture_only_when_requested(monkeypatch):
    asyncio.run(_async_test_schedule_payload_refreshes_fixture_only_when_requested(monkeypatch))


async def _async_test_schedule_payload_refreshes_fixture_only_when_requested(monkeypatch):
    import custom_components.fluvalble as integration

    device = _make_device()
    device.async_refresh_state = AsyncMock(return_value=True)
    device.values["native_pro_schedule"] = [
        {"minute": 480, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40}
    ]
    effect_windows = [
        {
            "start": "12:00",
            "end": "12:10",
            "effect": "Lightning",
            "weekdays": ["monday"],
            "enabled": True,
        }
    ]
    _MemoryStore.data = {
        "schedules": {
            "entry_1": {
                "points": _schedule_points(),
                "mode": "native",
                "effect_windows": effect_windows,
            }
        }
    }
    monkeypatch.setattr(integration, "Store", _MemoryStore)
    hass = _FakeHass(device)

    cached = await _async_schedule_payload(hass, "entry_1")
    refreshed = await _async_schedule_payload(hass, "entry_1", refresh=True)

    assert cached["refresh_ok"] is None
    assert cached["effect_windows"] == effect_windows
    assert refreshed["refresh_ok"] is True
    assert refreshed["fixture"]["professional"][0]["time"] == "08:00"
    device.async_refresh_state.assert_awaited_once()
