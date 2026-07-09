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
