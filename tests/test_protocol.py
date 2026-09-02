"""Tests for Fluval packet builders."""

from datetime import datetime, timezone

import pytest

from custom_components.fluvalble.core import protocol


def _old_state_packet(body: bytes) -> bytes:
    return protocol.old_packet(protocol.OLD_READ_PARAMS + body)


def test_decode_old_manual_state_matches_apk_layout():
    body = bytearray((0, 0x03, 11))
    for value in (100, 200, 300, 400, 500):
        body.extend((value & 0xFF, value >> 8))
    body.extend(bytes(range(1, 21)))

    assert protocol.decode_old_state_packet(_old_state_packet(body), channel_count=5) == {
        "mode": 0,
        "body": bytes(body),
        "power": True,
        "effect_id": 11,
        "channels": [100, 200, 300, 400, 500],
    }


def test_decode_old_state_accepts_only_apk_auto_and_pro_lengths():
    for length in (17, 20, 23, 26):
        body = bytes((1,)) + bytes(length - 1)
        assert protocol.decode_old_state_packet(_old_state_packet(body), channel_count=4) is not None
    assert protocol.decode_old_state_packet(_old_state_packet(bytes((1,)) + bytes(17)), channel_count=4) is None

    pro_body = bytes((2, 4)) + bytes(4 * (4 + 2))
    assert protocol.decode_old_state_packet(_old_state_packet(pro_body), channel_count=4) is not None
    assert protocol.decode_old_state_packet(_old_state_packet(pro_body + bytes(6)), channel_count=4) is not None
    assert protocol.decode_old_state_packet(_old_state_packet(pro_body + bytes(3)), channel_count=4) is None


def test_decode_old_state_rejects_wrong_command_checksum_channel_count_and_mode():
    body = bytes((0, 1, 0)) + bytes(24)
    valid = _old_state_packet(body)

    assert protocol.decode_old_state_packet(protocol.old_packet(bytes((0x68, 0x18)) + body), channel_count=4) is None
    assert protocol.decode_old_state_packet(valid[:-1] + bytes((valid[-1] ^ 1,)), channel_count=4) is None
    assert protocol.decode_old_state_packet(valid, channel_count=3) is None
    assert protocol.decode_old_state_packet(_old_state_packet(bytes((3, 0, 0))), channel_count=4) is None


def test_wifi_five_channel_all_zone_packet_matches_apk_keys():
    packet = protocol.wifi_all_zone_packet([10, 20, 30, 40, 50])

    decoded = protocol.decode_cbor_map(packet)

    assert decoded == {
        protocol.WIFI_MANUAL_KEY: 0,
        protocol.WIFI_CHANNEL_KEYS[0]: 10,
        protocol.WIFI_CHANNEL_KEYS[1]: 20,
        protocol.WIFI_CHANNEL_KEYS[2]: 30,
        protocol.WIFI_CHANNEL_KEYS[3]: 40,
        protocol.WIFI_CHANNEL_KEYS[4]: 50,
    }
    assert protocol.WIFI_CHANNEL_KEYS[4] == protocol.WIFI_AUTO_SUNRISE_KEY


def test_wifi_four_channel_all_zone_packet_stops_before_key_114():
    decoded = protocol.decode_cbor_map(protocol.wifi_all_zone_packet([10, 20, 30, 40]))

    assert decoded == {
        protocol.WIFI_MANUAL_KEY: 0,
        protocol.WIFI_CHANNEL_KEYS[0]: 10,
        protocol.WIFI_CHANNEL_KEYS[1]: 20,
        protocol.WIFI_CHANNEL_KEYS[2]: 30,
        protocol.WIFI_CHANNEL_KEYS[3]: 40,
    }
    assert protocol.WIFI_AUTO_SUNRISE_KEY not in decoded


def test_wifi_values_are_clamped_to_percent_range():
    packet = protocol.wifi_all_zone_packet([-1, 101, 25, 50, 75])

    decoded = protocol.decode_cbor_map(packet)

    assert decoded[protocol.WIFI_CHANNEL_KEYS[0]] == 0
    assert decoded[protocol.WIFI_CHANNEL_KEYS[1]] == 100


def test_wifi_single_zone_packet_matches_apk_channel_and_manual_keys():
    packet = protocol.wifi_single_zone_packet(4, 75)

    assert packet == bytes.fromhex("a2 18 72 18 4b 18 6d 00")
    assert protocol.decode_cbor_map(packet) == {
        protocol.WIFI_CHANNEL_KEYS[4]: 75,
        protocol.WIFI_MANUAL_KEY: 0,
    }


def test_wifi_single_zone_packet_validates_index_and_clamps_level():
    assert protocol.decode_cbor_map(protocol.wifi_single_zone_packet(0, 101))[protocol.WIFI_CHANNEL_KEYS[0]] == 100
    with pytest.raises(ValueError, match="between 0 and 4"):
        protocol.wifi_single_zone_packet(5, 50)


def test_wifi_mode_packet_uses_mode_key():
    packet = protocol.wifi_mode_packet(1)

    assert protocol.decode_cbor_map(packet) == {protocol.WIFI_MODE_KEY: 1}


def test_wifi_dst_packet_uses_apk_boolean_key_99():
    assert protocol.decode_cbor_map(protocol.wifi_dst_packet(True)) == {
        protocol.WIFI_DST_KEY: True,
    }
    assert protocol.decode_cbor_map(protocol.wifi_dst_packet(False)) == {
        protocol.WIFI_DST_KEY: False,
    }


def test_wifi_weather_effect_packet_uses_apk_manual_key():
    assert protocol.decode_cbor_map(protocol.wifi_effect_packet(2)) == {
        protocol.WIFI_MANUAL_KEY: 2,
    }
    assert protocol.decode_cbor_map(protocol.wifi_effect_packet(0)) == {
        protocol.WIFI_MANUAL_KEY: 0,
    }


def test_native_find_packets_match_apk_commands():
    assert protocol.decode_cbor_map(protocol.wifi_find_packet()) == {52: "find"}
    assert protocol.spp_find_packet() == bytes.fromhex("d1 a1 18 34 64 66 69 6e 64")
    assert protocol.old_find_packet() == bytes.fromhex("68 0f 67")


@pytest.mark.parametrize("effect_id", [-1, 12])
def test_wifi_weather_effect_packet_rejects_unknown_ids(effect_id):
    with pytest.raises(ValueError):
        protocol.wifi_effect_packet(effect_id)


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


def test_wifi_five_channel_auto_schedule_preserves_apk_level_arrays():
    packet = protocol.wifi_auto_schedule_packet(
        sunrise=(8, 0, 60),
        sunset=(21, 0, 45),
        sleep=None,
        day_levels=[80, 70, 60, 50, 40],
        night_levels=[0, 10, 0, 0, 5],
        channel_count=5,
    )

    decoded = protocol.decode_cbor_map(packet)

    assert decoded[protocol.WIFI_AUTO_DAY_LEVELS_KEY] == bytes([80, 70, 60, 50, 40])
    assert decoded[protocol.WIFI_AUTO_NIGHT_LEVELS_KEY] == bytes([0, 10, 0, 0, 5])
    assert protocol.decode_wifi_auto_schedule(decoded)["day_levels"] == [80, 70, 60, 50, 40]


def test_wifi_auto_schedule_rejects_non_apk_channel_count():
    with pytest.raises(ValueError, match="four or five channels"):
        protocol.wifi_auto_schedule_packet(
            sunrise=(8, 0, 60),
            sunset=(21, 0, 45),
            sleep=None,
            day_levels=[80, 70, 60],
            night_levels=[0, 10, 0],
            channel_count=3,
        )


def test_wifi_native_pro_schedule_matches_apk_cbor_shape():
    packet = protocol.wifi_pro_schedule_packet(
        [
            {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
            {"minute": 600, "channel_1": 5, "channel_2": 6, "channel_3": 7, "channel_4": 8},
            {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
            {"minute": 1200, "channel_1": 0, "channel_2": 0, "channel_3": 0, "channel_4": 0},
        ]
    )

    decoded = protocol.decode_cbor_map(packet)

    assert decoded == {
        120: 4,
        121: [480, 600, 750, 1200],
        122: bytes([1, 2, 3, 4, 5, 6, 7, 8, 10, 20, 30, 40, 0, 0, 0, 0]),
    }
    assert protocol.decode_wifi_pro_schedule(decoded) == [
        {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
        {"minute": 600, "channel_1": 5, "channel_2": 6, "channel_3": 7, "channel_4": 8},
        {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
        {"minute": 1200, "channel_1": 0, "channel_2": 0, "channel_3": 0, "channel_4": 0},
    ]


def test_wifi_native_preview_uses_1440_to_stop():
    assert protocol.decode_cbor_map(protocol.wifi_auto_preview_packet(750)) == {119: 750}
    assert protocol.decode_cbor_map(protocol.wifi_auto_preview_packet(None)) == {119: 1440}


def test_plant_pro_native_preview_uses_apk_mesh_key_and_stop_value():
    assert protocol.decode_cbor_update(protocol.spp_schedule_preview_packet(750)) == {51: 750}
    assert protocol.decode_cbor_update(protocol.spp_schedule_preview_packet(None)) == {51: 1440}


def test_classic_native_preview_uses_680b_scaled_levels_and_680c_stop():
    preview = protocol.old_auto_preview_packet([10, 20, 30, 40])
    stop = protocol.old_auto_preview_packet(None)

    assert preview[:-1] == bytes.fromhex("68 0B 00 64 00 C8 01 2C 01 90")
    assert stop[:-1] == bytes.fromhex("68 0C")


def test_old_all_zone_packet_matches_apk_big_endian_words():
    packet = protocol.old_all_zone_packet([0, 50, 100, 25])

    assert packet == bytes.fromhex("68 04 00 00 01 F4 03 E8 00 FA 88")


def test_old_all_zone_packet_clamps_and_encodes_five_channels():
    packet = protocol.old_all_zone_packet([-1, 20, 30, 40, 101])

    assert packet == bytes.fromhex("68 04 00 00 00 C8 01 2C 01 90 03 E8 F3")


def test_old_clock_packet_shape():
    moment = datetime(2026, 7, 19, 12, 30, 45, tzinfo=timezone.utc)
    local = moment.astimezone()
    packet = protocol.old_clock_packet(moment)

    assert packet[0] == 0x68
    assert packet[1] == protocol.OLD_CLOCK
    assert packet[2] == local.year % 100
    assert packet[3] == local.month
    assert packet[4] == local.day
    assert packet[5] == local.isoweekday()
    assert packet[6] == local.hour
    assert packet[7] == local.minute
    assert packet[8] == local.second


@pytest.mark.parametrize(("day", "weekday"), [(7, 1), (8, 2), (9, 3), (10, 4), (11, 5), (12, 6), (13, 7)])
def test_old_clock_packet_matches_apk_weekday_values(day, weekday):
    moment = datetime(2026, 9, day, 12, tzinfo=timezone.utc)

    assert protocol.old_clock_packet(moment)[5] == weekday


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
            {"minute": 600, "channel_1": 5, "channel_2": 6, "channel_3": 7, "channel_4": 8},
            {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
            {"minute": 1200, "channel_1": 0, "channel_2": 0, "channel_3": 0, "channel_4": 0},
        ],
        channel_count=4,
    )

    assert packet[:-1] == bytes.fromhex(
        "68 10 04 08 00 01 02 03 04 0a 00 05 06 07 08 0c 1e 0a 14 1e 28 14 00 00 00 00 00"
    )
    assert protocol.decode_old_pro_schedule(bytes((2,)) + packet[2:-1], channel_count=4) == [
        {"minute": 480, "channel_1": 1, "channel_2": 2, "channel_3": 3, "channel_4": 4},
        {"minute": 600, "channel_1": 5, "channel_2": 6, "channel_3": 7, "channel_4": 8},
        {"minute": 750, "channel_1": 10, "channel_2": 20, "channel_3": 30, "channel_4": 40},
        {"minute": 1200, "channel_1": 0, "channel_2": 0, "channel_3": 0, "channel_4": 0},
    ]


def test_native_pro_schedule_builders_enforce_apk_point_limits():
    channel_points = [
        {
            "minute": index * 60,
            "channel_1": index,
            "channel_2": index,
            "channel_3": index,
            "channel_4": index,
        }
        for index in range(13)
    ]
    spp_points = [{"hour": index, "minute": 0, "levels": [index] * 5} for index in range(13)]

    protocol.old_pro_schedule_packet(channel_points[:10], channel_count=4)
    protocol.wifi_pro_schedule_packet(channel_points[:12])
    protocol.spp_pro_schedule_packet(spp_points[:12])

    with pytest.raises(ValueError, match="Classic Fluval schedule requires 4-10 points"):
        protocol.old_pro_schedule_packet(channel_points[:3], channel_count=4)
    with pytest.raises(ValueError, match="Classic Fluval schedule requires 4-10 points"):
        protocol.old_pro_schedule_packet(channel_points[:11], channel_count=4)
    with pytest.raises(ValueError, match="FACEBD schedule requires 4-12 points"):
        protocol.wifi_pro_schedule_packet(channel_points[:3])
    with pytest.raises(ValueError, match="FACEBD schedule requires 4-12 points"):
        protocol.wifi_pro_schedule_packet(channel_points)
    with pytest.raises(ValueError, match="Plant Pro schedule requires 4-12 points"):
        protocol.spp_pro_schedule_packet(spp_points[:3])
    with pytest.raises(ValueError, match="Plant Pro schedule requires 4-12 points"):
        protocol.spp_pro_schedule_packet(spp_points)


def test_mesh_clock_packet_shape():
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    local = moment.astimezone()
    clock = protocol.mesh_clock_packet(moment)
    assert clock[0] == protocol.MESH_OPCODE_CLOCK
    assert list(clock[1:8]) == [
        local.year % 100,
        local.month,
        local.day,
        local.isoweekday(),
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


def test_plant_pro_single_zone_packet_matches_apk_mesh_command():
    packet = protocol.spp_single_zone_packet(0, 75)

    assert packet == bytes.fromhex("d1 a2 03 18 4b 0e 00")
    assert protocol.decode_cbor_update(packet) == {
        protocol.SPP_CHANNEL_KEYS[0]: 75,
        protocol.SPP_MANUAL_KEY: 0,
    }


def test_plant_pro_single_zone_packet_validates_index_and_clamps_level():
    assert protocol.decode_cbor_update(protocol.spp_single_zone_packet(4, -1))[protocol.SPP_CHANNEL_KEYS[4]] == 0
    with pytest.raises(ValueError, match="between 0 and 4"):
        protocol.spp_single_zone_packet(-1, 50)


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
        {"hour": 10, "minute": 0, "levels": [20, 20, 20, 20, 20]},
        {"hour": 12, "minute": 30, "levels": [80, 70, 60, 50, 40]},
        {"hour": 20, "minute": 0, "levels": [0, 0, 0, 0, 0]},
    ]
    decoded = protocol.decode_cbor_update(protocol.spp_pro_schedule_packet(points))

    assert decoded[protocol.SPP_PRO_SCHEDULE_KEY][0] == 4
    assert protocol.decode_spp_pro_schedule(decoded) == [
        {"time": "08:00", "levels": [0, 0, 0, 0, 0]},
        {"time": "10:00", "levels": [20, 20, 20, 20, 20]},
        {"time": "12:30", "levels": [80, 70, 60, 50, 40]},
        {"time": "20:00", "levels": [0, 0, 0, 0, 0]},
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


def test_facebd_effect_schedule_uses_apk_key_123_variable_blob():
    windows = [
        {
            "start_hour": 12,
            "start_minute": 0,
            "end_hour": 12,
            "end_minute": 10,
            "effect_id": 11,
            "weekdays": [True, False, True, False, True, False, False],
            "enabled": True,
        }
    ]

    packet = protocol.wifi_effect_schedule_packet(windows)
    decoded = protocol.decode_cbor_map(packet)

    assert packet == bytes.fromhex("a1 18 7b 46 95 0c 00 0c 0a 0b")
    assert decoded[protocol.WIFI_SCHEDULED_EFFECT_KEY] == bytes((0x95, 12, 0, 12, 10, 11))
    assert protocol.decode_wifi_effect_schedule(decoded) == [
        {
            "enabled": True,
            "weekdays": [True, False, True, False, True, False, False],
            "start": "12:00",
            "end": "12:10",
            "effect_id": 11,
        }
    ]
    assert protocol.wifi_effect_schedule_packet([]) == bytes.fromhex("a1 18 7b 40")


def test_classic_effect_schedule_uses_apk_6811_packet():
    windows = [
        {
            "start_hour": 12,
            "start_minute": 0,
            "end_hour": 12,
            "end_minute": 10,
            "effect_id": 11,
            "weekdays": [True, False, True, False, True, False, False],
            "enabled": True,
        }
    ]

    packet = protocol.old_effect_schedule_packet(windows)

    assert packet[:-1] == bytes.fromhex("68 11 95 0c 00 0c 0a 0b")
    assert packet[-1] == _xor(packet[:-1])
    assert protocol.old_effect_schedule_packet([]) == bytes.fromhex("68 11 79")


@pytest.mark.parametrize(
    ("builder", "effect_id"),
    [
        (protocol.spp_effect_schedule_packet, 5),
        (protocol.wifi_effect_schedule_packet, 12),
        (protocol.old_effect_schedule_packet, 12),
    ],
)
def test_effect_schedule_rejects_transport_unsupported_effect_ids(builder, effect_id):
    windows = [
        {
            "start_hour": 12,
            "start_minute": 0,
            "end_hour": 12,
            "end_minute": 10,
            "effect_id": effect_id,
            "weekdays": [True] * 7,
            "enabled": True,
        }
    ]

    with pytest.raises(ValueError, match="effect window ID"):
        builder(windows)


def test_classic_schedule_readback_distinguishes_sleep_from_effect_slot():
    day = bytes((10, 20, 30, 40))
    night = bytes((1, 2, 3, 4))
    base = bytes((1, 8, 0, 9, 0)) + day + bytes((19, 0, 20, 0)) + night
    effect = bytes((0x95, 12, 0, 12, 10, 11))

    auto = protocol.decode_old_auto_schedule(base + effect, channel_count=4)
    windows = protocol.decode_old_effect_schedule(base + effect, channel_count=4)

    assert auto["sleep"] is None
    assert windows == [
        {
            "enabled": True,
            "weekdays": [True, False, True, False, True, False, False],
            "start": "12:00",
            "end": "12:10",
            "effect_id": 11,
        }
    ]


def _xor(packet):
    checksum = 0
    for item in packet:
        checksum ^= item
    return checksum


def test_plant_pro_status_strips_d2_header_and_skips_schedule_blobs():
    status = bytes.fromhex(
        "d2 aa 00 0e 01 00 02 f5 03 18 64 04 18 64 05 18 64 06 18 64 07 18 64 08 43 0d 00 a0 09 43 15 03 26"
    )

    decoded = protocol.decode_cbor_update(status)

    assert decoded[protocol.SPP_FIRMWARE_VERSION_KEY] == 14
    assert decoded[protocol.SPP_MODE_KEY] == 0
    assert decoded[protocol.SPP_SWITCH_KEY] is True
    assert decoded[protocol.SPP_CHANNEL_KEYS[0]] == 100
    assert decoded[8] == bytes.fromhex("0d00a0")


def test_cbor_signed_timezone_offset():
    packet = protocol.cbor_map({protocol.WIFI_TZ_OFFSET_KEY: -150})
    decoded = protocol.decode_cbor_map(packet)
    assert decoded[protocol.WIFI_TZ_OFFSET_KEY] == -150
