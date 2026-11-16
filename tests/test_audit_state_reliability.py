"""Adversarial integration-path regressions from the APK/state audit."""

import asyncio
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.device import Device
from custom_components.fluvalble.core.products import PRODUCTS
from tests.test_client import _make_client
from tests.test_last_manual_settings import make_device, report, saved


def test_equal_slider_in_auto_still_selects_manual():
    async def run():
        d = make_device(545, "spp")
        d.values["channel_1"] = 50

        async def send(packet):
            report(d, "spp", [50, 0, 0, 0, 0])
            return True

        d._async_send_packet = AsyncMock(side_effect=send)
        assert await d.async_set_value("channel_1", 50)
        d._async_prepare_command.assert_awaited()
        assert protocol.spp_mode_packet(0) in [c.args[0] for c in d._async_send_packet.await_args_list]
        assert d.values["mode"] == "manual"

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", [("classic", 328), ("facebd", 532), ("spp", 545)])
def test_brightness_uses_reconnect_mix(transport, product):
    async def run():
        d = make_device(product, transport)
        d.values.update(mode="manual", channel_1=100, channel_2=10)

        async def prepare(**kwargs):
            report(d, transport, [10, 100] + [0] * (len(d.numbers()) - 2))
            return True

        d._async_prepare_command = AsyncMock(side_effect=prepare)
        d._async_send_packet = AsyncMock(return_value=True)
        assert await d.async_set_master_brightness(50)
        builder = {
            "classic": protocol.old_all_zone_packet,
            "facebd": protocol.wifi_all_zone_packet,
            "spp": protocol.spp_all_zone_packet,
        }[transport]
        assert d._async_send_packet.await_args.args[0] == builder([5, 50] + [0] * (len(d.numbers()) - 2))

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", [("classic", 328), ("facebd", 532), ("spp", 545)])
def test_effect_failure_keeps_confirmed_partial_operations(transport, product):
    async def run():
        d = make_device(product, transport)
        d.values.update(mode="automatic", led_on_off=False, channel_1=10)
        if transport == "classic":
            d.conn_info["service_uuids"] = ["00001000-0000-1000-8000-00805f9b34fb"]
        builders = {
            "classic": (protocol.old_mode_packet, protocol.old_switch_packet),
            "facebd": (protocol.wifi_mode_packet, protocol.wifi_switch_packet),
            "spp": (protocol.spp_mode_packet, protocol.spp_switch_packet),
        }
        mode, power = builders[transport]

        async def send(packet):
            if packet == mode(0):
                report(d, transport, [10] + [0] * (len(d.numbers()) - 1))
                return True
            if packet == power(True):
                report(d, transport, [77] + [0] * (len(d.numbers()) - 1))
                return True
            return False

        d._async_send_packet = AsyncMock(side_effect=send)
        assert not await d.async_set_effect("Lightning")
        assert (d.values["mode"], d.values["led_on_off"], d.values["channel_1"]) == ("manual", True, 77)

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", [("classic", 328), ("facebd", 532), ("spp", 545)])
def test_clock_uses_ha_timezone_not_process_timezone(transport, product):
    async def run():
        d = make_device(product, transport)
        d.hass = SimpleNamespace()
        local = datetime(2026, 1, 15, 8, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        d._async_send_packet = AsyncMock(return_value=True)
        with patch("custom_components.fluvalble.core.device.dt_util.now", return_value=local):
            assert await d._async_send_clock_command()
            builder = {
                "classic": protocol.old_clock_packet,
                "facebd": protocol.wifi_clock_packet,
                "spp": protocol.mesh_clock_packet,
            }[transport]
            assert d._async_send_packet.await_args.args[0] == builder(local)
            if transport == "facebd":
                assert await d._async_finish_clock_sync({101: 0})
                assert protocol.decode_cbor_update(d._async_send_packet.await_args.args[0]) == {101: -480}
        if transport != "facebd":
            packet = d._async_send_packet.await_args.args[0]
            assert tuple(packet[-4:-2] if transport == "classic" else packet[-3:-1]) == (8, 30)

    asyncio.run(run())


def test_partial_spp_notification_does_not_shrink_five_channels():
    d = make_device(None, "spp")
    report(d, "spp", [10, 20, 30, 40, 50])
    d._decode_spp_update({3: 15})
    assert len(d.numbers()) == 5


def test_first_four_channel_command_saves_actual_width():
    async def run():
        d = make_device(None, "facebd")
        persist = AsyncMock()
        d.configure_manual_settings(None, persist)

        async def prepare(**kwargs):
            report(d, "facebd", [0] * 4)
            return True

        async def send(_packet):
            report(d, "facebd", [50, 20, 0, 0])
            return True

        d._async_prepare_command = AsyncMock(side_effect=prepare)
        d._async_send_packet = AsyncMock(side_effect=send)
        assert await d.async_set_channels({"channel_1": 50, "channel_2": 20})
        persist.assert_awaited_once_with(dict(zip(d.numbers(), [50, 20, 0, 0])))

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["automatic", "professional"])
def test_restore_reads_actual_mode_before_refusing_cached_mode(mode):
    async def run():
        d = make_device()
        d.values["mode"] = mode
        d.configure_manual_settings(saved(d, [40] * 5), AsyncMock())

        async def prepare(**kwargs):
            report(d, "spp", [0] * 5)
            return True

        async def send(_packet):
            report(d, "spp", [40] * 5)
            return True

        d._async_prepare_command = AsyncMock(side_effect=prepare)
        d._async_send_packet = AsyncMock(side_effect=send)
        assert await d.async_restore_last_manual_settings()
        assert protocol.spp_mode_packet(0) not in [c.args[0] for c in d._async_send_packet.await_args_list]

    asyncio.run(run())


def test_mode_contradiction_blocks_following_channel_write():
    async def run():
        d = make_device(532, "facebd")

        async def send(_packet):
            d._decode_wifi_update({103: 1})
            return True

        d._async_send_packet = AsyncMock(side_effect=send)
        assert not await d.async_set_channels({"channel_1": 50})
        d._async_send_packet.assert_awaited_once_with(protocol.wifi_mode_packet(0))

    asyncio.run(run())


def test_classic_initialization_waits_for_received_state():
    async def run():
        c = _make_client()
        d = Device("Offline", config_data={"mac": "AA", "product_id": 328})
        c.client = SimpleNamespace(is_connected=True)
        c._ensure_client = AsyncMock(return_value=c.client)
        c.init_write_uuid = "init"
        c.wake_read_uuid = None
        c._wait_for_command_gap = AsyncMock()
        c.update_callback = d.decode_update_packet
        c.state_ready_callback = AsyncMock()
        delivered = asyncio.Event()

        async def write(_uuid, _packet):
            async def later():
                await asyncio.sleep(0)
                c.state_ready_callback.assert_not_awaited()
                c._dispatch_update(protocol.old_packet(bytes([0x68, 5, 0, 1, 0]) + bytes(24)))
                delivered.set()

            asyncio.create_task(later())

        c._write_packet = AsyncMock(side_effect=write)
        assert await c._initialize_session(c.client)
        assert delivered.is_set()
        c.state_ready_callback.assert_awaited_once()

    asyncio.run(run())


def test_initial_state_timeout_does_not_mark_session_ready():
    async def run():
        c = _make_client()
        c.client = SimpleNamespace(is_connected=True)
        c._ensure_client = AsyncMock(return_value=c.client)
        c.init_write_uuid = "init"
        c.wake_read_uuid = None
        c._wait_for_command_gap = AsyncMock()
        c._write_packet = AsyncMock()
        c.state_ready_callback = AsyncMock()
        with patch("custom_components.fluvalble.core.client.INITIAL_STATE_TIMEOUT", 0.001):
            assert not await c._initialize_session(c.client)
        assert not c._session_initialized
        c.state_ready_callback.assert_not_awaited()

    asyncio.run(run())


def test_read_waits_past_partial_notification_for_expected_fields():
    async def run():
        c = _make_client()
        c.client = SimpleNamespace(is_connected=True)
        c._ensure_client = AsyncMock(return_value=c.client)
        c.raw_facebd = True
        c.spp_transport = True
        c.command_write_uuid = "fff2"
        c.wake_read_uuid = None
        c._wait_for_command_gap = AsyncMock()
        c.update_callback = lambda _packet: True

        async def write(_uuid, _packet):
            async def later():
                c._dispatch_update(bytes([0xD2]) + protocol.cbor_map({1: 0}))
                await asyncio.sleep(0)
                c._dispatch_update(bytes([0xD2]) + protocol.cbor_map({3: 50}))

            asyncio.create_task(later())

        c._write_packet = AsyncMock(side_effect=write)
        assert await c.request_state({1: 0, 3: 50})
        assert c.observed_state == {1: 0, 3: 50}

    asyncio.run(run())


def test_schedule_refresh_rejects_mode_only_readback():
    async def run():
        d = make_device(532, "facebd")
        d._async_ensure_client = AsyncMock(return_value=True)

        async def request(**kwargs):
            d._decode_wifi_update({103: 1, 104: True})
            return kwargs["state_validator"]({103: 1, 104: True})

        d.client = SimpleNamespace(
            ensure_connected=AsyncMock(return_value=True), request_state=AsyncMock(side_effect=request)
        )
        assert not await d.async_refresh_state(schedule="native_auto_schedule")

    asyncio.run(run())


def test_deferred_channel_entities_reconcile_and_clean_registry():
    from custom_components.fluvalble.number import setup_channel_entities
    from custom_components.fluvalble import FluvalRuntimeData

    async def run():
        d = make_device(None, "facebd")
        runtime = FluvalRuntimeData()
        entry = SimpleNamespace(async_on_unload=MagicMock())
        hass = SimpleNamespace(async_create_task=asyncio.create_task)
        added = []
        rows = {}
        registry = SimpleNamespace(
            async_get_entity_id=MagicMock(side_effect=lambda domain, platform, unique_id: rows.get(unique_id)),
            async_remove=MagicMock(side_effect=lambda entity_id: rows.clear()),
        )
        with (
            patch("custom_components.fluvalble.number.require_entry_runtime_data", return_value=runtime),
            patch.dict(
                sys.modules,
                {"homeassistant.helpers.entity_registry": SimpleNamespace(async_get=lambda _hass: registry)},
            ),
        ):
            setup_channel_entities(hass, entry, d, added.extend)
            assert not added
            report(d, "facebd", [0] * 4)
            assert len(added) == 4
            d.product_id = 545
            for handler in list(d.updates_component):
                handler()
            assert len(added) == 5
            added[-1].unique_id = added[-1]._attr_unique_id
            rows[added[-1].unique_id] = "number.extra"
            d.product_id = 532
            for handler in list(d.updates_component):
                handler()
            await asyncio.gather(*runtime.background_tasks)
            registry.async_remove.assert_called_once_with("number.extra")
            entry.async_on_unload.call_args.args[0]()

    asyncio.run(run())


def test_restore_refreshes_mode_on_an_already_connected_session():
    async def run():
        d = make_device()
        d.configure_manual_settings(saved(d, [40] * 5), AsyncMock())
        d._async_prepare_command = Device._async_prepare_command.__get__(d)
        d._async_ensure_client = AsyncMock(return_value=True)

        async def read(**kwargs):
            report(d, "spp", [0] * 5)
            return kwargs["state_validator"]({1: 0})

        d.client = SimpleNamespace(
            ensure_connected=AsyncMock(return_value=True), request_state=AsyncMock(side_effect=read), last_error=None
        )

        async def send(_packet):
            report(d, "spp", [40] * 5)
            return True

        d._async_send_packet = AsyncMock(side_effect=send)
        assert await d.async_restore_last_manual_settings()
        d.client.request_state.assert_awaited_once()
        assert protocol.spp_mode_packet(0) not in [c.args[0] for c in d._async_send_packet.await_args_list]

    asyncio.run(run())


@pytest.mark.parametrize("raises", [False, True])
def test_failed_initial_read_releases_the_connection(raises):
    async def run():
        c = _make_client()
        physical = SimpleNamespace(is_connected=True, disconnect=AsyncMock())
        c.client = physical
        c._ensure_client = AsyncMock(return_value=physical)
        c.request_state = AsyncMock(side_effect=TimeoutError() if raises else None, return_value=False)
        assert not await c.ensure_connected()
        assert c.client is None
        physical.disconnect.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("product", sorted(PRODUCTS))
def test_all_catalogue_products_require_complete_initial_manual_bank(product):
    transport = "facebd" if PRODUCTS[product].channel_count == 4 else "spp"
    d = make_device(product, transport)
    keys = protocol.WIFI_CHANNEL_KEYS if transport == "facebd" else protocol.SPP_CHANNEL_KEYS
    mode, power = (103, 104) if transport == "facebd" else (1, 2)
    fields = {mode: 0, power: True, **dict.fromkeys(keys[: len(d.numbers())], 50)}
    assert d._initial_state_complete(fields)
    del fields[keys[0]]
    assert not d._initial_state_complete(fields)
    assert d._initial_state_complete({mode: 1})
    assert not d._initial_state_complete({power: True})


def test_editor_does_not_write_from_a_cached_schedule_after_mode_only_read():
    from tests.test_schedule_colours import _run_save, auto_schedule

    async def run():
        d = make_device(532, "facebd")
        d.values["native_auto_schedule"] = auto_schedule()
        d.async_refresh_state = Device.async_refresh_state.__get__(d)
        d._async_ensure_client = AsyncMock(return_value=True)

        async def read(**kwargs):
            d._decode_wifi_update({103: 1, 104: True})
            return kwargs.get("state_validator", lambda _state: True)({103: 1, 104: True})

        d.client = SimpleNamespace(
            ensure_connected=AsyncMock(return_value=True), request_state=AsyncMock(side_effect=read)
        )
        d._async_send_packet = AsyncMock(return_value=True)
        return d

    d = asyncio.run(run())
    connection = _run_save(device=d, baseline=auto_schedule())
    d._async_send_packet.assert_not_awaited()
    connection.send_error.assert_called_once()


def test_light_brightness_refreshes_before_reading_the_colour_mix():
    from custom_components.fluvalble.light import FluvalLight

    async def run():
        d = make_device(532, "facebd")
        d.values.update(mode="manual", channel_1=100, channel_2=10)

        async def prepare(**kwargs):
            report(d, "facebd", [10, 100, 0, 0])
            return True

        d._async_prepare_command = AsyncMock(side_effect=prepare)
        d._async_send_packet = AsyncMock(return_value=True)
        entity = FluvalLight(d, "light")
        await entity.async_turn_on(brightness=128)
        assert d._async_send_packet.await_args.args[0] == protocol.wifi_all_zone_packet([5, 50, 0, 0])

    asyncio.run(run())


@pytest.mark.parametrize("unload_ok", [False, True])
def test_reconciler_is_paused_during_platform_unload_and_retained_on_failure(unload_ok):
    import custom_components.fluvalble as integration
    from custom_components.fluvalble.number import setup_channel_entities

    async def run():
        d = make_device(532, "facebd")
        runtime = integration.FluvalRuntimeData(device=d)
        entry = SimpleNamespace(entry_id="fixture", runtime_data=runtime, async_on_unload=MagicMock())
        added = []

        async def unload(_entry, _platforms):
            assert runtime.unloading
            d.product_id = 545
            for handler in list(d.updates_component):
                handler()
            assert len(added) == 4
            return unload_ok

        hass = SimpleNamespace(
            data={"fluvalble": {"fixture": runtime}},
            async_create_task=asyncio.create_task,
            config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(side_effect=unload)),
        )
        registry = SimpleNamespace(async_get_entity_id=lambda *args: None)
        with patch.dict(
            sys.modules, {"homeassistant.helpers.entity_registry": SimpleNamespace(async_get=lambda _: registry)}
        ):
            setup_channel_entities(hass, entry, d, added.extend)
            assert len(added) == 4
            assert await integration.async_unload_entry(hass, entry) is unload_ok
            for handler in list(d.updates_component):
                handler()
            assert len(added) == (4 if unload_ok else 5)
            assert runtime.unloading is unload_ok

    asyncio.run(run())


def test_resolved_layout_removes_an_old_extra_registry_row():
    from custom_components.fluvalble.number import setup_channel_entities
    from custom_components.fluvalble import FluvalRuntimeData

    d = make_device(532, "facebd")
    key = "AABBCCDDEEFF_channel_5"
    rows = {key: "number.old_extra", "OTHERFIXTURE_channel_5": "number.other"}

    def remove(entity_id):
        for unique_id, row in list(rows.items()):
            if row == entity_id:
                del rows[unique_id]

    registry = SimpleNamespace(
        async_get_entity_id=lambda domain, platform, unique_id: rows.get(unique_id),
        async_remove=MagicMock(side_effect=remove),
    )
    runtime = FluvalRuntimeData()
    with (
        patch("custom_components.fluvalble.number.require_entry_runtime_data", return_value=runtime),
        patch.dict(
            sys.modules, {"homeassistant.helpers.entity_registry": SimpleNamespace(async_get=lambda _: registry)}
        ),
    ):
        setup_channel_entities(
            SimpleNamespace(), SimpleNamespace(async_on_unload=MagicMock()), d, lambda entities: None
        )
    assert rows == {"OTHERFIXTURE_channel_5": "number.other"}
    registry.async_remove.assert_called_once_with("number.old_extra")
