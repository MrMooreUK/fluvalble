"""Tests for BLE client notification and write behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.fluvalble.core.client import Client


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


def test_send_now_writes_all_facebd_command_targets():
    asyncio.run(_async_test_send_now_writes_all_facebd_command_targets())


async def _async_test_send_now_writes_all_facebd_command_targets():
    client = _make_client()
    client.raw_facebd = True
    client.command_write_uuid = "FACEBD80-7261-6262-6974-696F74626C65"
    client.command_write_uuids = [
        "FACEBD80-7261-6262-6974-696F74626C65",
        "FACEBD01-7261-6262-6974-696F74626C65",
    ]
    client.wake_read_uuid = None
    client._ensure_client = AsyncMock(return_value=MagicMock())
    client._write_packet = AsyncMock()
    client.request_state = AsyncMock()
    client.ping = MagicMock()

    assert await client.send_now(bytes([0xA1, 0x18, 0x6D, 0x00]))

    assert client._write_packet.await_count == 2
    assert client.last_write_targets == client.command_write_uuids
    client.request_state.assert_awaited_once()
    client.ping.assert_called_once()
