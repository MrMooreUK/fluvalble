"""Failure-path checks for command, storage, and unload ordering."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import custom_components.fluvalble as integration
from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.client import Client
from custom_components.fluvalble.core.device import Device


def make_device():
    return Device("Audit", config_data={"mac": "AA:BB:CC:DD:EE:FF", "product_id": 328})


def test_single_channel_request_preserves_other_channels_read_on_reconnect():
    async def run():
        device = make_device()
        device.values.update(led_on_off=True, channel_1=10, channel_2=5)

        async def prepare():
            device.values["channel_2"] = 75
            return True

        device._async_prepare_command = AsyncMock(side_effect=prepare)
        device._async_send_packet = AsyncMock(return_value=True)
        assert await device.async_set_channels({"channel_1": 30})
        assert device.values["channel_2"] == 75
        device._async_send_packet.assert_awaited_once_with(protocol.old_all_zone_packet([30, 75, 0, 0]))

    asyncio.run(run())


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("reported", [False, True])
def test_dst_write_preserves_fresh_readback(success, reported):
    async def run():
        device = Device("Audit", config_data={"mac": "AA:BB:CC:DD:EE:FF", "product_id": 532})
        device.client = SimpleNamespace(
            wifi_facebd=True, spp_transport=False, command_write_uuid="facebd02-7261-6262-6974-696f74626c65"
        )
        device.values["daylight_saving_time"] = not reported
        device._async_prepare_command = AsyncMock(return_value=True)

        async def send(packet):
            assert packet == protocol.wifi_dst_packet(True)
            device._decode_wifi_update({99: reported})
            return success

        device._async_send_packet = AsyncMock(side_effect=send)
        assert await device.async_set_daylight_saving_time(True) is success
        assert device.values["daylight_saving_time"] is reported
        assert device.diagnostics["daylight_saving_time"] is reported

    asyncio.run(run())


@pytest.mark.parametrize("product", [328, 532, 545])
@pytest.mark.parametrize("reported", [0, 90])
def test_channel_failure_keeps_readback_even_when_equal_to_request(product, reported):
    async def run():
        device = Device("Audit", config_data={"mac": "AA:BB:CC:DD:EE:FF", "product_id": product})
        device.client = SimpleNamespace(
            spp_transport=product == 545, wifi_facebd=product == 532, command_write_uuid=None
        )
        device.values.update(led_on_off=True, channel_1=20)
        device._async_prepare_command = AsyncMock(return_value=True)

        async def send(packet):
            if product == 328:
                body = (
                    bytes([0, 1, 0])
                    + b"".join(int(v * 10).to_bytes(2, "little") for v in [reported, 0, 0, 0])
                    + bytes(16)
                )
                raw = bytes([0x68, 5]) + body
                checksum = 0
                for value in raw:
                    checksum ^= value
                device.decode_update_packet(raw + bytes([checksum]))
            elif product == 532:
                device._decode_wifi_update({110: reported})
            else:
                device._decode_spp_update({3: reported})
            return False

        device._async_send_packet = AsyncMock(side_effect=send)
        assert not await device.async_set_channels({"channel_1": 90})
        assert device.values["channel_1"] == reported

    asyncio.run(run())


@pytest.mark.parametrize("duration,interval", [(60, 30), (5, 30), (65, 30)])
def test_channel_transition_uses_full_duration(duration, interval):
    async def run():
        device = make_device()
        clock = [0.0]
        writes = []

        async def sleep(delay):
            clock[0] += delay

        async def write(values, **kwargs):
            writes.append((clock[0], values["channel_1"]))
            return True

        device._async_set_channels_now = AsyncMock(side_effect=write)
        with (
            patch("custom_components.fluvalble.core.device.monotonic", side_effect=lambda: clock[0]),
            patch("custom_components.fluvalble.core.device.asyncio.sleep", side_effect=sleep),
        ):
            assert await device.async_set_channels({"channel_1": 100}, transition=duration, step_seconds=interval)
        assert writes[-1] == (duration, 100)
        assert writes[0][0] > 0

    asyncio.run(run())


def test_failed_channel_preparation_preserves_reconnect_state():
    async def run():
        device = make_device()

        async def prepare():
            device.values.update(mode="professional", channel_1=42)
            return False

        device._async_prepare_command = AsyncMock(side_effect=prepare)
        assert not await device.async_set_channels({"channel_1": 90})
        assert device.values["mode"] == "professional"
        assert device.values["channel_1"] == 42

    asyncio.run(run())


@pytest.mark.parametrize("existing", [True, False])
def test_clock_sync_initializes_without_reentering_clock_lock(existing):
    async def run():
        device = make_device()
        with patch.object(Client, "_connect", new=AsyncMock()):
            client = Client(
                SimpleNamespace(address=device.address),
                ready_callback=device._async_on_client_ready,
                state_ready_callback=device._async_on_client_state_ready,
            )
            await client.connect_task
        underlying = SimpleNamespace(is_connected=True)
        client.client = underlying
        client._ensure_client = AsyncMock(return_value=underlying)
        client.request_state = AsyncMock(return_value=True)
        device._async_send_packet = AsyncMock(return_value=True)

        async def create_client():
            device.client = client
            return True

        device._async_ensure_client = AsyncMock(side_effect=create_client)
        if existing:
            device.client = client
        assert await asyncio.wait_for(device.async_sync_clock(force=True), 1)
        assert client._session_initialized
        assert device._clock_synced
        assert not device._clock_sync_lock.locked()

    asyncio.run(run())


@pytest.mark.parametrize("mode", [False, True])
@pytest.mark.parametrize("write_ok", [False, True])
def test_initial_status_precedes_requested_state(mode, write_ok):
    async def run():
        device = make_device()
        device.client = SimpleNamespace(spp_transport=True)

        async def prepare():
            device._decode_spp_update({protocol.SPP_SWITCH_KEY: False, protocol.SPP_MODE_KEY: 0})
            return True

        device._async_prepare_command = AsyncMock(side_effect=prepare)
        device._async_send_packet = AsyncMock(return_value=write_ok)
        if mode:
            assert await device.async_select_option("mode", "professional") is write_ok
            assert device.values["mode"] == ("professional" if write_ok else "manual")
        else:
            assert await device.async_set_switch("led_on_off", True) is write_ok
            assert device.values["led_on_off"] is write_ok

    asyncio.run(run())


def test_post_write_observation_is_not_overwritten():
    async def run():
        device = make_device()
        device.client = SimpleNamespace(spp_transport=True)
        device._async_prepare_command = AsyncMock(return_value=True)

        async def send(_packet):
            device._decode_spp_update({protocol.SPP_SWITCH_KEY: False})
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        assert await device.async_set_switch("led_on_off", True)
        assert device.values["led_on_off"] is False

    asyncio.run(run())


@pytest.mark.parametrize("response", [False, True])
def test_refresh_propagates_read_result(response):
    async def run():
        device = make_device()
        device.client = SimpleNamespace(
            ensure_connected=AsyncMock(return_value=True), request_state=AsyncMock(return_value=response)
        )
        device._async_ensure_client = AsyncMock(return_value=True)
        assert await device.async_refresh_state() is response

    asyncio.run(run())


@pytest.mark.parametrize("unload_ok", [False, True])
def test_unload_tasks_without_discovered_device(unload_ok):
    async def run():
        runtime = integration.FluvalRuntimeData()
        pending = asyncio.create_task(asyncio.sleep(100))
        runtime.background_tasks.add(pending)
        entry = SimpleNamespace(entry_id="audit", runtime_data=runtime)
        hass = SimpleNamespace(
            data={integration.DOMAIN: {"audit": runtime}},
            config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=unload_ok)),
        )
        try:
            assert await integration.async_unload_entry(hass, entry) is unload_ok
            assert pending.cancelled() is unload_ok
            assert ("audit" in hass.data[integration.DOMAIN]) is not unload_ok
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(run())
