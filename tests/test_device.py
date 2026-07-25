"""Tests for Fluval device schedule and channel behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.fluvalble.core import protocol
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


def test_home_assistant_selects_connectable_esphome_route(monkeypatch):
    asyncio.run(_async_test_home_assistant_selects_connectable_esphome_route(monkeypatch))


async def _async_test_home_assistant_selects_connectable_esphome_route(
    monkeypatch,
):
    from homeassistant.components import bluetooth

    proxy = SimpleNamespace(
        address="AA:BB:CC:DD:EE:FF",
        name="AquaSky3.0_Test",
        details={"source": "fluvalble-proxy"},
    )
    monkeypatch.setattr(
        bluetooth,
        "async_ble_device_from_address",
        MagicMock(return_value=proxy),
    )
    device = Device(
        "AquaSky3.0_Test",
        hass=MagicMock(),
        config_data={
            "mac": proxy.address,
            "model": "AquaSky Bluetooth LED",
        },
    )

    assert device._connectable_ble_device() is proxy
    assert await device._async_find_device() is proxy
    bluetooth.async_ble_device_from_address.assert_called_with(
        device.hass,
        proxy.address,
        connectable=True,
    )


def test_aquasky_facebd_packet_excludes_violet_channel():
    device = _make_device()
    device.values.update(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
            "channel_5": 50,
        }
    )
    device.client = MagicMock(raw_facebd=True)

    packet = protocol.wifi_all_zone_packet(device._channel_values())
    expected = device._expected_state_for_packet(packet)

    assert device._channel_values() == [10, 20, 30, 40]
    assert expected == {
        protocol.WIFI_CHANNEL_KEYS[0]: 10,
        protocol.WIFI_CHANNEL_KEYS[1]: 20,
        protocol.WIFI_CHANNEL_KEYS[2]: 30,
        protocol.WIFI_CHANNEL_KEYS[3]: 40,
    }
    assert protocol.WIFI_CHANNEL_KEYS[4] not in expected


def test_led_channel_test_verifies_each_channel_and_restores_state(monkeypatch):
    asyncio.run(_async_test_led_channel_test_verifies_each_channel_and_restores_state(monkeypatch))


async def _async_test_led_channel_test_verifies_each_channel_and_restores_state(
    monkeypatch,
):
    import custom_components.fluvalble.core.device as device_module

    device = _make_device()
    device.values.update(
        {
            "channel_1": 8,
            "channel_2": 7,
            "channel_3": 6,
            "channel_4": 5,
            "led_on_off": False,
        }
    )
    device.client = MagicMock(
        last_write_verified=True,
        last_confirmed_state={protocol.WIFI_SWITCH_KEY: True},
        last_verification_mismatches={},
    )
    device.async_set_switch = AsyncMock(return_value=True)
    device.async_set_channels = AsyncMock(return_value=True)
    monkeypatch.setattr(device_module, "CHANNEL_TEST_HOLD_SECONDS", 0)

    assert await device.async_test_led_channels()

    assert [result["channel"] for result in device.diagnostics["channel_test_results"]] == [
        "Power",
        "Red",
        "Green",
        "Blue",
        "White",
    ]
    assert device.diagnostics["status"] == "channel_test_passed"
    assert device.diagnostics["channel_test_restore_ok"] is True
    assert device.channel_test_active is False
    assert device.async_set_channels.await_count == 5
    device.async_set_channels.assert_awaited_with(
        {
            "channel_1": 8,
            "channel_2": 7,
            "channel_3": 6,
            "channel_4": 5,
        },
        force=True,
    )
    assert device.async_set_switch.await_count == 2
