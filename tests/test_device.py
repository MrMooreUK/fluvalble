"""Tests for Fluval device schedule and channel behavior."""

import asyncio
from unittest.mock import AsyncMock

from custom_components.fluvalble.core.device import (
    AQUASKY_NUMBERS,
    CHANNEL_NAMES,
    Device,
    NUMBERS,
)


def _make_device(name="AquaSky3.0_Test", model="AquaSky Bluetooth LED"):
    return Device(
        name,
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": model,
        },
    )


def test_initial_values_include_all_channels():
    device = _make_device()

    assert device.connected is False
    for channel in NUMBERS:
        assert device.values[channel] == 0
    assert device.values["mode"] == "manual"
    assert device.values["led_on_off"] is False


def test_aquasky_exposes_four_color_channels():
    device = _make_device()

    assert device.numbers() == AQUASKY_NUMBERS
    assert CHANNEL_NAMES["channel_5"] == "Violet"


def test_schedule_points_are_normalized_from_color_names():
    device = _make_device()

    points = device._normalize_schedule_points(
        [
            {"time": "11:00", "red": 10, "green": 20, "blue": 30, "white": 40},
            {"time": "10:00", "red": 0, "green": 0, "blue": 0, "white": 0},
        ]
    )

    assert [point["time"] for point in points] == ["10:00", "11:00"]
    assert points[1]["channel_1"] == 10
    assert points[1]["channel_4"] == 40


def test_schedule_interpolation_ramps_between_points():
    device = _make_device()
    points = device._normalize_schedule_points(
        [
            {"time": "10:00", "red": 0, "green": 0, "blue": 0, "white": 0},
            {"time": "11:00", "red": 10, "green": 20, "blue": 30, "white": 40},
        ]
    )

    channels = device._interpolate_schedule(points, 10 * 60 + 30)

    assert channels["channel_1"] == 5
    assert channels["channel_2"] == 10
    assert channels["channel_3"] == 15
    assert channels["channel_4"] == 20


def test_set_channels_skips_unchanged_targets_before_ble_connect():
    asyncio.run(_async_test_set_channels_skips_unchanged_targets_before_ble_connect())


async def _async_test_set_channels_skips_unchanged_targets_before_ble_connect():
    device = _make_device()
    device.values.update(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
        }
    )
    device._async_prepare_command = AsyncMock()

    assert await device.async_set_channels(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
        }
    )
    device._async_prepare_command.assert_not_called()


def test_set_channels_switches_to_manual_before_write():
    asyncio.run(_async_test_set_channels_switches_to_manual_before_write())


async def _async_test_set_channels_switches_to_manual_before_write():
    device = _make_device()
    device.values["mode"] = "automatic"
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    device._async_send_channel_state = AsyncMock(return_value=True)

    assert await device.async_set_channels({"channel_1": 25})

    assert device.values["mode"] == "manual"
    device._async_send_packet.assert_called_once()
    device._async_send_channel_state.assert_called_once()
