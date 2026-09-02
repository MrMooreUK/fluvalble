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
        if on_write := getattr(self, "on_write", None):
            on_write(uuid, bytes(data), response)

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


def _make_client(address="AA:BB:CC:DD:EE:FF", *, active_time=120, ping_interval=10):
    ble_device = MagicMock()
    ble_device.address = address
    with patch("asyncio.create_task", side_effect=lambda coro: _FakeTask(coro)):
        return Client(
            ble_device,
            active_time=active_time,
            ping_interval=ping_interval,
        )


def _facebd_characteristics():
    return [
        _FakeCharacteristic(client_module.FACEBD_COMMAND_WRITE_UUIDS[0], ["write"]),
        _FakeCharacteristic(client_module.NOTIFY_UUIDS[0], ["notify", "read"]),
        _FakeCharacteristic(client_module.NOTIFY_UUIDS[4], ["write", "notify", "read"]),
        _FakeCharacteristic(client_module.WAKE_READ_UUIDS[2], ["read"]),
    ]


def _plant_pro_characteristics():
    return [
        _FakeCharacteristic(
            client_module.SPP_COMMAND_WRITE_UUIDS[0],
            ["write", "write-without-response"],
        ),
        _FakeCharacteristic(
            "0000fff1-0000-1000-8000-00805f9b34fb",
            ["notify"],
        ),
        _FakeCharacteristic(
            client_module.LEGACY_COMMAND_WRITE_UUIDS[0],
            ["write"],
        ),
    ]


def _classic_characteristics():
    return [
        _FakeCharacteristic(
            client_module.LEGACY_COMMAND_WRITE_UUIDS[0],
            ["write", "write-without-response"],
        ),
        _FakeCharacteristic(
            "00001002-0000-1000-8000-00805f9b34fb",
            ["notify"],
        ),
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


def test_plant_pro_notify_callback_forwards_d2_status_frame():
    client = _make_client()
    client.raw_facebd = True
    client.plant_pro_spp = True
    update_callback = MagicMock(return_value=True)
    client.update_callback = update_callback

    client.notify_callback(MagicMock(), bytearray.fromhex("d2 a1 02 f5"))

    update_callback.assert_called_once_with(bytes.fromhex("d2 a1 02 f5"))
    assert client.last_confirmed_state == {protocol.SPP_SWITCH_KEY: True}


def test_send_now_paces_commands_for_resolved_transport():
    asyncio.run(_async_test_send_now_paces_commands_for_resolved_transport())


async def _async_test_send_now_paces_commands_for_resolved_transport():
    cases = (
        (_classic_characteristics(), client_module.CLASSIC_COMMAND_GAP),
        (_facebd_characteristics(), client_module.COMMAND_GAP),
        (_plant_pro_characteristics(), client_module.COMMAND_GAP),
    )

    for characteristics, expected_gap in cases:
        client = _make_client()
        client.client = _FakeGattClient(characteristics)

        await client._resolve_characteristics()
        client.last_command_at = 100.0
        client.ping = MagicMock()

        with (
            patch.object(client_module.time, "time", return_value=100.0),
            patch.object(client_module.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            assert await client.send_now(b"\x68\x03\x01\x6a", verify=False)

        assert sleep.await_count == 1
        assert sleep.await_args.args[0] == pytest.approx(expected_gap)


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


def test_facebd_write_packet_chunks_native_schedule_at_att_limit():
    asyncio.run(_async_test_facebd_write_packet_chunks_native_schedule_at_att_limit())


async def _async_test_facebd_write_packet_chunks_native_schedule_at_att_limit():
    client = _make_client()
    client.raw_facebd = True
    mock_client = MagicMock()
    mock_client.write_gatt_char = AsyncMock()
    mock_client.mtu_size = 23
    client.client = mock_client

    characteristic = MagicMock()
    characteristic.properties = ["write", "write-without-response"]
    characteristic.max_write_without_response_size = 20
    client._get_characteristic = MagicMock(return_value=characteristic)
    packet = bytes(range(45))

    with patch("custom_components.fluvalble.core.client.asyncio.sleep", new=AsyncMock()) as sleep:
        await client._write_packet("FACEBD01-7261-6262-6974-696F74626C65", packet)

    assert [call.kwargs["data"] for call in mock_client.write_gatt_char.await_args_list] == [
        packet[:20],
        packet[20:40],
        packet[40:],
    ]
    assert all(call.kwargs["response"] is False for call in mock_client.write_gatt_char.await_args_list)
    assert sleep.await_count == 2


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


def test_plant_pro_profile_prefers_spp_endpoint_over_legacy():
    asyncio.run(_async_test_plant_pro_profile_prefers_spp_endpoint_over_legacy())


async def _async_test_plant_pro_profile_prefers_spp_endpoint_over_legacy():
    client = _make_client()
    client.client = _FakeGattClient(_plant_pro_characteristics())

    await client._resolve_characteristics()

    assert client.profile == "plant_pro_spp"
    assert client.plant_pro_spp is True
    assert client.raw_facebd is True
    assert client.wifi_facebd is False
    assert client.command_write_uuids == [
        client_module.SPP_COMMAND_WRITE_UUIDS[0],
        client_module.LEGACY_COMMAND_WRITE_UUIDS[0],
    ]
    assert client.command_write_uuid.lower().startswith("0000fff2")
    assert client.notify_uuid.lower().startswith("0000fff1")


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


def test_send_now_writes_raw_plant_pro_command_and_verifies_status(monkeypatch):
    asyncio.run(_async_test_send_now_writes_raw_plant_pro_command(monkeypatch))


async def _async_test_send_now_writes_raw_plant_pro_command(monkeypatch):
    monkeypatch.setattr(client_module, "POST_WRITE_STATE_DELAY", 0)
    status = bytes.fromhex("d2 a1 02 f5")
    gatt = _FakeGattClient(_plant_pro_characteristics(), state=status)
    client = _make_client()
    client.client = gatt
    client.update_callback = lambda data: protocol.decode_cbor_update(data) is not None
    client.ping = MagicMock()
    await client._resolve_characteristics()
    gatt.on_write = lambda _uuid, data, _response: (
        client.notify_callback(MagicMock(), bytearray(status)) if data != protocol.SPP_READ_PARAMS_PACKET else None
    )

    assert await client.send_now(
        protocol.spp_switch_packet(True),
        expected_state={protocol.SPP_SWITCH_KEY: True},
    )

    assert gatt.writes == [
        (
            client_module.SPP_COMMAND_WRITE_UUIDS[0],
            bytes.fromhex("d1 a1 02 f5"),
            False,
        )
    ]
    assert client.last_write_verified is True


def test_plant_pro_request_state_writes_d0ff_and_waits_for_status():
    asyncio.run(_async_test_plant_pro_request_state_writes_d0ff())


async def _async_test_plant_pro_request_state_writes_d0ff():
    status = bytes.fromhex("d2 a1 02 f5")
    gatt = _FakeGattClient(_plant_pro_characteristics(), state=status)
    client = _make_client()
    client.client = gatt
    client.update_callback = lambda data: protocol.decode_cbor_update(data) is not None
    await client._resolve_characteristics()
    gatt.on_write = lambda _uuid, data, _response: (
        client.notify_callback(MagicMock(), bytearray(status)) if data == protocol.SPP_READ_PARAMS_PACKET else None
    )

    assert await client.request_state()
    assert gatt.writes[0][1] == protocol.SPP_READ_PARAMS_PACKET


def test_classic_request_state_writes_existing_read_params_command():
    asyncio.run(_async_test_classic_request_state_writes_existing_read_params_command())


async def _async_test_classic_request_state_writes_existing_read_params_command():
    client = _make_client()
    client.client = _FakeGattClient(
        [
            _FakeCharacteristic(client_module.LEGACY_COMMAND_WRITE_UUIDS[0], ["write"]),
            _FakeCharacteristic("00001002-0000-1000-8000-00805f9b34fb", ["notify"]),
        ]
    )
    await client._resolve_characteristics()

    async def write_and_confirm(_uuid, _data):
        client._state_update_event.set()

    client._write_packet = AsyncMock(side_effect=write_and_confirm)

    assert await client.request_state()
    client._write_packet.assert_awaited_once_with(client.init_write_uuid, protocol.old_read_params_packet())


def test_raw_connect_initialization_follows_apk_order():
    asyncio.run(_async_test_raw_connect_initialization_follows_apk_order())


async def _async_test_raw_connect_initialization_follows_apk_order():
    client = _make_client()
    client.connect_task = None
    client.raw_facebd = True
    client.wake_read_uuid = None
    client.init_write_uuid = None
    connected = SimpleNamespace(is_connected=True)
    client._ensure_client = AsyncMock(return_value=connected)
    client.ping = MagicMock()
    events = []

    async def send_clock():
        events.append("clock")

    async def read_state(_expected_state=None):
        events.append("state")
        client._observed_state = {protocol.WIFI_TZ_OFFSET_KEY: 0}
        return True

    async def send_timezone(state):
        assert state == {protocol.WIFI_TZ_OFFSET_KEY: 0}
        events.append("timezone")

    client.ready_callback = send_clock
    client.request_state = AsyncMock(side_effect=read_state)
    client.state_ready_callback = send_timezone

    await client._connect()

    assert events == ["clock", "state", "timezone"]
    client.ping.assert_called_once()


def test_classic_connect_initialization_follows_apk_order():
    asyncio.run(_async_test_classic_connect_initialization_follows_apk_order())


async def _async_test_classic_connect_initialization_follows_apk_order():
    client = _make_client()
    client.connect_task = None
    client.raw_facebd = False
    client.wake_read_uuid = None
    client.init_write_uuid = "classic-init"
    connected = SimpleNamespace(is_connected=True)
    client._ensure_client = AsyncMock(return_value=connected)
    client.ping = MagicMock()
    events = []

    async def send_clock():
        events.append("clock")

    async def write_state(_uuid, _packet):
        events.append("state")

    async def finish_state(state):
        assert state == {}
        events.append("finish")

    client.ready_callback = send_clock
    client._write_packet = AsyncMock(side_effect=write_state)
    client.state_ready_callback = finish_state

    await client._connect()

    assert events == ["clock", "state", "finish"]
    client._write_packet.assert_awaited_once_with("classic-init", protocol.old_read_params_packet())


def test_device_provider_refreshes_adapter_route():
    old = SimpleNamespace(address="AA", name="old", details={"source": "local"})
    proxy = SimpleNamespace(address="AA", name="proxy", details={"source": "esphome"})
    provider = MagicMock(return_value=proxy)
    with patch("asyncio.create_task", side_effect=lambda coro: _FakeTask(coro)):
        client = Client(old, device_provider=provider)

    assert client._current_device() is proxy
    assert client.device.details["source"] == "esphome"


def test_fresh_connection_uses_one_connector_retry_cycle():
    asyncio.run(_async_test_fresh_connection_uses_one_connector_retry_cycle())


async def _async_test_fresh_connection_uses_one_connector_retry_cycle():
    client = _make_client()
    connected_route = client.device
    later_advertisement_route = SimpleNamespace(
        address=connected_route.address,
        details={"source": "later-advertisement"},
    )
    connection_ready = MagicMock()
    client.connection_ready_callback = connection_ready
    connected = SimpleNamespace(
        is_connected=True,
        start_notify=AsyncMock(),
        _connected_scanner=SimpleNamespace(source="confirmed-connection-route"),
    )
    client._resolve_characteristics = AsyncMock()

    async def establish_connection(*_args, **_kwargs):
        client.device = later_advertisement_route
        return connected

    with patch(
        "custom_components.fluvalble.core.client.establish_connection",
        new=AsyncMock(side_effect=establish_connection),
    ) as establish:
        result = await client._ensure_client()

    assert result is connected
    connection_ready.assert_called_once_with(connected_route, "confirmed-connection-route")
    establish.assert_awaited_once()
    assert establish.await_args.kwargs["max_attempts"] == client_module.CONNECT_RETRIES
    assert establish.await_args.kwargs["disconnected_callback"] == client._on_disconnected


def test_disconnected_client_is_replaced_instead_of_reused():
    asyncio.run(_async_test_disconnected_client_is_replaced_instead_of_reused())


async def _async_test_disconnected_client_is_replaced_instead_of_reused():
    client = _make_client()
    stale = SimpleNamespace(is_connected=False, disconnect=AsyncMock())
    fresh = SimpleNamespace(is_connected=True, start_notify=AsyncMock())
    client.client = stale
    client._resolve_characteristics = AsyncMock()

    with patch(
        "custom_components.fluvalble.core.client.establish_connection",
        new=AsyncMock(return_value=fresh),
    ) as establish:
        result = await client._ensure_client()

    assert result is fresh
    stale.disconnect.assert_awaited_once()
    establish.assert_awaited_once()


def test_unexpected_persistent_disconnect_schedules_immediate_reconnect():
    status_callback = MagicMock()
    client = _make_client(active_time=0)
    client.status_callback = status_callback
    connected = MagicMock()
    client.client = connected
    client.ping_future = MagicMock()

    with patch(
        "custom_components.fluvalble.core.client.asyncio.create_task",
        side_effect=lambda coro: _FakeTask(coro),
    ) as create_task:
        client._on_disconnected(connected)

    assert client.client is None
    client.ping_future.cancel.assert_called_once()
    status_callback.assert_called_once_with(False)
    create_task.assert_called_once()


def test_finite_disconnect_does_not_reconnect_until_demand():
    client = _make_client(active_time=120)
    client.connect_task = None
    connected = MagicMock()
    client.client = connected

    with patch("custom_components.fluvalble.core.client.asyncio.create_task") as create_task:
        client._on_disconnected(connected)

    assert client.client is None
    create_task.assert_not_called()


def test_persistent_heartbeat_reconnects_once_after_command_releases():
    asyncio.run(_async_test_persistent_heartbeat_reconnects_once_after_command_releases())


async def _async_test_persistent_heartbeat_reconnects_once_after_command_releases():
    client = _make_client(active_time=0, ping_interval=60)
    client.connect_task = None
    client.wake_read_uuid = "wake"
    client.ping_time = float("inf")
    old = SimpleNamespace(
        is_connected=True,
        read_gatt_char=AsyncMock(return_value=b""),
        disconnect=AsyncMock(),
    )
    fresh = SimpleNamespace(
        is_connected=True,
        read_gatt_char=AsyncMock(return_value=b""),
        start_notify=AsyncMock(),
    )
    client.client = old
    client._resolve_characteristics = AsyncMock()
    heartbeat = asyncio.create_task(client._ping_loop())
    client.ping_task = heartbeat

    for _ in range(10):
        if client.ping_future is not None:
            break
        await asyncio.sleep(0)
    assert client.ping_future is not None

    await client._command_lock.acquire()
    try:
        with patch(
            "custom_components.fluvalble.core.client.establish_connection",
            new=AsyncMock(return_value=fresh),
        ) as establish:
            client._on_disconnected(old)
            await asyncio.sleep(0)
            establish.assert_not_awaited()

            client._command_lock.release()
            for _ in range(10):
                if establish.await_count:
                    break
                await asyncio.sleep(0)
            establish.assert_awaited_once()
            assert client.client is fresh
    finally:
        if client._command_lock.locked():
            client._command_lock.release()
        await client.stop()


def test_stale_disconnect_callback_cannot_clear_new_connection():
    client = _make_client(active_time=0)
    stale = MagicMock()
    current = MagicMock()
    client.client = current

    client._on_disconnected(stale)

    assert client.client is current


def test_final_stop_prevents_disconnect_callback_from_reconnecting():
    client = _make_client(active_time=0)
    client.connect_task = None
    connected = MagicMock()
    client.client = connected
    client._stopping = True

    with patch("custom_components.fluvalble.core.client.asyncio.create_task") as create_task:
        client._on_disconnected(connected)

    assert client.client is None
    create_task.assert_not_called()


def test_persistent_connection_uses_infinite_idle_deadline():
    client = _make_client(active_time=0)
    with patch(
        "custom_components.fluvalble.core.client.asyncio.create_task",
        side_effect=lambda coro: _FakeTask(coro),
    ):
        client.ping()

    assert client.ping_time == float("inf")


def test_disconnect_is_reusable_but_stop_is_final():
    asyncio.run(_async_test_disconnect_is_reusable_but_stop_is_final())


async def _async_test_disconnect_is_reusable_but_stop_is_final():
    client = _make_client(active_time=0)
    client.connect_task = None
    client.client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())

    await client.disconnect()
    assert client._stopping is False

    client.client = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
    await client.stop()
    assert client._stopping is True


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


def test_characteristic_uuid_constants_are_lowercase():
    """ESPHome 2026.x / esp-idf 5.x proxies compare UUIDs case-sensitively."""
    for uuid in (
        *client_module.FACEBD_COMMAND_WRITE_UUIDS,
        *client_module.SPP_COMMAND_WRITE_UUIDS,
        *client_module.LEGACY_COMMAND_WRITE_UUIDS,
        *client_module.NOTIFY_UUIDS,
        *client_module.WAKE_READ_UUIDS,
    ):
        assert uuid == uuid.lower()


def test_get_characteristic_matches_case_insensitively():
    client = _make_client()
    stored = "00001001-0000-1000-8000-00805f9b34fb"
    characteristic = _FakeCharacteristic(stored, ["write"])
    client.client = _FakeGattClient([characteristic])

    found = client._get_characteristic("00001001-0000-1000-8000-00805F9B34FB")

    assert found is characteristic
    assert found.uuid == stored
