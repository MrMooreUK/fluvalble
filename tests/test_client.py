"""Tests for BLE client notification and write behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core import client as client_module
from custom_components.fluvalble.core.client import Client


class _FakeCharacteristic:
    def __init__(self, uuid, properties):
        self.uuid = uuid
        self.properties = properties


class _FakeServices:
    def __init__(self, characteristics):
        self._characteristics = {characteristic.uuid.lower(): characteristic for characteristic in characteristics}

    def get_characteristic(self, uuid):
        return self._characteristics.get(uuid.lower())


class _FakeGattClient:
    def __init__(self, characteristics, state=b"\x00"):
        self.services = _FakeServices(characteristics)
        self.is_connected = True
        self.state = state
        self.writes = []

    async def read_gatt_char(self, _uuid):
        return self.state

    async def write_gatt_char(self, uuid, data, response):
        self.writes.append((uuid, bytes(data), response))

    async def disconnect(self):
        self.is_connected = False


class _FakeTask:
    """Small task-like object so Client.__init__ does not start real BLE work."""

    def __init__(self, coroutine=None):
        if coroutine is not None:
            coroutine.close()

    def done(self):
        return False

    def cancel(self):
        pass

    def __await__(self):
        if False:
            yield None
        return None


def _make_client(address="AA:BB:CC:DD:EE:FF"):
    ble_device = MagicMock()
    ble_device.address = address
    with patch("asyncio.create_task", side_effect=lambda coro: _FakeTask(coro)):
        return Client(ble_device)


def _facebd_characteristics():
    return [
        _FakeCharacteristic(client_module.FACEBD_COMMAND_WRITE_UUIDS[0], ["write"]),
        _FakeCharacteristic(client_module.NOTIFY_UUIDS[0], ["notify", "read"]),
        _FakeCharacteristic(client_module.NOTIFY_UUIDS[4], ["write", "notify", "read"]),
        _FakeCharacteristic(client_module.WAKE_READ_UUIDS[2], ["read"]),
    ]


def test_old_protocol_notify_callback_flushes_short_final_notifications():
    client = _make_client()
    update_callback = MagicMock()
    client.update_callback = update_callback

    client.notify_callback(MagicMock(), bytearray([0x54, 0x55]))

    update_callback.assert_called_once_with(b"")


def test_raw_facebd_notify_callback_forwards_cbor_payload():
    client = _make_client()
    client.raw_facebd = True
    update_callback = MagicMock()
    client.update_callback = update_callback

    client.notify_callback(MagicMock(), bytearray([0xA1, 0x18, 0x68, 0xF5]))

    update_callback.assert_called_once_with(bytes([0xA1, 0x18, 0x68, 0xF5]))


def test_write_packet_prefers_write_without_response():
    asyncio.run(_async_test_write_packet_prefers_write_without_response())


async def _async_test_write_packet_prefers_write_without_response():
    client = _make_client()
    client.raw_facebd = False
    mock_client = MagicMock()
    mock_client.write_gatt_char = AsyncMock()
    client.client = mock_client

    characteristic = MagicMock()
    characteristic.properties = ["write", "write-without-response"]
    client._get_characteristic = MagicMock(return_value=characteristic)

    with patch(
        "custom_components.fluvalble.core.client.protocol.encrypted_old_packet",
        return_value=bytearray(b"\x54\x01"),
    ):
        await client._write_packet("00001001-0000-1000-8000-00805F9B34FB", bytes([0x68, 0x03, 0x01, 0x6A]))

    kwargs = mock_client.write_gatt_char.await_args.kwargs
    assert kwargs["response"] is False


def test_facebd_profile_uses_command_endpoint_not_provisioning_or_echo():
    asyncio.run(_async_test_facebd_profile_uses_command_endpoint())


async def _async_test_facebd_profile_uses_command_endpoint():
    client = _make_client()
    client.client = _FakeGattClient(_facebd_characteristics())

    await client._resolve_characteristics()

    assert client.profile == "facebd_command"
    assert client.wifi_facebd is True
    assert client.command_write_uuids == [client_module.FACEBD_COMMAND_WRITE_UUIDS[0]]
    assert client.notify_uuid.lower().startswith("facebd02")


def test_send_now_writes_only_facebd01_and_verifies_readback(monkeypatch):
    asyncio.run(_async_test_send_now_writes_only_facebd01(monkeypatch))


async def _async_test_send_now_writes_only_facebd01(monkeypatch):
    monkeypatch.setattr(client_module, "POST_WRITE_STATE_DELAY", 0)
    client = _make_client()
    state = protocol.wifi_switch_packet(True)
    gatt = _FakeGattClient(_facebd_characteristics(), state=state)
    client.client = gatt
    client.update_callback = lambda data: protocol.decode_cbor_map(data) is not None
    client.ping = MagicMock()
    await client._resolve_characteristics()

    assert await client.send_now(
        state,
        expected_state={protocol.WIFI_SWITCH_KEY: True},
    )

    assert len(gatt.writes) == 1
    assert gatt.writes[0][0].lower().startswith("facebd01")
    assert client.last_write_verified is True


def test_unverified_facebd_command_is_retried_and_reports_mismatch(monkeypatch):
    asyncio.run(_async_test_unverified_facebd_command(monkeypatch))


async def _async_test_unverified_facebd_command(monkeypatch):
    monkeypatch.setattr(client_module, "POST_WRITE_STATE_DELAY", 0)
    monkeypatch.setattr(client_module, "WRITE_DELAY", 0)
    monkeypatch.setattr(client_module, "STATE_NOTIFY_TIMEOUT", 0.001)
    state = protocol.wifi_switch_packet(False)
    gatt = _FakeGattClient(_facebd_characteristics(), state=state)
    client = _make_client()
    client.client = gatt
    client.update_callback = lambda data: protocol.decode_cbor_map(data) is not None
    client.ping = MagicMock()
    await client._resolve_characteristics()

    assert await client.send_now(
        protocol.wifi_switch_packet(True),
        expected_state={protocol.WIFI_SWITCH_KEY: True},
    )

    assert len(gatt.writes) == client_module.UNVERIFIED_WRITE_COPIES
    assert client.last_write_verified is False
    assert client.last_verification_mismatches == {
        protocol.WIFI_SWITCH_KEY: {
            "expected": True,
            "confirmed": False,
        }
    }


def test_device_provider_refreshes_adapter_route():
    old = SimpleNamespace(address="AA", name="old", details={"source": "local"})
    proxy = SimpleNamespace(address="AA", name="proxy", details={"source": "esphome"})
    provider = MagicMock(return_value=proxy)
    with patch("asyncio.create_task", side_effect=lambda coro: _FakeTask(coro)):
        client = Client(old, device_provider=provider)

    assert client._current_device() is proxy
    assert client.device.details["source"] == "esphome"


def test_ping_loop_can_be_cancelled_while_waiting():
    asyncio.run(_async_test_ping_loop_can_be_cancelled_while_waiting())


async def _async_test_ping_loop_can_be_cancelled_while_waiting():
    client = _make_client()
    client.client = _FakeGattClient([])
    client.ping_time = float("inf")
    task = asyncio.create_task(client._ping_loop())
    await asyncio.sleep(0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
