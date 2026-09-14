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
