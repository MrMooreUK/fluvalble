"""Tests for BLE client packet handling and reconnect scheduling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
        client = Client(ble_device)
    return client


def test_notify_callback_ignores_short_notifications():
    client = _make_client()
    update_callback = MagicMock()
    client.update_callback = update_callback

    client.notify_callback(MagicMock(), bytearray([0x54, 0x55]))

    update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_send_restarts_ping_loop_after_idle_disconnect():
    client = _make_client()
    client.ping_task = None

    with patch(
        "asyncio.create_task", side_effect=lambda coro: _FakeTask(coro)
    ) as create_task:
        client.send(bytes([0x68, 0x03, 0x01]))

    assert client.send_queue == [bytes([0x68, 0x03, 0x01])]
    assert client.ping_task is not None
    create_task.assert_called_once()


@pytest.mark.asyncio
async def test_send_after_stopped_client_does_not_restart_ping_loop():
    client = _make_client()
    client._stopped = True
    client.ping_task = None

    with patch("asyncio.create_task") as create_task:
        client.send(bytes([0x68, 0x03, 0x01]))

    assert client.send_queue == [bytes([0x68, 0x03, 0x01])]
    assert client.ping_task is None
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_ping_loop_keeps_connected_after_idle_window_expires():
    client = _make_client()
    bleak_client = MagicMock()
    bleak_client.is_connected = True
    bleak_client.read_gatt_char = AsyncMock()
    bleak_client.disconnect = AsyncMock()
    client.client = bleak_client
    client.ping_time = 0

    await client._ping_loop()

    bleak_client.disconnect.assert_not_called()
