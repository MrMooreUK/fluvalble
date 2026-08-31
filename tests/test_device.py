"""Tests for Fluval device schedule and channel behavior."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.fluvalble.core import (
    LAMP_PROFILE_AQUASKY3,
    LAMP_PROFILE_PLANT,
)
from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.device import (
    AQUASKY_NUMBERS,
    CHANNEL_NAMES_PLANT,
    CHANNEL_NAMES_PLANT_PRO,
    Device,
    NUMBERS,
    REACHABLE_SECONDS,
)
from custom_components.fluvalble.core.effects import PLANT_PRO_EFFECTS, WEATHER_EFFECTS


def _make_device(name="AquaSky3.0_Test", model="AquaSky Bluetooth LED", **config):
    return Device(
        name,
        config_data={
            "mac": "AA:BB:CC:DD:EE:FF",
            "model": model,
            **config,
        },
    )


def test_connection_attribute_uses_recent_activity_or_live_gatt():
    device = _make_device()
    device.connected = False
    device.conn_info["last_seen"] = datetime.now(UTC)

    assert device.is_reachable() is True
    assert device.attribute("connection")["is_on"] is True
    assert device.attribute("connection")["extra"]["gatt_connected"] is False

    device.conn_info["last_seen"] = datetime.now(UTC) - timedelta(seconds=REACHABLE_SECONDS + 1)
    assert device.is_reachable() is False
    assert device.attribute("connection")["is_on"] is False

    device.connected = True
    assert device.is_reachable() is True
    assert device.attribute("connection")["extra"]["gatt_connected"] is True


def test_reachability_expiry_notifies_connection_entities():
    device = _make_device()
    handler = MagicMock()
    device.register_update("connection", handler)
    device.conn_info["last_seen"] = datetime.now(UTC) - timedelta(seconds=REACHABLE_SECONDS + 1)

    device._on_reachability_expired(datetime.now(UTC))

    handler.assert_called_once()
    assert device.attribute("connection")["is_on"] is False


def test_cancel_reachability_refresh_releases_timer():
    device = _make_device()
    cancel = MagicMock()
    device._reachability_unsub = cancel

    device.cancel_reachability_refresh()

    cancel.assert_called_once()
    assert device._reachability_unsub is None


def test_activity_updates_last_seen_and_schedules_expiry(monkeypatch):
    import custom_components.fluvalble.core.device as device_module

    device = _make_device()
    device.hass = MagicMock()
    cancel = MagicMock()
    track = MagicMock(return_value=cancel)
    monkeypatch.setattr(device_module, "async_track_point_in_time", track)

    device.touch_seen(rssi=-64)

    assert device.conn_info["rssi"] == -64
    assert device.conn_info["rssi_updated_at"] == device.conn_info["last_seen"]
    track.assert_called_once()
    assert device._reachability_unsub is cancel


def test_expected_disconnect_remains_reachable_after_successful_connect():
    device = _make_device()

    device.set_connected(True)
    connected_at = device.conn_info["last_seen"]
    device.set_connected(False)

    assert connected_at <= device.conn_info["last_seen"]
    assert device.is_reachable() is True


def _facebd_client():
    return SimpleNamespace(
        raw_facebd=True,
        command_write_uuid="facebd03-7261-6262-6974-696f74626c65",
    )


def test_initial_values_include_all_channels():
    device = _make_device()

    assert device.connected is False
    for channel in NUMBERS:
        assert device.values[channel] == 0
    assert device.values["mode"] == "manual"
    assert device.values["led_on_off"] is False
    assert device.values["effect"] is None


def test_classic_effects_require_positive_transport_evidence():
    unknown = _make_device()
    classic = _make_device(service_uuids=["00001002-0000-1000-8000-00805f9b34fb"])
    facebd = _make_device(service_uuids=["facebd00-0000-1000-8000-00805f9b34fb"])

    assert unknown.effect_list() == []
    assert classic.effect_list() == ["None", *WEATHER_EFFECTS]
    assert facebd.effect_list() == []


def test_plant_pro_identity_exposes_only_plant_pro_effects():
    device = _make_device(name="PlantPro_AABBCC", model="Plant Pro 4.0 Bluetooth LED")

    assert device.effect_list() == ["None", *PLANT_PRO_EFFECTS]


def test_native_weather_effect_uses_apk_packet():
    asyncio.run(_async_test_native_weather_effect_uses_apk_packet())


async def _async_test_native_weather_effect_uses_apk_packet():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    device.client = SimpleNamespace(command_write_uuid="00001001-0000-1000-8000-00805f9b34fb")
    device.values.update(
        {
            "channel_1": 10,
            "channel_2": 20,
            "channel_3": 30,
            "channel_4": 40,
            "mode": "automatic",
            "led_on_off": False,
        }
    )
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)

    assert await device.async_set_effect("Lightning")

    assert [call.args[0] for call in device._async_send_packet.await_args_list] == [
        protocol.old_mode_packet(0),
        protocol.old_switch_packet(True),
        protocol.old_weather_effect_packet(2),
    ]
    assert device.values["effect"] == "Lightning"
    assert device.values["led_on_off"] is True
    assert device.values["mode"] == "manual"
    assert device._effect_restore_channels == {
        "channel_1": 10,
        "channel_2": 20,
        "channel_3": 30,
        "channel_4": 40,
    }


def test_plant_pro_native_effect_uses_key_14_packet():
    asyncio.run(_async_test_plant_pro_native_effect_uses_key_14_packet())


async def _async_test_plant_pro_native_effect_uses_key_14_packet():
    device = _make_device(name="PlantPro_AABBCC", model="Plant Pro 4.0 Bluetooth LED")
    device.client = SimpleNamespace(
        plant_pro_spp=True,
        command_write_uuid="0000fff2-0000-1000-8000-00805f9b34fb",
    )
    device.values.update({"mode": "automatic", "led_on_off": False})
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)

    assert await device.async_set_effect("Sun and lightning")
    assert [call.args[0] for call in device._async_send_packet.await_args_list] == [
        protocol.spp_mode_packet(0),
        protocol.spp_switch_packet(True),
        protocol.spp_effect_packet(3),
    ]
    assert device.values["effect"] == "Sun and lightning"


def test_native_weather_effect_rejects_nonclassic_transport():
    asyncio.run(_async_test_native_weather_effect_rejects_nonclassic_transport())


async def _async_test_native_weather_effect_rejects_nonclassic_transport():
    device = _make_device()
    device.client = SimpleNamespace(command_write_uuid="facebd80-0000-1000-8000-00805f9b34fb")
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)

    assert not await device.async_set_effect("Lightning")
    device._async_send_packet.assert_not_awaited()
    assert device.values["effect"] is None


def test_stopping_effect_forces_static_channel_restore():
    asyncio.run(_async_test_stopping_effect_forces_static_channel_restore())


async def _async_test_stopping_effect_forces_static_channel_restore():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    restore = {
        "channel_1": 10,
        "channel_2": 20,
        "channel_3": 30,
        "channel_4": 40,
    }
    device.values.update(restore)
    device.values["effect"] = "Lightning"
    device._effect_restore_channels = dict(restore)
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_channel_state = AsyncMock(return_value=True)

    assert await device.async_stop_effect()

    device._async_send_channel_state.assert_awaited_once()
    assert device._async_send_channel_state.await_args.kwargs["force_power"] is True
    assert device.values["effect"] is None


def test_effect_active_off_sends_only_switch_packet():
    asyncio.run(_async_test_effect_active_off_sends_only_switch_packet())


async def _async_test_effect_active_off_sends_only_switch_packet():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    device.values["led_on_off"] = True
    device.values["effect"] = "Lightning"
    device._effect_restore_channels = device._channel_snapshot()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)

    assert await device.async_set_switch("led_on_off", False)

    device._async_send_packet.assert_awaited_once_with(protocol.old_switch_packet(False))
    assert device.values["led_on_off"] is False
    assert device.values["effect"] is None


def test_aquasky_2_exposes_four_color_channels():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")

    assert device.numbers() == AQUASKY_NUMBERS


def test_aquasky_3_name_exposes_four_rgbw_channels():
    device = _make_device(name="AquaSky3.0_2F3176", model="AquaSky 3.0 Bluetooth LED")

    assert device.numbers() == AQUASKY_NUMBERS


def test_aquasky_3_profile_exposes_four_rgbw_channels():
    device = _make_device(lamp_profile=LAMP_PROFILE_AQUASKY3)

    assert device.numbers() == AQUASKY_NUMBERS


def test_plant_profile_exposes_five_channels_with_plant_labels():
    device = _make_device(
        name="Fish Tank",
        model="Unknown Bluetooth LED",
        lamp_profile=LAMP_PROFILE_PLANT,
    )

    assert device.numbers() == NUMBERS
    assert device.entity_name("channel_1") == CHANNEL_NAMES_PLANT["channel_1"]
    assert device.entity_name("channel_5") == CHANNEL_NAMES_PLANT["channel_5"]


def test_plant_name_exposes_five_channels():
    device = _make_device(name="Plant 3.0_AABB", model="Plant 3.0 Bluetooth LED")

    assert device.numbers() == NUMBERS
    assert device.entity_name("channel_3") == "Cold White"


def test_plant_pro_exposes_five_channel_rgb_spectrum_with_reference_labels():
    device = _make_device(
        name="PlantPro_AABBCC",
        model="Plant Pro 4.0 Bluetooth LED",
    )

    assert device.numbers() == NUMBERS
    assert device.light_mode() == "rgb"
    assert device.entity_name("channel_1") == CHANNEL_NAMES_PLANT_PRO["channel_1"]
    assert device.entity_name("channel_5") == CHANNEL_NAMES_PLANT_PRO["channel_5"]


def test_aquasky_uses_rgbw_and_maps_channels_at_requested_brightness():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")

    assert device.light_mode() == "rgbw"
    assert device.channels_from_rgbw((0, 255, 128, 0), 128) == {
        "channel_1": 0,
        "channel_2": 50,
        "channel_3": 25,
        "channel_4": 0,
    }


def test_plant_uses_rgb_and_maps_saturated_colours_without_white_channels():
    device = _make_device(name="Plant 3.0_AABB", model="Plant 3.0 Bluetooth LED")

    assert device.light_mode() == "rgb"
    assert device.channels_from_rgb((255, 0, 0), 255) == {
        "channel_1": 100,
        "channel_2": 0,
        "channel_3": 0,
        "channel_4": 0,
        "channel_5": 0,
    }


def test_light_colour_cache_is_used_only_while_physical_channels_match():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    channels = {"channel_1": 0, "channel_2": 50, "channel_3": 0, "channel_4": 0}
    device.values.update(channels)
    device.remember_commanded_light(channels, rgbw=(0, 255, 0, 0), brightness=128)

    assert device.light_rgbw_255() == (0, 255, 0, 0)
    assert device.light_brightness_255() == 128

    device.values["channel_1"] = 50
    assert device.light_rgbw_255() == (255, 255, 0, 0)


def test_apply_light_channels_turns_on_after_channel_write():
    asyncio.run(_async_test_apply_light_channels_turns_on_after_channel_write())


async def _async_test_apply_light_channels_turns_on_after_channel_write():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    device.async_set_channels = AsyncMock(return_value=True)
    device.async_set_switch = AsyncMock(return_value=True)

    values = {"channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40}
    assert await device.async_apply_light_channels(values)

    device.async_set_channels.assert_awaited_once_with(values)
    device.async_set_switch.assert_awaited_once_with("led_on_off", True)


def test_master_brightness_writes_every_scaled_channel():
    asyncio.run(_async_test_master_brightness_writes_every_scaled_channel())


async def _async_test_master_brightness_writes_every_scaled_channel():
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
    device.values.update(
        {
            "channel_1": 20,
            "channel_2": 40,
            "channel_3": 60,
            "channel_4": 80,
        }
    )
    device.async_set_channels = AsyncMock(return_value=True)

    assert await device.async_set_master_brightness(50)

    device.async_set_channels.assert_awaited_once_with(
        {
            "channel_1": 12,
            "channel_2": 25,
            "channel_3": 38,
            "channel_4": 50,
        }
    )


def test_clock_sync_flag_resets_on_disconnect():
    device = _make_device(name="Plant 3.0", model="Plant 3.0 Bluetooth LED")
    device._clock_synced = True
    device.set_connected(False)
    assert device._clock_synced is False


def test_old_status_packet_scales_to_percent():
    device = _make_device(name="Plant 3.0", model="Plant 3.0 Bluetooth LED")
    # Manual mode, on, five channels at 10/20/30/40/50% => wire 100/200/...
    packet = bytearray(
        [
            0x68,
            0x18,
            0x00,
            0x01,
            0x00,
            100 & 0xFF,
            100 >> 8,
            200 & 0xFF,
            200 >> 8,
            300 & 0xFF,
            300 >> 8,
            400 & 0xFF,
            400 >> 8,
            500 & 0xFF,
            500 >> 8,
        ]
    )

    device.decode_update_packet(packet)

    assert device.values["channel_1"] == 10
    assert device.values["channel_2"] == 20
    assert device.values["channel_5"] == 50
    assert device._channel_count_hint == 5


def test_plant_pro_status_packet_updates_power_mode_and_all_channels():
    device = _make_device(
        name="PlantPro_AABBCC",
        model="Plant Pro 4.0 Bluetooth LED",
    )
    status = bytes.fromhex("d2 a7 01 00 02 f5 03 18 64 04 14 05 18 1e 06 18 28 07 18 32")

    assert device.decode_update_packet(status)
    assert device.values["mode"] == "manual"
    assert device.values["led_on_off"] is True
    assert device.values["channel_1"] == 100
    assert device.values["channel_2"] == 20
    assert device.values["channel_5"] == 50
    assert device._channel_count_hint == 5


def test_plant_pro_status_decodes_effect_and_fixture_schedules():
    device = _make_device(name="PlantPro_AABBCC", model="Plant Pro 4.0 Bluetooth LED")
    windows = [
        {
            "start_hour": 12,
            "start_minute": 0,
            "end_hour": 12,
            "end_minute": 10,
            "effect_id": 1,
            "weekdays": [True] * 7,
            "enabled": True,
        }
    ]
    auto = {
        "sunrise": (8, 0, 60),
        "sunset": (20, 30, 45),
        "sleep": (23, 15),
        "day_levels": [80, 70, 60, 50, 40],
        "night_levels": [0, 5, 0, 0, 0],
    }
    points = [
        {"hour": 8, "minute": 0, "levels": [0, 0, 0, 0, 0]},
        {"hour": 10, "minute": 0, "levels": [20, 20, 20, 20, 20]},
        {"hour": 12, "minute": 30, "levels": [80, 70, 60, 50, 40]},
        {"hour": 20, "minute": 0, "levels": [0, 0, 0, 0, 0]},
    ]
    status_map = protocol.decode_cbor_update(protocol.spp_effect_schedule_packet(windows))
    status_map.update(protocol.decode_cbor_update(protocol.spp_auto_schedule_packet(**auto)))
    status_map.update(protocol.decode_cbor_update(protocol.spp_pro_schedule_packet(points)))
    status_map[protocol.SPP_EFFECT_KEY] = 4
    status = bytes((protocol.SPP_STATUS_HEADER,)) + protocol.cbor_map(status_map)

    assert device.decode_update_packet(status)
    assert device.values["effect"] == "Colour cycle"
    assert device.values["native_auto_schedule"]["sunrise"] == "08:00"
    assert device.values["native_pro_schedule"][2]["time"] == "12:30"
    assert device.diagnostics["native_schedule_protocol"] == "plant_pro"
    assert device.diagnostics["native_schedule_readback_at"]
    assert device.diagnostics["plant_pro_effect_schedule"][0]["effect"] == "Thunderstorm"


def test_facebd_schedule_readback_is_recorded_for_dashboard():
    device = _make_device(name="AquaSky3.0_Test", model="AquaSky 3.0 Bluetooth LED")
    points = [
        {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
        {"minute": 600, "channel_1": 5, "channel_2": 6, "channel_3": 7, "channel_4": 8},
        {"minute": 1200, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
        {"minute": 1320, "channel_1": 0, "channel_2": 0, "channel_3": 0, "channel_4": 0},
    ]
    data = protocol.decode_cbor_map(protocol.wifi_pro_schedule_packet(points))

    assert device._decode_wifi_update(data)
    assert device.values["native_pro_schedule"][2]["minute"] == 1200
    assert device.diagnostics["native_schedule_protocol"] == "facebd"
    assert device.diagnostics["native_schedule_readback_at"]


def test_plant_pro_switch_mode_and_channels_use_spp_packets():
    asyncio.run(_async_test_plant_pro_commands_use_spp_packets())


async def _async_test_plant_pro_commands_use_spp_packets():
    device = _make_device(
        name="PlantPro_AABBCC",
        model="Plant Pro 4.0 Bluetooth LED",
    )
    device.client = SimpleNamespace(
        plant_pro_spp=True,
        command_write_uuid="0000fff2-0000-1000-8000-00805f9b34fb",
        raw_facebd=True,
        wifi_facebd=False,
    )
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)

    assert await device.async_set_switch("led_on_off", True)
    device._async_send_packet.assert_awaited_once_with(protocol.spp_switch_packet(True))

    device._async_send_packet.reset_mock()
    assert await device.async_select_option("mode", "professional")
    device._async_send_packet.assert_awaited_once_with(protocol.spp_mode_packet(2))

    device.values["mode"] = "manual"
    device.values["led_on_off"] = True
    device._async_send_packet.reset_mock()
    assert await device.async_set_channels({"channel_1": 75})
    device._async_send_packet.assert_awaited_once_with(protocol.spp_all_zone_packet([75, 0, 0, 0, 0]))


def test_plant_pro_native_schedule_actions_write_fixture_packets():
    asyncio.run(_async_test_plant_pro_native_schedule_actions_write_fixture_packets())


async def _async_test_plant_pro_native_schedule_actions_write_fixture_packets():
    device = _make_device(name="PlantPro_AABBCC", model="Plant Pro 4.0 Bluetooth LED")
    device.client = SimpleNamespace(plant_pro_spp=True)
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    auto = {
        "sunrise": (8, 0, 60),
        "sunset": (20, 30, 45),
        "sleep": (23, 15),
        "day_levels": [80, 70, 60, 50, 40],
        "night_levels": [0, 5, 0, 0, 0],
    }
    points = [
        {"hour": 8, "minute": 0, "levels": [0, 0, 0, 0, 0]},
        {"hour": 10, "minute": 0, "levels": [20, 20, 20, 20, 20]},
        {"hour": 12, "minute": 30, "levels": [80, 70, 60, 50, 40]},
        {"hour": 20, "minute": 0, "levels": [0, 0, 0, 0, 0]},
    ]
    windows = [
        {
            "start_hour": 12,
            "start_minute": 0,
            "end_hour": 12,
            "end_minute": 10,
            "effect_id": 1,
            "weekdays": [True] * 7,
            "enabled": True,
        }
    ]

    assert await device.async_set_native_auto_schedule(auto)
    assert await device.async_set_native_pro_schedule(points)
    assert await device.async_set_native_effect_schedule(windows)
    assert [call.args[0] for call in device._async_send_packet.await_args_list] == [
        protocol.spp_auto_schedule_packet(
            sunrise=auto["sunrise"],
            sunset=auto["sunset"],
            sleep=auto["sleep"],
            day_levels=auto["day_levels"],
            night_levels=auto["night_levels"],
        ),
        protocol.spp_mode_packet(1),
        protocol.spp_pro_schedule_packet(points),
        protocol.spp_mode_packet(2),
        protocol.spp_effect_schedule_packet(windows),
    ]
    assert device.diagnostics["native_schedule_protocol"] == "plant_pro"
    assert device.diagnostics["native_pro_schedule_points"] == 4
    assert device.diagnostics["plant_pro_effect_schedule"][0]["effect"] == "Thunderstorm"


def test_native_pro_schedule_limits_follow_detected_apk_transport():
    classic = _make_device()
    facebd = _make_device(name="AquaSky3.0_Test", model="AquaSky 3.0 Bluetooth LED")
    facebd.client = SimpleNamespace(
        command_write_uuid="facebd01-0000-1000-8000-00805f9b34fb",
        wifi_facebd=True,
        plant_pro_spp=False,
    )
    plant_pro = _make_device(name="PlantPro_AABBCC", model="Plant Pro 4.0 Bluetooth LED")
    plant_pro.client = SimpleNamespace(wifi_facebd=False, plant_pro_spp=True)

    assert classic.native_pro_schedule_limits() == ("classic", 4, 10)
    assert facebd.native_pro_schedule_limits() == ("facebd", 4, 12)
    assert plant_pro.native_pro_schedule_limits() == ("plant_pro", 4, 12)


def test_invalid_classic_pro_schedule_is_rejected_after_transport_detection():
    asyncio.run(_async_test_invalid_classic_pro_schedule_is_rejected_after_transport_detection())


async def _async_test_invalid_classic_pro_schedule_is_rejected_after_transport_detection():
    device = _make_device()
    device._async_prepare_command = AsyncMock(return_value=True)
    device._async_send_packet = AsyncMock(return_value=True)
    points = [{"time": f"{hour:02d}:00", "red": 0, "green": 0, "blue": 0, "white": 0} for hour in range(11)]

    assert not await device.async_set_native_pro_schedule(points)
    device._async_prepare_command.assert_awaited_once()
    device._async_send_packet.assert_not_awaited()
    assert device.diagnostics["last_error"] == "classic Professional schedules require 4 to 10 points"


def test_plant_pro_expected_state_uses_spp_keys():
    device = _make_device(
        name="PlantPro_AABBCC",
        model="Plant Pro 4.0 Bluetooth LED",
    )
    device.client = MagicMock(raw_facebd=True, plant_pro_spp=True)
    packet = protocol.spp_all_zone_packet([10, 20, 30, 40, 50])

    assert device._expected_state_for_packet(packet) == {
        protocol.SPP_CHANNEL_KEYS[0]: 10,
        protocol.SPP_CHANNEL_KEYS[1]: 20,
        protocol.SPP_CHANNEL_KEYS[2]: 30,
        protocol.SPP_CHANNEL_KEYS[3]: 40,
        protocol.SPP_CHANNEL_KEYS[4]: 50,
        protocol.SPP_EFFECT_KEY: 0,
    }


def test_plant_pro_clock_action_sends_apk_mesh_clock_packet():
    asyncio.run(_async_test_plant_pro_clock_action_sends_apk_mesh_clock_packet())


def test_stopping_preview_reactivates_the_native_fixture_mode():
    asyncio.run(_async_test_stopping_preview_reactivates_the_native_fixture_mode())


async def _async_test_stopping_preview_reactivates_the_native_fixture_mode():
    device = _make_device()
    device.preview_restore_values = {"channel_1": 50}
    device.preview_restore_mode = "professional"
    device.async_select_option = AsyncMock(return_value=True)
    device.async_set_channels = AsyncMock(return_value=True)

    await device.async_stop_preview()

    device.async_select_option.assert_awaited_once_with("mode", "professional")
    device.async_set_channels.assert_not_awaited()


async def _async_test_plant_pro_clock_action_sends_apk_mesh_clock_packet():
    device = _make_device(
        name="PlantPro_AABBCC",
        model="Plant Pro 4.0 Bluetooth LED",
        service_uuids=["0000fff0-0000-1000-8000-00805f9b34fb"],
    )
    device.client = SimpleNamespace(
        plant_pro_spp=True,
        command_write_uuid="0000fff2-0000-1000-8000-00805f9b34fb",
        ensure_connected=AsyncMock(return_value=True),
    )
    device._async_send_packet = AsyncMock(return_value=True)

    assert await device.async_sync_clock(force=True)
    device._async_send_packet.assert_awaited_once()
    packet = device._async_send_packet.await_args.args[0]
    assert packet[0] == protocol.MESH_OPCODE_CLOCK
    assert len(packet) == 8
    assert device.diagnostics["status"] == "clock_synced"


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
    device = _make_device(name="AquaSky2.0_Test", model="AquaSky 2.0 Bluetooth LED")
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
    assert protocol.WIFI_AUTO_SUNRISE_KEY not in expected


def test_facebd_service_uuid_selects_facebd_protocol():
    device = _make_device()

    assert (
        device._uses_facebd_protocol(
            "AquaSky3.0_Test",
            ["facebd00-7261-6262-6974-696f74626c65"],
            {},
            {},
        )
        is True
    )


def test_classic_manufacturer_data_is_not_facebd_protocol_evidence():
    device = _make_device(
        name="AquaSky2.0_Test",
        model="AquaSky 2.0 Bluetooth LED",
        service_uuids=["00001000-0000-1000-8000-00805f9b34fb"],
        manufacturer_data={"12592": "3438303130330000000000000000000000000000"},
    )

    assert device.facebd is False
    assert device.numbers() == AQUASKY_NUMBERS
