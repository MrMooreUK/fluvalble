"""
Tests for the Device class — state decoding, availability and handler dispatch.

All HA and BLE stubs are registered by conftest.py before this module loads.
"""
import sys
import os
from unittest.mock import MagicMock, patch

# conftest.py registers all stubs before collection; just ensure path is set.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.fluvalble.core.device import Device, MODES, ALL_CHANNELS


def _make_device(name="Test Light"):
    ble_device = MagicMock()
    ble_device.address = "AA:BB:CC:DD:EE:FF"
    advertisement = MagicMock()
    advertisement.rssi = -70

    # Patch out Client so no real BLE tasks start.
    # Configure the mock client instance so device.mac (client.device.address)
    # returns the expected value.
    with patch("custom_components.fluvalble.core.device.Client") as MockClient:
        mock_client = MagicMock()
        mock_client.device.address = "AA:BB:CC:DD:EE:FF"
        MockClient.return_value = mock_client
        device = Device(name, ble_device, advertisement)
        device.client = mock_client
    return device


class TestDeviceInit:
    def test_initial_values(self):
        device = _make_device()
        assert device.connected is False
        for ch in ALL_CHANNELS:
            assert device.values[ch] == 0
        assert device.values["mode"] == "manual"
        assert device.values["led_on_off"] is False

    def test_name_stored(self):
        device = _make_device("My Fluval")
        assert device.name == "My Fluval"

    def test_mac_exposed(self):
        device = _make_device()
        assert device.mac == "AA:BB:CC:DD:EE:FF"


class TestModelName:
    def test_four_channel_model(self):
        device = _make_device()
        device._channel_count = 4
        assert device.model_name == "Aquasky 2.0"

    def test_five_channel_model(self):
        device = _make_device()
        device._channel_count = 5
        assert device.model_name == "Aquarium LED 3.0"


class TestDecodeUpdatePacket:
    def _make_packet(self, mode=0x00, led=0x01, channels=None, five_channel=False):
        """Build a minimal valid state packet."""
        channels = channels or [100, 200, 300, 400, 500]
        data = bytearray(15 if five_channel else 13)
        data[2] = mode
        data[3] = led
        for i, val in enumerate(channels[:4]):
            data[5 + i * 2] = (val >> 8) & 0xFF
            data[6 + i * 2] = val & 0xFF
        if five_channel and len(channels) >= 5:
            data[13] = (channels[4] >> 8) & 0xFF
            data[14] = channels[4] & 0xFF
        return data

    def test_mode_manual_decoded(self):
        device = _make_device()
        device.decode_update_packet(self._make_packet(mode=0x00))
        assert device.values["mode"] == MODES[0]

    def test_mode_automatic_decoded(self):
        device = _make_device()
        device.decode_update_packet(self._make_packet(mode=0x01))
        assert device.values["mode"] == MODES[1]

    def test_mode_professional_decoded(self):
        device = _make_device()
        device.decode_update_packet(self._make_packet(mode=0x02))
        assert device.values["mode"] == MODES[2]

    def test_led_on(self):
        device = _make_device()
        device.decode_update_packet(self._make_packet(led=0x01))
        assert device.values["led_on_off"] is True

    def test_led_off(self):
        device = _make_device()
        device.decode_update_packet(self._make_packet(led=0x00))
        assert device.values["led_on_off"] is False

    def test_channel_values_decoded(self):
        device = _make_device()
        device.decode_update_packet(
            self._make_packet(mode=0x00, channels=[100, 200, 300, 400, 0])
        )
        assert device.values["channel_1"] == 100
        assert device.values["channel_2"] == 200
        assert device.values["channel_3"] == 300
        assert device.values["channel_4"] == 400

    def test_five_channel_detected(self):
        device = _make_device()
        assert device._channel_count == 4
        device.decode_update_packet(
            self._make_packet(channels=[10, 20, 30, 40, 50], five_channel=True)
        )
        assert device._channel_count == 5
        assert device.values["channel_5"] == 50

    def test_short_packet_ignored(self):
        device = _make_device()
        original = dict(device.values)
        device.decode_update_packet(bytearray([0x01, 0x02]))  # too short
        # Values should be unchanged
        assert device.values == original

    def test_component_handlers_called_after_decode(self):
        device = _make_device()
        handler = MagicMock()
        device.updates_component.append(handler)
        device.decode_update_packet(self._make_packet())
        handler.assert_called_once()


class TestConnectionHandlers:
    def test_connect_handlers_called_on_set_connected(self):
        device = _make_device()
        connect_handler = MagicMock()
        component_handler = MagicMock()
        device.updates_connect.append(connect_handler)
        device.updates_component.append(component_handler)

        device._fire_connect_handlers()

        connect_handler.assert_called_once()
        # Component handlers are also notified so entities can update availability
        component_handler.assert_called_once()

    def test_deregister_connect_handler(self):
        device = _make_device()
        handler = MagicMock()
        device.register_update("connection", handler)
        assert handler in device.updates_connect
        device.deregister_update("connection", handler)
        assert handler not in device.updates_connect

    def test_deregister_component_handler(self):
        device = _make_device()
        handler = MagicMock()
        device.register_update("channel_1", handler)
        assert handler in device.updates_component
        device.deregister_update("channel_1", handler)
        assert handler not in device.updates_component
