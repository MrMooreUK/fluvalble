"""APK-derived scheduled output is presentation, never a controller write."""

from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.fluvalble.core.device import Device
from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.scheduled_state import interpolate_levels
from custom_components.fluvalble.light import FluvalLight


def device_with_schedule(count=5, *, sleep=True):
    device = Device("Plant", config_data={"mac": "AA:BB:CC:DD:EE:FF", "product_id": 305 if count == 5 else 328})
    device.connected = True
    device.values["mode"] = "automatic"
    device.diagnostics["clock_synced_at"] = datetime.now(UTC).isoformat()
    schedule = {
        "sunrise": {"hour": 8, "minute": 0, "ramp": 60},
        "sunset": {"hour": 20, "minute": 0, "ramp": 60},
        "day_levels": [100] * count,
        "night_levels": [5] * count,
        "sleep": {"hour": 22, "minute": 0} if sleep else None,
    }
    device._record_native_schedule_readback(protocol_name="classic", auto=schedule)
    return device


def at(hour, minute=0):
    return datetime(2026, 9, 8, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize("count", [4, 5])
@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (0, 0, False),
        (7, 59, False),
        (8, 0, False),
        (8, 1, True),
        (12, 0, True),
        (21, 59, True),
        (22, 0, False),
        (23, 59, False),
    ],
)
def test_auto_day_ramp_and_sleep(count, hour, minute, expected):
    device = device_with_schedule(count)
    before = deepcopy(device.values)
    assert device.expected_scheduled_on(at(hour, minute)) is expected
    assert device.values == before


def test_night_levels_without_sleep_remain_on():
    device = device_with_schedule(sleep=False)
    assert device.expected_scheduled_on(at(2)) is True


@pytest.mark.parametrize("count", [4, 5])
def test_pro_sort_and_midnight_wrap(count):
    device = device_with_schedule(count)
    device.values["mode"] = "professional"
    points = [
        {"minute": minute, **{f"channel_{i + 1}": value for i in range(count)}}
        for minute, value in [(1200, 100), (120, 0), (1080, 0), (60, 100)]
    ]
    device._record_native_schedule_readback(protocol_name="classic", professional=points)
    assert device.expected_scheduled_on(at(0)) is True
    assert device.expected_scheduled_on(at(2)) is False
    assert device.expected_scheduled_on(at(19)) is True


def test_tenths_and_java_descending_truncation():
    points = [(0, (0, 0, 0, 0)), (60, (1, 0, 0, 0)), (120, (0, 0, 0, 0))]
    assert interpolate_levels(points, 6) == (1, 0, 0, 0)
    assert interpolate_levels(points, 119) == (1, 0, 0, 0)
    assert interpolate_levels(points, 120) == (0, 0, 0, 0)


def test_equal_time_steps_select_last_point():
    points = [(480, (0,) * 4), (480, (100,) * 4), (1200, (100,) * 4), (1200, (0,) * 4)]
    assert interpolate_levels(points, 479) == (0,) * 4
    assert interpolate_levels(points, 480) == (1000,) * 4
    assert interpolate_levels(points, 1200) == (0,) * 4
    assert interpolate_levels([(0, (0,) * 4), (0, (100,) * 4)], 0) is None


def test_readback_is_immutable_and_clock_survives_idle_disconnect():
    device = device_with_schedule()
    device.values["native_auto_schedule"]["day_levels"][:] = [0] * 5
    device.connected = False
    device._clock_synced = False
    assert device.expected_scheduled_on(at(12)) is True
    device.diagnostics.pop("clock_synced_at")
    assert device.expected_scheduled_on(at(12)) is None


def test_incomplete_and_preview_do_not_reuse_manual_state():
    device = device_with_schedule()
    device.values["led_on_off"] = True
    device._reported_schedule_points.clear()
    assert device.expected_scheduled_on(at(12)) is None
    device = device_with_schedule()
    device.native_preview_active = True
    assert device.expected_scheduled_on(at(12)) is None


@pytest.mark.parametrize("count", [4, 5])
def test_actual_classic_response_populates_projection_and_invalid_read_clears_it(count):
    device = device_with_schedule(count)
    body = bytes([1, 8, 0, 9, 0] + [100] * count + [19, 0, 20, 0] + [0] * count)
    assert device.decode_update_packet(protocol.old_packet(protocol.OLD_READ_PARAMS + body))
    assert device.expected_scheduled_on(at(12)) is True
    assert device.expected_scheduled_on(at(21)) is False
    # Valid framing but an invalid schedule time must not retain old forecast.
    invalid = bytes([1, 25, 0, 9, 0] + [100] * count + [19, 0, 20, 0] + [0] * count)
    assert device.decode_update_packet(protocol.old_packet(protocol.OLD_READ_PARAMS + invalid))
    assert device.expected_scheduled_on(at(12)) is None


def test_enabled_weather_overlay_does_not_misreport_static_output():
    device = device_with_schedule()
    device.values["native_effect_schedule"] = [{"enabled": True}]
    assert device.expected_scheduled_on(at(12)) is None
    device.values["native_effect_schedule"] = [{"enabled": False}]
    assert device.expected_scheduled_on(at(12)) is True


@pytest.mark.asyncio
async def test_entity_tick_updates_only_display_and_unload_cancels():
    device = device_with_schedule()
    device._async_send_packet = AsyncMock()
    entity = FluvalLight(device, "light")
    cancel = MagicMock()
    with patch("custom_components.fluvalble.light.async_track_time_interval", return_value=cancel) as track:
        await entity.async_added_to_hass()
        assert track.call_args.args[2].total_seconds() == 30
    with patch.object(device, "expected_scheduled_on", return_value=False):
        await entity._async_schedule_tick(at(22))
        assert entity._attr_is_on is False
    with patch.object(device, "expected_scheduled_on", return_value=True):
        await entity._async_schedule_tick(at(12))
        assert entity._attr_is_on is True
        assert entity._attr_assumed_state is True
        assert entity._attr_brightness is None
        assert entity._attr_rgb_color is None
    device._async_send_packet.assert_not_called()
    await entity.async_will_remove_from_hass()
    cancel.assert_called_once()
    assert entity._update_handler not in device.updates_component


def test_manual_and_new_transport_keep_existing_reporting():
    device = device_with_schedule()
    entity = FluvalLight(device, "light")
    device.values.update(mode="manual", led_on_off=True)
    entity.internal_update()
    assert entity._attr_is_on is True
    assert entity._attr_assumed_state is False
    device.values["mode"] = "automatic"
    device.facebd = True
    entity.internal_update()
    assert entity._attr_assumed_state is False


@pytest.mark.asyncio
async def test_successful_off_survives_schedule_ticks_and_failed_on():
    device = device_with_schedule()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    assert await device.async_set_switch("led_on_off", False)
    assert device.expected_scheduled_on(at(12)) is False
    device._async_send_packet.return_value = False
    assert not await device.async_set_switch("led_on_off", True)
    assert device.expected_scheduled_on(at(12)) is False
    device._async_send_packet.return_value = True
    assert await device.async_select_option("mode", "automatic")
    assert device.expected_scheduled_on(at(12)) is True
