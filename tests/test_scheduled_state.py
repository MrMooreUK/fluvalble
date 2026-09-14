"""APK-derived scheduled output is presentation, never a controller write."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.fluvalble.core.device import Device
from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.scheduled_state import interpolate_levels, weather_may_be_active
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


@pytest.mark.parametrize("count", [4, 5])
@pytest.mark.parametrize("shift", [0, 360, 900, 1380])
@pytest.mark.parametrize("sleep", [False, True])
def test_full_day_matches_apk_auto_segment_walk(count, shift, sleep):
    # Independent transcription of AutoFragment.getBright's segment walk:
    # no sorting, explicit midnight branch, separate rising/falling arithmetic.
    day = tuple([100, 1, 37, 0, 63][:count])
    night = tuple([1, 0, 2, 0, 4][:count])
    points = [(480, (0,) * count if sleep else night), (541, day), (1140, day), (1207, night)]
    if sleep:
        points.extend([(1320, night), (1320, (0,) * count)])
    points = [((minute + shift) % 1440, levels) for minute, levels in points]
    for minute in range(1440):
        expected = [0] * count
        for index, (start, levels) in enumerate(points):
            end, next_levels = points[(index + 1) % len(points)]
            if end >= start:
                if not start <= minute < end:
                    continue
                duration, elapsed = end - start, minute - start
            else:
                if minute < start and minute >= end:
                    continue
                duration = 1440 - start + end
                elapsed = minute - start if minute >= start else 1440 - start + minute
            for channel, (low, high) in enumerate(zip(levels, next_levels, strict=True)):
                delta = abs(high - low) * 10 * elapsed // duration
                expected[channel] = low * 10 + (delta if high >= low else -delta)
        assert interpolate_levels(points, minute) == tuple(expected), (minute, points)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [4, 5])
@pytest.mark.parametrize("mode", ["automatic", "professional"])
async def test_explicit_off_does_not_require_schedule_or_clock(count, mode):
    device = device_with_schedule(count)
    device.values["mode"] = mode
    device.diagnostics.pop("clock_synced_at")
    device._reported_schedule_points.clear()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    assert device.expected_scheduled_on(at(12)) is None
    assert await device.async_set_switch("led_on_off", False)
    assert device.expected_scheduled_on(at(12)) is False
    # On releases the override; it cannot manufacture missing schedule data.
    assert await device.async_set_switch("led_on_off", True)
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
@pytest.mark.parametrize("count", [4, 5])
@pytest.mark.parametrize("mode", ["automatic", "professional"])
@pytest.mark.parametrize("manual_level", [0, 50])
async def test_plain_turn_on_in_schedule_does_not_rewrite_manual_channels(count, mode, manual_level):
    device = device_with_schedule(count)
    device.values["mode"] = mode
    for channel in device.numbers():
        device.values[channel] = manual_level
    device._scheduled_power_off = True
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    device.async_apply_light_channels = AsyncMock(return_value=True)
    entity = FluvalLight(device, "light")
    await entity.async_turn_on()
    device.async_apply_light_channels.assert_not_awaited()
    device._async_send_packet.assert_awaited_once_with(protocol.old_switch_packet(True))
    assert device.values["mode"] == mode
    assert device._scheduled_power_off is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["automatic", "professional"])
async def test_failed_plain_scheduled_turn_on_preserves_off_override(mode):
    device = device_with_schedule()
    device.values["mode"] = mode
    device._scheduled_power_off = True
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=False)
    device.async_apply_light_channels = AsyncMock(return_value=True)
    entity = FluvalLight(device, "light")
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await entity.async_turn_on()
    assert device._scheduled_power_off is True
    assert device.values["mode"] == mode
    device.async_apply_light_channels.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [False, True])
@pytest.mark.parametrize("send_ok", [False, True])
@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
async def test_power_write_preserves_reconnect_readback_and_notifies_final_state(requested, send_ok, transport):
    device = device_with_schedule()
    device.client = SimpleNamespace(
        command_write_uuid="facebd" if transport == "facebd" else "00001001",
        wifi_facebd=transport == "facebd",
        spp_transport=transport == "spp",
    )
    device.values["led_on_off"] = requested

    async def prepare():
        # A fresh connection reports newer fixture state than the idle cache.
        device.values.update(mode="manual", led_on_off=not requested, channel_1=37)
        return True

    device._async_prepare_command = AsyncMock(side_effect=prepare)
    device._async_send_packet = AsyncMock(return_value=send_ok)
    observed = []
    device.updates_component.append(lambda: observed.append(dict(device.values)))
    assert await device.async_set_switch("led_on_off", requested) is send_ok
    assert device.values["mode"] == "manual"
    assert device.values["channel_1"] == 37
    assert device.values["led_on_off"] is (requested if send_ok else not requested)
    if send_ok:
        assert observed[-1]["led_on_off"] is requested
    builder = {
        "classic": protocol.old_switch_packet,
        "facebd": protocol.wifi_switch_packet,
        "spp": protocol.spp_switch_packet,
    }[transport]
    device._async_send_packet.assert_awaited_once_with(builder(requested))


@pytest.mark.asyncio
async def test_power_prepare_failure_keeps_new_readback():
    device = device_with_schedule()

    async def prepare():
        device.values.update(mode="manual", led_on_off=True, channel_1=37)
        return False

    device._async_prepare_command = AsyncMock(side_effect=prepare)
    device._async_send_packet = AsyncMock()
    assert not await device.async_set_switch("led_on_off", False)
    assert device.values["mode"] == "manual"
    assert device.values["led_on_off"] is True
    assert device.values["channel_1"] == 37
    device._async_send_packet.assert_not_awaited()


@pytest.mark.asyncio
async def test_power_notification_includes_scheduled_override():
    device = device_with_schedule()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    observed = []
    device.updates_component.append(lambda: observed.append(device.expected_scheduled_on(at(12))))
    assert await device.async_set_switch("led_on_off", False)
    assert observed[-1] is False
    assert await device.async_set_switch("led_on_off", True)
    assert observed[-1] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
@pytest.mark.parametrize("send_ok", [False, True])
async def test_mode_write_keeps_verification_readback(transport, send_ok):
    device = device_with_schedule()
    device.client = SimpleNamespace(
        command_write_uuid="facebd" if transport == "facebd" else "00001001",
        wifi_facebd=transport == "facebd",
        spp_transport=transport == "spp",
        request_state=AsyncMock(return_value=False),
    )
    device._async_prepare_command = AsyncMock(return_value=True)

    async def send(_packet):
        device.values.update(mode="manual", channel_1=37)
        return send_ok

    device._async_send_packet = AsyncMock(side_effect=send)
    observed = []
    device.updates_component.append(lambda: observed.append(device.values["mode"]))
    assert await device.async_select_option("mode", "professional") is send_ok
    assert device.values["channel_1"] == 37
    assert device.values["mode"] == ("professional" if send_ok else "manual")
    if send_ok:
        assert observed[-1] == "professional"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
@pytest.mark.parametrize("field", ["mode", "led_on_off"])
@pytest.mark.parametrize("send_ok", [False, True])
async def test_reported_control_state_wins_over_requested_state(transport, field, send_ok):
    device = device_with_schedule()
    device.values.update(mode="manual", led_on_off=False)
    device.client = SimpleNamespace(
        command_write_uuid="facebd" if transport == "facebd" else "00001001",
        wifi_facebd=transport == "facebd",
        spp_transport=transport == "spp",
        request_state=AsyncMock(return_value=False),
    )
    device._async_prepare_command = AsyncMock(return_value=True)

    async def send(_packet):
        if transport == "classic":
            body = bytes([0, 0, 0] + [0] * 10 + [0] * 20)
            assert device.decode_update_packet(protocol.old_packet(protocol.OLD_READ_PARAMS + body))
        elif transport == "facebd":
            device._decode_wifi_update({protocol.WIFI_MODE_KEY: 0, protocol.WIFI_SWITCH_KEY: False})
        else:
            device._decode_spp_update({protocol.SPP_MODE_KEY: 0, protocol.SPP_SWITCH_KEY: False})
        return send_ok

    device._async_send_packet = AsyncMock(side_effect=send)
    if field == "mode":
        assert await device.async_select_option(field, "professional") is send_ok
    else:
        assert await device.async_set_switch(field, True) is send_ok
    assert device.values["mode"] == "manual"
    assert device.values["led_on_off"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
async def test_light_off_preserves_actual_on_readback_and_effect(transport):
    device = device_with_schedule(4)
    device.values.update(mode="manual", led_on_off=True, effect="Sun")
    device.client = SimpleNamespace(
        command_write_uuid="facebd" if transport == "facebd" else "00001001",
        wifi_facebd=transport == "facebd",
        spp_transport=transport == "spp",
    )
    device._async_prepare_command = AsyncMock(return_value=True)

    async def send(_packet):
        if transport == "classic":
            body = bytes([0, 1, 1] + [0] * 8 + [0] * 16)
            assert device.decode_update_packet(protocol.old_packet(protocol.OLD_READ_PARAMS + body))
        elif transport == "facebd":
            device._decode_wifi_update({protocol.WIFI_SWITCH_KEY: True})
        else:
            device._decode_spp_update({protocol.SPP_SWITCH_KEY: True})
        return True

    device._async_send_packet = AsyncMock(side_effect=send)
    entity = FluvalLight(device, "light")
    await entity.async_turn_off()
    assert device.values["led_on_off"] is True
    assert device.values["effect"]
    assert entity._attr_is_on is True


@pytest.mark.asyncio
async def test_manual_read_and_mode_return_keep_schedule_weather_consistent():
    device = device_with_schedule(4)
    manual = bytes([0, 1, 0] + [0] * 8 + [0] * 16)
    assert device.decode_update_packet(protocol.old_packet(protocol.OLD_READ_PARAMS + manual))
    assert not device._reported_schedule_points
    body = bytes([1, 8, 0, 9, 0] + [100] * 4 + [19, 0, 20, 0] + [0] * 4 + [255, 12, 0, 13, 0, 1])

    async def read():
        return device.decode_update_packet(protocol.old_packet(protocol.OLD_READ_PARAMS + body))

    device.client = SimpleNamespace(command_write_uuid="00001001", request_state=AsyncMock(side_effect=read))
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    assert await device.async_select_option("mode", "automatic")
    assert device.expected_scheduled_on(at(12)) is None
    assert device.expected_scheduled_on(at(13)) is True
    assert device.values["native_effect_schedule"][0]["enabled"] is True


@pytest.mark.parametrize(
    "hour,minute,active", [(12, 0, False), (19, 59, False), (20, 0, True), (20, 4, True), (20, 5, False)]
)
def test_weather_only_withholds_during_its_window(hour, minute, active):
    device = device_with_schedule()
    device.values["native_effect_schedule"] = [
        {"enabled": True, "start": "20:00", "end": "20:05", "weekdays": [True] * 7}
    ]
    assert device.expected_scheduled_on(at(hour, minute)) is (None if active else True)


def test_weather_weekdays_and_midnight_boundaries():
    windows = [
        {
            "enabled": True,
            "start": "23:00",
            "end": "01:00",
            "weekdays": [True, False, False, False, False, False, False],
        }
    ]
    assert weather_may_be_active(windows, datetime(2026, 9, 7, 23, 0))
    assert weather_may_be_active(windows, datetime(2026, 9, 8, 0, 59))
    assert not weather_may_be_active(windows, datetime(2026, 9, 8, 1, 0))
    assert not weather_may_be_active(windows, datetime(2026, 9, 8, 23, 0))
    assert not weather_may_be_active(windows, datetime(2026, 9, 7, 0, 30))


@pytest.mark.asyncio
async def test_successful_off_survives_schedule_ticks_and_failed_on():
    device = prepare_readback("automatic", level=100)
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


def prepare_readback(mode, *, read=True, level=0):
    device = device_with_schedule()
    device.values["mode"] = mode
    points = [{"minute": minute, **{f"channel_{i}": 100 for i in range(1, 6)}} for minute in (0, 480, 960, 1200)]
    if mode == "professional":
        device._record_native_schedule_readback(protocol_name="classic", professional=points)
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)

    async def readback():
        if not read:
            return False
        if mode == "automatic":
            body = bytes([1, 8, 0, 9, 0] + [level] * 5 + [19, 0, 20, 0] + [0] * 5)
        else:
            body = bytes([2, 4] + [value for hour in (0, 8, 16, 20) for value in [hour, 0] + [level] * 5])
        return device.decode_update_packet(protocol.old_packet(protocol.OLD_READ_PARAMS + body))

    device.client = SimpleNamespace(
        command_write_uuid="00001001-0000-1000-8000-00805f9b34fb",
        wifi_facebd=False,
        spp_transport=False,
        plant_pro_spp=False,
        request_state=AsyncMock(side_effect=readback),
    )

    return device


@pytest.mark.asyncio
async def test_newer_schedule_projection_refresh_does_not_read_or_notify():
    device = prepare_readback("automatic")
    update = MagicMock()
    device.updates_component.append(update)
    await device._async_read_schedule_projection("facebd")
    await device._async_read_schedule_projection("spp")
    device.client.request_state.assert_not_awaited()
    update.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["automatic", "professional"])
async def test_entering_scheduled_mode_fetches_missing_readback(mode):
    device = prepare_readback(mode, level=100)
    device.values["mode"] = "manual"
    device._reported_schedule_points.clear()

    async def prepare():
        # A connection-initialization read can report the previous mode.
        device.values["mode"] = "manual"
        return True

    device._async_prepare_command.side_effect = prepare
    assert await device.async_select_option("mode", mode)
    device.client.request_state.assert_awaited_once()
    assert device.values["mode"] == mode
    assert device.expected_scheduled_on(at(12)) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["automatic", "professional"])
async def test_failed_mode_read_never_reuses_inactive_forecast(mode):
    device = prepare_readback(mode, read=False)
    assert device.expected_scheduled_on(at(12)) is True
    device.values["mode"] = "manual"
    assert await device.async_select_option("mode", mode)
    assert device.expected_scheduled_on(at(12)) is None
    assert not device._reported_schedule_points


def test_incomplete_schedule_does_not_reuse_manual_state():
    device = device_with_schedule()
    device.values["led_on_off"] = True
    device._reported_schedule_points.clear()
    assert device.expected_scheduled_on(at(12)) is None
