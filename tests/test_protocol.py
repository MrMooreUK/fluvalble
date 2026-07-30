"""Tests for Fluval packet builders."""

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
