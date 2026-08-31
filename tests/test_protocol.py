"""Tests for Fluval packet builders."""

from datetime import datetime, timezone

import pytest

from custom_components.fluvalble.core import protocol


def test_wifi_all_zone_packet_contains_manual_key_and_channel_values():
    packet = protocol.wifi_all_zone_packet([10, 20, 30, 40, 50])

    decoded = protocol.decode_cbor_map(packet)

    assert decoded[protocol.WIFI_MANUAL_KEY] == 0
    assert decoded[protocol.WIFI_CHANNEL_KEYS[0]] == 10
    assert decoded[protocol.WIFI_CHANNEL_KEYS[4]] == 50


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


def test_cbor_signed_timezone_offset():
    packet = protocol.cbor_map({protocol.WIFI_TZ_OFFSET_KEY: -150})
    decoded = protocol.decode_cbor_map(packet)
    assert decoded[protocol.WIFI_TZ_OFFSET_KEY] == -150
