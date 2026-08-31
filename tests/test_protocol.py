"""Tests for Fluval packet builders."""

from datetime import datetime, timezone

import pytest

from custom_components.fluvalble.core import protocol


def test_wifi_all_zone_packet_contains_manual_key_and_channel_values():
    packet = protocol.wifi_all_zone_packet([10, 20, 30, 40, 50])

    decoded = protocol.decode_cbor_map(packet)

    assert decoded[protocol.WIFI_MANUAL_KEY] == 0
    assert decoded[protocol.WIFI_CHANNEL_KEYS[0]] == 10
    assert decoded[protocol.WIFI_CHANNEL_KEYS[3]] == 40
    assert protocol.WIFI_AUTO_SUNRISE_KEY not in decoded


def test_wifi_values_are_clamped_to_percent_range():
    packet = protocol.wifi_all_zone_packet([-1, 101, 25, 50, 75])

    decoded = protocol.decode_cbor_map(packet)

    assert decoded[protocol.WIFI_CHANNEL_KEYS[0]] == 0
    assert decoded[protocol.WIFI_CHANNEL_KEYS[1]] == 100


def test_wifi_mode_packet_uses_mode_key():
    packet = protocol.wifi_mode_packet(1)

    assert protocol.decode_cbor_map(packet) == {protocol.WIFI_MODE_KEY: 1}


def test_decode_aquasky_facebd02_state_capture():
    """Decode a hardware response with the AquaSky's four physical channels."""
    captured_state = bytes.fromhex("a6 18 66 1b 00 00 01 9f 43 b3 19 af 18 6d 00 18 71 0a 18 70 0a 18 6f 00 18 6e 00")

    assert protocol.decode_cbor_map(captured_state) == {
        102: 1783547238831,
        protocol.WIFI_MANUAL_KEY: 0,
        protocol.WIFI_CHANNEL_KEYS[3]: 10,
        protocol.WIFI_CHANNEL_KEYS[2]: 10,
        protocol.WIFI_CHANNEL_KEYS[1]: 0,
        protocol.WIFI_CHANNEL_KEYS[0]: 0,
    }


def test_decode_cbor_map_rejects_trailing_data():
    assert protocol.decode_cbor_map(bytes((0xA1, 0x01, 0x02, 0x00))) is None


def test_decode_cbor_map_rejects_oversized_container():
    assert protocol.decode_cbor_map(bytes((0xB8, 65))) is None


def test_decode_cbor_map_rejects_excessive_nesting():
    nested = bytes((0xA1, 0x01)) + (bytes((0x81,)) * 9) + bytes((0x00,))
    assert protocol.decode_cbor_map(nested) is None


def test_wifi_clock_and_timezone_packets():
    moment = datetime(2026, 7, 19, 12, 30, 0, tzinfo=timezone.utc)
    clock = protocol.decode_cbor_map(protocol.wifi_clock_packet(moment))
    tz = protocol.decode_cbor_map(protocol.wifi_timezone_packet(moment))

    assert clock[protocol.WIFI_CLOCK_MS_KEY] == int(moment.timestamp() * 1000)
    assert tz[protocol.WIFI_TZ_OFFSET_KEY] == 0


def test_wifi_native_auto_schedule_matches_apk_cbor_shape():
    packet = protocol.wifi_auto_schedule_packet(
        sunrise=(8, 0, 60),
        sunset=(21, 0, 45),
        sleep=(22, 30),
        day_levels=[80, 70, 60, 50],
        night_levels=[0, 10, 0, 0],
    )

    decoded = protocol.decode_cbor_map(packet)

    assert decoded == {
        114: [480, 540],
        115: [1215, 1260],
        116: 1350,
        117: bytes([80, 70, 60, 50]),
        118: bytes([0, 10, 0, 0]),
    }
    assert protocol.decode_wifi_auto_schedule(decoded) == {
        "sunrise": {"hour": 8, "minute": 0, "ramp": 60},
        "sunset": {"hour": 21, "minute": 0, "ramp": 45},
        "sleep": {"hour": 22, "minute": 30},
        "day_levels": [80, 70, 60, 50],
        "night_levels": [0, 10, 0, 0],
    }


def test_wifi_native_pro_schedule_matches_apk_cbor_shape():
    packet = protocol.wifi_pro_schedule_packet(
        [
            {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
            {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
        ]
    )

    decoded = protocol.decode_cbor_map(packet)

    assert decoded == {120: 2, 121: [480, 750], 122: bytes([1, 2, 3, 4, 10, 20, 30, 40])}
    assert protocol.decode_wifi_pro_schedule(decoded) == [
        {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
        {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
    ]


def test_wifi_native_preview_uses_1440_to_stop():
    assert protocol.decode_cbor_map(protocol.wifi_auto_preview_packet(750)) == {119: 750}
    assert protocol.decode_cbor_map(protocol.wifi_auto_preview_packet(None)) == {119: 1440}


def test_old_clock_packet_shape():
    moment = datetime(2026, 7, 19, 12, 30, 45, tzinfo=timezone.utc)
    local = moment.astimezone()
    packet = protocol.old_clock_packet(moment)

    assert packet[0] == 0x68
    assert packet[1] == protocol.OLD_CLOCK
    assert packet[2] == local.year % 100
    assert packet[3] == local.month
    assert packet[4] == local.day
    assert packet[6] == local.hour
    assert packet[7] == local.minute
    assert packet[8] == local.second


def test_old_weather_effect_packet_uses_apk_command_and_checksum():
    packet = protocol.old_weather_effect_packet(2)

    assert packet[:3] == bytes((0x68, protocol.OLD_WEATHER_EFFECT, 2))
    assert packet[-1] == packet[0] ^ packet[1] ^ packet[2]


@pytest.mark.parametrize("effect_id", [0, 12])
def test_old_weather_effect_packet_rejects_unknown_ids(effect_id):
    with pytest.raises(ValueError):
        protocol.old_weather_effect_packet(effect_id)


def test_classic_native_auto_schedule_matches_apk_6807_shape():
    packet = protocol.old_auto_schedule_packet(
        sunrise=(8, 0, 60),
        sunset=(21, 0, 45),
        sleep=(22, 30),
        day_levels=[80, 70, 60, 50],
        night_levels=[0, 10, 0, 0],
        channel_count=4,
    )

    assert packet[:-1] == bytes.fromhex("68 07 08 00 09 00 50 46 3c 32 14 0f 15 00 00 0a 00 00 01 16 1e")
    assert protocol.decode_old_auto_schedule(bytes((1,)) + packet[2:-1], channel_count=4) == {
        "sunrise": {"hour": 8, "minute": 0, "ramp": 60},
        "sunset": {"hour": 21, "minute": 0, "ramp": 45},
        "sleep": {"hour": 22, "minute": 30},
        "day_levels": [80, 70, 60, 50],
        "night_levels": [0, 10, 0, 0],
    }


def test_classic_native_pro_schedule_matches_apk_6810_shape():
    packet = protocol.old_pro_schedule_packet(
        [
            {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
            {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
        ],
        channel_count=4,
    )

    assert packet[:-1] == bytes.fromhex("68 10 02 08 00 01 02 03 04 0c 1e 0a 14 1e 28")
    assert protocol.decode_old_pro_schedule(bytes((2,)) + packet[2:-1], channel_count=4) == [
        {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
        {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
    ]


def test_mesh_clock_packet_shape():
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    local = moment.astimezone()
    clock = protocol.mesh_clock_packet(moment)
    assert clock[0] == protocol.MESH_OPCODE_CLOCK
    assert list(clock[1:8]) == [
        local.year % 100,
        local.month,
        local.day,
        (local.weekday() + 1) % 7,
        local.hour,
        local.minute,
        local.second,
    ]


def test_plant_pro_switch_packets_match_reference_capture():
    assert protocol.spp_switch_packet(True) == bytes.fromhex("d1 a1 02 f5")
    assert protocol.spp_switch_packet(False) == bytes.fromhex("d1 a1 02 f4")


def test_plant_pro_mode_packets_match_reference_capture():
    assert protocol.spp_mode_packet(0) == bytes.fromhex("d1 a1 01 00")
    assert protocol.spp_mode_packet(1) == bytes.fromhex("d1 a1 01 01")
    assert protocol.spp_mode_packet(2) == bytes.fromhex("d1 a1 01 02")


def test_plant_pro_all_zone_packet_matches_reference_capture():
    packet = protocol.spp_all_zone_packet([100, 20, 30, 40, 50])

    assert packet == bytes.fromhex("d1 a6 03 18 64 04 14 05 18 1e 06 18 28 07 18 32 0e 00")
    assert protocol.decode_cbor_update(packet) == {
        protocol.SPP_CHANNEL_KEYS[0]: 100,
        protocol.SPP_CHANNEL_KEYS[1]: 20,
        protocol.SPP_CHANNEL_KEYS[2]: 30,
        protocol.SPP_CHANNEL_KEYS[3]: 40,
        protocol.SPP_CHANNEL_KEYS[4]: 50,
        protocol.SPP_MANUAL_KEY: 0,
    }


def test_plant_pro_effect_packet_matches_apk_cbor_command():
    assert protocol.spp_effect_packet(3) == bytes.fromhex("d1 a1 0e 03")


def test_plant_pro_auto_schedule_round_trip():
    packet = protocol.spp_auto_schedule_packet(
        sunrise=(8, 0, 60),
        sunset=(20, 30, 45),
        sleep=(23, 15),
        day_levels=[80, 70, 60, 50, 40],
        night_levels=[0, 5, 0, 0, 0],
    )
    decoded = protocol.decode_cbor_update(packet)

    assert decoded == {
        8: bytes((8, 0, 60)),
        9: bytes((20, 30, 45)),
        10: bytes((23, 15)),
        11: bytes((80, 70, 60, 50, 40)),
        12: bytes((0, 5, 0, 0, 0)),
    }
    assert protocol.decode_spp_auto_schedule(decoded) == {
        "sunrise": "08:00",
        "sunrise_ramp": 60,
        "sunset": "20:30",
        "sunset_ramp": 45,
        "sleep": "23:15",
        "day_levels": [80, 70, 60, 50, 40],
        "night_levels": [0, 5, 0, 0, 0],
    }


def test_plant_pro_pro_schedule_round_trip():
    points = [
        {"hour": 8, "minute": 0, "levels": [0, 0, 0, 0, 0]},
        {"hour": 12, "minute": 30, "levels": [80, 70, 60, 50, 40]},
    ]
    decoded = protocol.decode_cbor_update(protocol.spp_pro_schedule_packet(points))

    assert decoded[protocol.SPP_PRO_SCHEDULE_KEY] == bytes((2, 8, 0, 0, 0, 0, 0, 0, 12, 30, 80, 70, 60, 50, 40))
    assert protocol.decode_spp_pro_schedule(decoded) == [
        {"time": "08:00", "levels": [0, 0, 0, 0, 0]},
        {"time": "12:30", "levels": [80, 70, 60, 50, 40]},
    ]


def test_plant_pro_effect_schedule_uses_fixed_42_byte_apk_blob():
    windows = [
        {
            "start_hour": 12,
            "start_minute": 0,
            "end_hour": 12,
            "end_minute": 10,
            "effect_id": 1,
            "weekdays": [True, False, True, False, True, False, False],
            "enabled": True,
        }
    ]
    packet = protocol.spp_effect_schedule_packet(windows)
    decoded = protocol.decode_cbor_update(packet)

    assert packet[:5] == bytes.fromhex("d1 a1 0f 58 2a")
    assert len(decoded[protocol.SPP_EFFECT_SCHEDULE_KEY]) == 42
    assert decoded[protocol.SPP_EFFECT_SCHEDULE_KEY][:6] == bytes((0x95, 12, 0, 12, 10, 1))
    assert protocol.decode_spp_effect_schedule(decoded) == [
        {
            "enabled": True,
            "weekdays": [True, False, True, False, True, False, False],
            "start": "12:00",
            "end": "12:10",
            "effect_id": 1,
        }
    ]


def test_plant_pro_status_strips_d2_header_and_skips_schedule_blobs():
    status = bytes.fromhex(
        "d2 aa 00 0e 01 00 02 f5 03 18 64 04 18 64 05 18 64 06 18 64 07 18 64 08 43 0d 00 a0 09 43 15 03 26"
    )

    decoded = protocol.decode_cbor_update(status)

    assert decoded[protocol.SPP_MODE_KEY] == 0
    assert decoded[protocol.SPP_SWITCH_KEY] is True
    assert decoded[protocol.SPP_CHANNEL_KEYS[0]] == 100
    assert decoded[8] == bytes.fromhex("0d00a0")


def test_cbor_signed_timezone_offset():
    packet = protocol.cbor_map({protocol.WIFI_TZ_OFFSET_KEY: -150})
    decoded = protocol.decode_cbor_map(packet)
    assert decoded[protocol.WIFI_TZ_OFFSET_KEY] == -150
