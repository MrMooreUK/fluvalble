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
        "presets": [
            [1, 2, 3, 4, 5],
            [6, 7, 8, 9, 10],
            [11, 12, 13, 14, 15],
            [16, 17, 18, 19, 20],
        ],
    }


def test_decode_old_manual_state_preserves_four_channel_presets():
    body = bytearray((0, 1, 0))
    for value in (1000, 750, 500, 250):
        body.extend((value & 0xFF, value >> 8))
    body.extend((10, 20, 30, 40, 11, 21, 31, 41, 12, 22, 32, 42, 13, 23, 33, 43))

    decoded = protocol.decode_old_state_packet(_old_state_packet(body), channel_count=4)

    assert decoded is not None
    assert decoded["presets"] == [
        [10, 20, 30, 40],
        [11, 21, 31, 41],
        [12, 22, 32, 42],
        [13, 23, 33, 43],
    ]


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


def test_decode_old_manual_state_rejects_out_of_range_fixture_values():
    body = bytearray((0, 1, 0))
    for value in (1000, 750, 500, 250):
        body.extend((value & 0xFF, value >> 8))
    body.extend(bytes(16))

    invalid_channel = bytearray(body)
    invalid_channel[3:5] = bytes((0xE9, 0x03))  # 1001 on the APK's 0-1000 wire scale.
    assert protocol.decode_old_state_packet(_old_state_packet(invalid_channel), channel_count=4) is None

    invalid_preset = bytearray(body)
    invalid_preset[11] = 101
    assert protocol.decode_old_state_packet(_old_state_packet(invalid_preset), channel_count=4) is None


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


def test_classic_power_packet_is_encoded_once_like_apk(monkeypatch):
    """The APK builder's checksum must not be checksummed a second time."""
    plaintext = protocol.old_switch_packet(False)

    assert plaintext == bytes.fromhex("68 03 00 6b")
    monkeypatch.setattr("custom_components.fluvalble.core.encryption.random.randint", lambda *_: 0)
    assert protocol.encrypted_old_packet(plaintext) == bytes.fromhex("54 51 54 68 03 00 6b")


def test_classic_transport_rejects_unchecksummed_and_double_checksummed_frames():
    with pytest.raises(ValueError):
        protocol.encrypted_old_frames(bytes.fromhex("68 03 00"))
    with pytest.raises(ValueError):
        protocol.encrypted_old_frames(bytes.fromhex("68 03 00 6b 00"))


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


def test_old_all_zone_packet_matches_apk_big_endian_words():
    packet = protocol.old_all_zone_packet([0, 50, 100, 25])

    assert packet == bytes.fromhex("68 04 00 00 01 F4 03 E8 00 FA 88")


def test_old_all_zone_packet_clamps_and_encodes_five_channels():
    packet = protocol.old_all_zone_packet([-1, 20, 30, 40, 101])

    assert packet == bytes.fromhex("68 04 00 00 00 C8 01 2C 01 90 03 E8 F3")


@pytest.mark.parametrize(
    ("slot_index", "expected"),
    [
        (0, "68 06 00 6E"),
        (1, "68 06 01 6F"),
        (2, "68 06 02 6C"),
        (3, "68 06 03 6D"),
    ],
)
def test_old_save_manual_preset_packet_matches_apk_slots(slot_index, expected):
    assert protocol.old_save_manual_preset_packet(slot_index) == bytes.fromhex(expected)


@pytest.mark.parametrize("slot_index", [-1, 4, True, 1.5])
def test_old_save_manual_preset_packet_rejects_invalid_slots(slot_index):
    with pytest.raises(ValueError, match="between 0 and 3"):
        protocol.old_save_manual_preset_packet(slot_index)


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


def test_classic_native_auto_decoder_rejects_invalid_shapes_and_ramps():
    valid = bytes((1, 8, 0, 9, 0, 80, 70, 60, 50, 20, 0, 21, 0, 0, 10, 0, 0))
    excessive_ramp = bytes((1, 8, 0, 13, 0, 80, 70, 60, 50, 20, 0, 21, 0, 0, 10, 0, 0))

    assert protocol.decode_old_auto_schedule(valid + b"\x00", channel_count=4) is None
    assert protocol.decode_old_auto_schedule(excessive_ramp, channel_count=4) is None


def test_classic_native_pro_decoder_rejects_invalid_count_and_shape():
    too_few = bytes((2, 3)) + bytes(3 * 6)
    valid = bytes((2, 4)) + bytes(4 * 6)

    assert protocol.decode_old_pro_schedule(too_few, channel_count=4) is None
    assert protocol.decode_old_pro_schedule(valid + b"\x00", channel_count=4) is None


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


def test_current_rgbw_effect_packet_accepts_apk_eleven_effect_catalogue():
    assert protocol.spp_effect_packet(11, maximum_effect_id=11) == bytes.fromhex("d1 a1 0e 0b")


def test_wifi_auto_schedule_requires_one_complete_apk_state_set():
    assert protocol.decode_wifi_auto_schedule({protocol.WIFI_AUTO_SUNRISE_KEY: [480, 540]}) is None
    assert protocol.decode_wifi_auto_schedule({}, channel_count=3) is None
    data = {
        protocol.WIFI_AUTO_SUNRISE_KEY: [True, 540],
        protocol.WIFI_AUTO_SUNSET_KEY: [1200, 1260],
        protocol.WIFI_AUTO_SLEEP_KEY: 1380,
        protocol.WIFI_AUTO_DAY_LEVELS_KEY: bytes((80, 70, 60, 50)),
        protocol.WIFI_AUTO_NIGHT_LEVELS_KEY: bytes((0, 5, 0, 0)),
    }
    assert protocol.decode_wifi_auto_schedule(data) is None


def test_wifi_pro_schedule_rejects_non_apk_channel_width():
    assert protocol.decode_wifi_pro_schedule({}, channel_count=3) is None
    assert (
        protocol.decode_wifi_pro_schedule(
            {
                protocol.WIFI_PRO_COUNT_KEY: True,
                protocol.WIFI_PRO_TIMES_KEY: [0],
                protocol.WIFI_PRO_LEVELS_KEY: bytes(4),
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "updates",
    [
        {protocol.SPP_AUTO_SUNRISE_KEY: bytes((24, 0, 60))},
        {protocol.SPP_AUTO_SUNRISE_KEY: bytes((8, 60, 60))},
        {protocol.SPP_AUTO_SUNRISE_KEY: bytes((8, 0, 241))},
        {protocol.SPP_AUTO_SUNSET_KEY: bytes((20, 60, 45))},
        {protocol.SPP_AUTO_SLEEP_KEY: bytes((0xFF, 0))},
        {protocol.SPP_AUTO_DAY_LEVELS_KEY: bytes((80, 70, 60, 50, 101))},
        {protocol.SPP_AUTO_NIGHT_LEVELS_KEY: bytes((0, 5, 0, 0))},
    ],
)
def test_plant_pro_auto_schedule_rejects_malformed_apk_fields(updates):
    data = {
        protocol.SPP_AUTO_SUNRISE_KEY: bytes((8, 0, 60)),
        protocol.SPP_AUTO_SUNSET_KEY: bytes((20, 30, 45)),
        protocol.SPP_AUTO_SLEEP_KEY: bytes((23, 15)),
        protocol.SPP_AUTO_DAY_LEVELS_KEY: bytes((80, 70, 60, 50, 40)),
        protocol.SPP_AUTO_NIGHT_LEVELS_KEY: bytes((0, 5, 0, 0, 0)),
    }
    data.update(updates)

    assert protocol.decode_spp_auto_schedule(data) is None


@pytest.mark.parametrize(
    "blob",
    [
        bytes((3,)) + bytes(3 * 7),
        bytes((13,)) + bytes(13 * 7),
        bytes((4,)) + bytes(4 * 7 - 1),
        bytes((4,)) + bytes(4 * 7 + 1),
        bytes((4, 24, 0)) + bytes(5) + bytes(3 * 7),
        bytes((4, 8, 60)) + bytes(5) + bytes(3 * 7),
        bytes((4, 8, 0, 101)) + bytes(4) + bytes(3 * 7),
    ],
)
def test_plant_pro_pro_schedule_rejects_malformed_apk_blob(blob):
    assert protocol.decode_spp_pro_schedule({protocol.SPP_PRO_SCHEDULE_KEY: blob}) is None


def test_schedule_readback_decoders_accept_apk_payloads():
    wifi_auto = {
        protocol.WIFI_AUTO_SUNRISE_KEY: [480, 540],
        protocol.WIFI_AUTO_SUNSET_KEY: [1215, 1260],
        protocol.WIFI_AUTO_SLEEP_KEY: 1350,
        protocol.WIFI_AUTO_DAY_LEVELS_KEY: bytes((80, 70, 60, 50)),
        protocol.WIFI_AUTO_NIGHT_LEVELS_KEY: bytes((0, 10, 0, 0)),
    }
    assert protocol.decode_wifi_auto_schedule(wifi_auto) == {
        "sunrise": {"hour": 8, "minute": 0, "ramp": 60},
        "sunset": {"hour": 21, "minute": 0, "ramp": 45},
        "sleep": {"hour": 22, "minute": 30},
        "day_levels": [80, 70, 60, 50],
        "night_levels": [0, 10, 0, 0],
    }

    wifi_pro = {
        protocol.WIFI_PRO_COUNT_KEY: 4,
        protocol.WIFI_PRO_TIMES_KEY: [480, 600, 750, 1200],
        protocol.WIFI_PRO_LEVELS_KEY: bytes((1, 2, 3, 4, 5, 6, 7, 8, 10, 20, 30, 40, 0, 0, 0, 0)),
    }
    assert [point["minute"] for point in protocol.decode_wifi_pro_schedule(wifi_pro) or []] == [480, 600, 750, 1200]

    spp_auto = {
        protocol.SPP_AUTO_SUNRISE_KEY: bytes((8, 0, 60)),
        protocol.SPP_AUTO_SUNSET_KEY: bytes((20, 30, 45)),
        protocol.SPP_AUTO_SLEEP_KEY: bytes((23, 15)),
        protocol.SPP_AUTO_DAY_LEVELS_KEY: bytes((80, 70, 60, 50, 40)),
        protocol.SPP_AUTO_NIGHT_LEVELS_KEY: bytes((0, 5, 0, 0, 0)),
    }
    assert protocol.decode_spp_auto_schedule(spp_auto)["day_levels"] == [80, 70, 60, 50, 40]

    spp_pro = {
        protocol.SPP_PRO_SCHEDULE_KEY: bytes(
            (
                4,
                8,
                0,
                0,
                0,
                0,
                0,
                0,
                10,
                0,
                20,
                20,
                20,
                20,
                20,
                12,
                30,
                80,
                70,
                60,
                50,
                40,
                20,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        )
    }
    assert [point["time"] for point in protocol.decode_spp_pro_schedule(spp_pro) or []] == [
        "08:00",
        "10:00",
        "12:30",
        "20:00",
    ]

    old_auto = bytes((1, 8, 0, 9, 0, 80, 70, 60, 50, 20, 0, 21, 0, 0, 10, 0, 0, 1, 22, 30))
    assert protocol.decode_old_auto_schedule(old_auto, channel_count=4)["sleep"] == {"hour": 22, "minute": 30}

    old_pro = bytes((2, 4, 8, 0, 1, 2, 3, 4, 10, 0, 5, 6, 7, 8, 12, 30, 10, 20, 30, 40, 20, 0, 0, 0, 0, 0))
    assert [point["minute"] for point in protocol.decode_old_pro_schedule(old_pro, channel_count=4) or []] == [
        480,
        600,
        750,
        1200,
    ]


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
