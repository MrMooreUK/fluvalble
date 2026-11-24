"""Regressions for all nine combined-review findings and their boundaries."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.fluvalble import FluvalRuntimeData
from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.products import PRODUCTS
from custom_components.fluvalble.core.schedule_colours import professional_batch_packet, replace_professional_batch
from tests.test_last_manual_settings import make_device, report
from tests.test_device import _old_manual_status
from tests.test_client import _make_client

ROUTES = [("classic", 328), ("facebd", 532), ("spp", 545)]


def test_classic_receive_buffer_discards_orphans_and_resets_on_disconnect():
    from custom_components.fluvalble.core.client import MAX_CLASSIC_RECEIVE_BUFFER
    from custom_components.fluvalble.core.encryption import encrypt

    client = _make_client()
    report = MagicMock(return_value=True)
    client.update_callback = report
    client.notify_callback(None, encrypt(b"\x01" * 15))
    assert not client.receive_buffer
    client.notify_callback(None, encrypt(b"\x68\x05\x01"))
    for _ in range(MAX_CLASSIC_RECEIVE_BUFFER // 15 + 1):
        client.notify_callback(None, encrypt(b"\x01" * 15))
    assert not client.receive_buffer
    client.notify_callback(None, encrypt(b"\x68\x05\x01"))
    assert client.receive_buffer
    client.client = object()
    client._on_disconnected(client.client)
    assert not client.receive_buffer
    report.assert_not_called()


def test_diagnostics_hide_addresses_embedded_in_freeform_errors():
    from custom_components.fluvalble.diagnostics import REDACTED, _redact_diagnostics

    report = _redact_diagnostics(
        {
            "gatt": {"last_error": "Failed to connect to AA:BB:CC:DD:EE:FF"},
            "last_diagnostics": {"last_error": "Proxy AA:BB:CC:DD:EE:FF unavailable", "last_status": "connect_failed"},
        }
    )
    assert report["gatt"]["last_error"] == REDACTED
    assert report["last_diagnostics"] == {"last_error": REDACTED, "last_status": "connect_failed"}


@pytest.mark.parametrize(
    ("schedule", "left", "right"),
    [
        (
            "native_auto_schedule",
            {114: [360, 420], 115: [1020, 1080], 116: 65535},
            {117: bytes([20] * 4), 118: bytes(4)},
        ),
        ("native_pro_schedule", {120: 4, 121: [360, 720, 1080, 1200]}, {122: bytes([20] * 16)}),
    ],
)
@pytest.mark.parametrize("active", [False, True])
def test_facebd_schedule_read_combines_only_maps_from_same_request(schedule, left, right, active):
    async def run():
        device = make_device(532, "facebd")
        device.async_refresh_state = type(device).async_refresh_state.__get__(device)
        device._async_ensure_client = AsyncMock(return_value=True)
        client = _make_client()
        device.client = client
        client.raw_facebd = True
        client.update_callback = device.decode_update_packet
        client.notify_uuid = "notify"
        client.state_read_uuids = ["first", "second"]
        client.ensure_connected = AsyncMock(return_value=True)
        mode = 1 if schedule == "native_auto_schedule" else 2
        head = {103: mode, **left}
        responses = AsyncMock(side_effect=[protocol.cbor_map(fields) for fields in (head, {}, {}, right, head, right)])
        client._ensure_client = AsyncMock(return_value=SimpleNamespace(read_gatt_char=responses))
        with patch("custom_components.fluvalble.core.client.STATE_NOTIFY_TIMEOUT", 0.01):
            target = "active" if active else schedule
            assert not await device.async_refresh_state(schedule=target)
            assert not await device.async_refresh_state(schedule=target)
            assert device._schedule_revisions[schedule] == 0
            assert await device.async_refresh_state(schedule=target)
        assert device._schedule_revisions[schedule] == 1
        assert device.values[schedule]

    asyncio.run(run())


def test_facebd_split_notifications_wake_waiting_schedule_read():
    async def run():
        device = make_device(532, "facebd")
        device.async_refresh_state = type(device).async_refresh_state.__get__(device)
        device._async_ensure_client = AsyncMock(return_value=True)
        client = _make_client()
        device.client = client
        client.raw_facebd = True
        client.update_callback = device.decode_update_packet
        client.notify_uuid = "notify"
        client.ensure_connected = AsyncMock(return_value=True)
        # The GATT read itself contributes no decoded state.
        client._ensure_client = AsyncMock(return_value=SimpleNamespace(read_gatt_char=AsyncMock(return_value=b"\x00")))
        waiting = asyncio.Queue()

        def signal_wait(event):
            original_wait = event.wait

            async def wait():
                waiting.put_nowait(None)
                return await original_wait()

            event.wait = wait

        signal_wait(client._state_fragment_event)
        signal_wait(client._state_update_event)
        with patch("custom_components.fluvalble.core.client.STATE_NOTIFY_TIMEOUT", 1):
            read = asyncio.create_task(device.async_refresh_state(schedule="native_auto_schedule"))
            try:
                await asyncio.wait_for(waiting.get(), 1)
                assert client._dispatch_update(
                    protocol.cbor_map({103: 1, 114: [360, 420], 115: [1020, 1080], 116: 65535})
                )
                await asyncio.wait_for(waiting.get(), 1)
                assert not read.done()
                assert device._schedule_revisions["native_auto_schedule"] == 0
                # This half is not a valid schedule on its own and only
                # signals the fragment event, not the accepted-state event.
                assert not client._dispatch_update(protocol.cbor_map({117: bytes([20] * 4), 118: bytes(4)}))
                assert await read, "The final notification must wake the waiting schedule read"
                assert device.values["native_auto_schedule"]["day_levels"] == [20] * 4
                assert device._schedule_revisions["native_auto_schedule"] == 1
            finally:
                if not read.done():
                    read.cancel()
                    await asyncio.gather(read, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", ROUTES)
def test_startup_accepts_reply_after_normal_verification_deadline(transport, product):
    async def run():
        d = make_device(product, transport)
        c = _make_client()
        c.raw_facebd = transport != "classic"
        c.spp_transport = transport == "spp"
        c.init_write_uuid = "init" if transport == "classic" else None
        c.wake_read_uuid = None
        c.notify_uuid = "notify"
        c.state_read_uuids = ["state"]
        c.client = SimpleNamespace(is_connected=True)
        c._ensure_client = AsyncMock(return_value=c.client)
        c._wait_for_command_gap = AsyncMock()
        c.update_callback = d.decode_update_packet
        c.state_validator = d._initial_state_complete
        c.state_ready_callback = AsyncMock()
        tasks = []

        async def later():
            await asyncio.sleep(0.8)
            if transport == "classic":
                payload = _old_manual_status([10] * 4)
            else:
                keys = protocol.SPP_CHANNEL_KEYS if transport == "spp" else protocol.WIFI_CHANNEL_KEYS
                payload = protocol.cbor_map(
                    {
                        1 if transport == "spp" else 103: 0,
                        2 if transport == "spp" else 104: True,
                        **dict(zip(keys, [10] * len(d.numbers()))),
                    }
                )
            if transport == "spp":
                payload = bytes([protocol.SPP_STATUS_HEADER]) + payload
            c._dispatch_update(payload)

        async def trigger(*args):
            tasks.append(asyncio.create_task(later()))
            return b"\x00"

        c._write_packet = AsyncMock(side_effect=trigger)
        c.client.read_gatt_char = AsyncMock(side_effect=trigger)
        assert await c._initialize_session(c.client)
        await asyncio.gather(*tasks)
        assert c._session_initialized
        c.state_ready_callback.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("first", [False, "exception"])
def test_startup_retries_one_failed_read_with_its_own_budget(first):
    from bleak import BleakError

    async def run():
        c = _make_client()
        c.client = SimpleNamespace(is_connected=True)
        c.wake_read_uuid = None
        c.ready_callback = AsyncMock()
        c.state_ready_callback = AsyncMock()
        c.request_state = AsyncMock(side_effect=[BleakError("busy") if first == "exception" else False, True])
        assert await c._initialize_session(c.client)
        assert c.request_state.await_count == 2
        assert all(call.kwargs["timeout"] == 5.0 for call in c.request_state.await_args_list)
        c.ready_callback.assert_awaited_once()
        c.state_ready_callback.assert_awaited_once()

    asyncio.run(run())


def test_failed_initialization_stops_after_two_reads_and_discards_session():
    async def run():
        c = _make_client()
        c.client = SimpleNamespace(is_connected=True)
        c.wake_read_uuid = None
        c._ensure_client = AsyncMock(return_value=c.client)
        c.request_state = AsyncMock(return_value=False)
        c._safe_disconnect = AsyncMock()
        assert not await c.ensure_connected()
        assert c.request_state.await_count == 2
        c._safe_disconnect.assert_awaited_once()
        assert not c._session_initialized

    asyncio.run(run())


@pytest.mark.parametrize("order", ["channels_first", "mode_first"])
def test_unknown_facebd_four_channels_arrive_separately_from_mode_and_power(order):
    d = make_device(None, "facebd")
    c = _make_client()
    c.raw_facebd = True
    c.update_callback = d.decode_update_packet
    channels = dict(zip(protocol.WIFI_CHANNEL_KEYS, [10, 20, 30, 40]))
    pieces = [channels, {103: 0}, {104: True}]
    if order == "mode_first":
        pieces = [{103: 0}, {104: True}, channels]
    for index, fields in enumerate(pieces):
        c._dispatch_update(protocol.cbor_map(fields))
        assert d._initial_state_complete(c.observed_state) is (index == 2)
    assert len(d.numbers()) == 4
    # A later fifth emitter upgrades the provisional layout; a partial four
    # emitter report must never shrink an established five-channel fixture.
    d._decode_wifi_update({protocol.WIFI_CHANNEL_KEYS[4]: 50})
    d._decode_wifi_update(channels)
    assert len(d.numbers()) == 5


@pytest.mark.parametrize("channels_first", [False, True])
def test_facebd_initialization_collects_split_state_characteristics(channels_first):
    """Exercise the complete client gate, not only its completion predicate."""

    async def run():
        d = make_device(None, "facebd")
        c = _make_client()
        c.raw_facebd = True
        c.spp_transport = False
        c.wake_read_uuid = None
        c.notify_uuid = "notify"
        mode_uuid, channels_uuid = "mode-state", "channel-state"
        c.state_read_uuids = [channels_uuid, mode_uuid] if channels_first else [mode_uuid, channels_uuid]
        mode = protocol.cbor_map({protocol.WIFI_MODE_KEY: 0, protocol.WIFI_SWITCH_KEY: True})
        channels = protocol.cbor_map(dict(zip(protocol.WIFI_CHANNEL_KEYS, [10, 20, 30, 40])))
        payloads = {mode_uuid: mode, channels_uuid: channels}

        async def read(uuid):
            # Yield as a GATT read does; initialization cannot finish after
            # receiving just the first half of the required settings.
            await asyncio.sleep(0)
            assert not c._session_initialized
            c.state_ready_callback.assert_not_awaited()
            return payloads[uuid]

        c.client = SimpleNamespace(is_connected=True, read_gatt_char=AsyncMock(side_effect=read))
        c._ensure_client = AsyncMock(return_value=c.client)
        c.update_callback = d.decode_update_packet
        c.state_validator = d._initial_state_complete
        c.state_ready_callback = AsyncMock()
        c.request_state = AsyncMock(wraps=c.request_state)
        assert await c._initialize_session(c.client)
        assert c._session_initialized
        assert len(d.numbers()) == 4
        assert [d.values[key] for key in d.numbers()] == [10, 20, 30, 40]
        assert d.values["mode"] == "manual"
        assert d.values["led_on_off"] is True
        assert [call.args[0] for call in c.client.read_gatt_char.await_args_list] == c.state_read_uuids
        c.request_state.assert_awaited_once()
        c.state_ready_callback.assert_awaited_once_with(
            {
                protocol.WIFI_MODE_KEY: 0,
                protocol.WIFI_SWITCH_KEY: True,
                **dict(zip(protocol.WIFI_CHANNEL_KEYS, [10, 20, 30, 40])),
            }
        )

    asyncio.run(run())


def test_provisional_channel_hint_preserves_existing_registry_rows_and_entities():
    from custom_components.fluvalble.number import setup_channel_entities

    async def run():
        d = make_device(None, "facebd")
        d._channel_count_hint = 5
        runtime = FluvalRuntimeData(device=d)
        registry = SimpleNamespace(
            async_get_entity_id=MagicMock(return_value="number.custom_fifth"), async_remove=MagicMock()
        )
        added = []
        with (
            patch("custom_components.fluvalble.number.require_entry_runtime_data", return_value=runtime),
            patch.dict(
                sys.modules, {"homeassistant.helpers.entity_registry": SimpleNamespace(async_get=lambda _: registry)}
            ),
        ):
            setup_channel_entities(
                SimpleNamespace(async_create_task=asyncio.create_task),
                SimpleNamespace(async_on_unload=MagicMock()),
                d,
                added.extend,
            )
            assert len(added) == 5
            d._channel_count_hint = 4
            for handler in list(d.updates_component):
                handler()
            assert not runtime.background_tasks
            added[-1].internal_update()
            assert added[-1]._attr_available is False
            registry.async_remove.assert_not_called()
            d._channel_count_hint = 5
            for handler in list(d.updates_component):
                handler()
            assert len(added) == 5

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", ROUTES)
def test_failed_partial_write_preserves_post_mode_manual_readback(transport, product):
    async def run():
        d = make_device(product, transport)
        d.values.update(mode="automatic", channel_1=100, channel_2=10)
        levels = [10, 100] + [0] * (len(d.numbers()) - 2)

        async def read(**kwargs):
            report(d, transport, levels)
            return True

        d.async_refresh_state = AsyncMock(side_effect=read)

        async def send(packet):
            return packet == mode_packet(transport)

        d._async_send_packet = AsyncMock(side_effect=send)
        assert not await d.async_set_channels({"channel_1": 40})
        assert [d.values[key] for key in d.numbers()] == levels

    asyncio.run(run())


def mode_packet(transport):
    return {"classic": protocol.old_mode_packet, "facebd": protocol.wifi_mode_packet, "spp": protocol.spp_mode_packet}[
        transport
    ](0)


def bank_packet(transport, levels):
    return {
        "classic": protocol.old_all_zone_packet,
        "facebd": protocol.wifi_all_zone_packet,
        "spp": protocol.spp_all_zone_packet,
    }[transport](levels)


@pytest.mark.parametrize("transport,product", ROUTES)
def test_effect_confirmation_uses_each_commands_own_revision(transport, product):
    async def run():
        d = make_device(product, transport)
        d.values.update(mode="automatic", led_on_off=False)
        if transport == "classic":
            d.conn_info["service_uuids"] = ["00001000-0000-1000-8000-00805f9b34fb"]

        async def send(packet):
            if packet == mode_packet(transport):
                if transport == "classic":
                    d.decode_update_packet(_old_manual_status([0] * 4, flags=0))
                elif transport == "facebd":
                    d._decode_wifi_update({103: 0, 104: False})
                else:
                    d._decode_spp_update({1: 0, 2: False})
            return True

        d._async_send_packet = AsyncMock(side_effect=send)
        assert await d.async_set_effect("Lightning")
        assert d._async_send_packet.await_count == 3
        assert d.values["led_on_off"] is True
        assert d.values["effect"] == "Lightning"

    asyncio.run(run())


def test_four_channel_width_resolves_during_manual_mode_and_is_saved():
    async def run():
        d = make_device(None, "facebd")
        persist = AsyncMock()
        d.configure_manual_settings(None, persist)

        async def send(packet):
            report(d, "facebd", [0] * 4 if packet == mode_packet("facebd") else [50, 20, 0, 0])
            return True

        d._async_send_packet = AsyncMock(side_effect=send)
        assert await d.async_set_channels({"channel_1": 50, "channel_2": 20})
        persist.assert_awaited_once_with(dict(zip(d.numbers(), [50, 20, 0, 0])))
        assert d.has_last_manual_settings()

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", ROUTES)
@pytest.mark.parametrize("mode_response_has_bank", [False, True])
def test_brightness_uses_manual_bank_after_switching_modes(transport, product, mode_response_has_bank):
    async def run():
        d = make_device(product, transport)
        d.values.update(mode="automatic", channel_1=100, channel_2=10)
        levels = [10, 100] + [0] * (len(d.numbers()) - 2)

        async def read(**kwargs):
            report(d, transport, levels)
            return True

        d.async_refresh_state = AsyncMock(side_effect=read)

        async def send(packet):
            if packet == mode_packet(transport):
                if mode_response_has_bank:
                    report(d, transport, levels)
                elif transport == "classic":
                    pass
                elif transport == "facebd":
                    d._decode_wifi_update({103: 0})
                else:
                    d._decode_spp_update({1: 0})
            return True

        d._async_send_packet = AsyncMock(side_effect=send)
        assert await d.async_set_master_brightness(50)
        assert d._async_send_packet.await_args.args[0] == bank_packet(transport, [5, 50] + [0] * (len(d.numbers()) - 2))
        assert d.async_refresh_state.await_count == (0 if mode_response_has_bank else 1)

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", ROUTES)
def test_missing_manual_bank_blocks_relative_brightness_write(transport, product):
    async def run():
        d = make_device(product, transport)
        d._async_send_packet = AsyncMock(return_value=True)
        assert not await d.async_set_master_brightness(50)
        d._async_send_packet.assert_awaited_once_with(mode_packet(transport))
        assert d.diagnostics["status"] == "manual_channels_unavailable"

    asyncio.run(run())


@pytest.mark.parametrize("product", sorted(PRODUCTS))
@pytest.mark.parametrize("transition", [0, 10])
def test_invalid_channels_never_change_a_fixture(product, transition):
    async def run():
        transport = "facebd" if PRODUCTS[product].channel_count == 4 else "spp"
        d = make_device(product, transport)
        before = dict(d.values)
        d._async_send_packet = AsyncMock()
        invalid = f"channel_{len(d.numbers()) + 1}"
        for values in ({invalid: 50}, {"channel_1": 50, invalid: 50}, {}):
            assert not await d.async_set_channels(values, transition=transition)
        assert d.values == before
        d._async_send_packet.assert_not_awaited()
        d._async_prepare_command.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("transport,product", ROUTES)
def test_final_rounded_fade_plateau_is_confirmed_and_saved(transport, product):
    async def run():
        d = make_device(product, transport)
        d.values.update(mode="manual", led_on_off=False)
        persist = AsyncMock()
        d.configure_manual_settings(None, persist)

        async def send(packet):
            if transport == "classic":
                if packet[1] == 4:
                    report(d, transport, [1] + [0] * 3)
            else:
                fields = protocol.decode_cbor_update(packet)
                if (110 if transport == "facebd" else 3) in fields:
                    report(d, transport, [1] + [0] * (len(d.numbers()) - 1))
            return True

        d._async_send_packet = AsyncMock(side_effect=send)
        with patch("custom_components.fluvalble.core.device.asyncio.sleep", new=AsyncMock()):
            assert await d.async_set_channels({"channel_1": 1}, transition=10, step_seconds=2)
        persist.assert_awaited_once_with(dict(zip(d.numbers(), [1] + [0] * (len(d.numbers()) - 1))))

    asyncio.run(run())


async def setup_editor_for_test(runtime, run):
    from custom_components.fluvalble.schedule_editor import async_setup_editor

    entry = SimpleNamespace(domain="fluvalble")
    hass = SimpleNamespace(
        data={"fluvalble": {}},
        http=SimpleNamespace(register_static_path=MagicMock()),
        config_entries=SimpleNamespace(async_get_entry=lambda _: entry),
    )
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True), send_result=MagicMock(), send_error=MagicMock())
    with (
        patch.dict(sys.modules, {"homeassistant.components.frontend": SimpleNamespace(add_extra_js_url=MagicMock())}),
        patch("custom_components.fluvalble.schedule_editor.vol.Any", lambda *args: object, create=True),
        patch("custom_components.fluvalble.schedule_editor.websocket_api.async_register_command") as register,
        patch("custom_components.fluvalble.entry_runtime_data", side_effect=lambda *args: runtime[0]),
    ):
        await async_setup_editor(hass)
        await run(register.call_args_list[1].args[1], hass, connection)
    return connection


@pytest.mark.parametrize("missing", ["target", "levels", "both"])
def test_incomplete_schedule_edit_is_rejected_before_any_device_read(missing):
    async def run():
        d = make_device()
        message = {
            "id": 1,
            "entry_id": "fixture",
            "schedule": "auto",
            "baseline": {},
            "target": "day",
            "levels": [50] * 5,
        }
        for field in ["target", "levels"] if missing == "both" else [missing]:
            del message[field]

        async def call(save, hass, connection):
            await save(hass, connection, message)

        connection = await setup_editor_for_test([FluvalRuntimeData(device=d)], call)
        connection.send_error.assert_called_once_with(
            1, "invalid_format", "Provide a schedule target and channel levels"
        )
        d.async_refresh_state.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("state", ["absent", "unloading", "replaced_while_waiting"])
def test_schedule_save_handles_unloaded_or_replaced_runtime(state):
    async def run():
        d = make_device()
        runtime = [None if state == "absent" else FluvalRuntimeData(device=d)]
        if state == "unloading":
            runtime[0].unloading = True

        @asynccontextmanager
        async def transaction():
            runtime[0] = FluvalRuntimeData(device=d)
            yield

        if state == "replaced_while_waiting":
            d.command_transaction = transaction
        d._async_send_packet = AsyncMock()

        async def call(save, hass, connection):
            await save(
                hass,
                connection,
                {
                    "id": 1,
                    "entry_id": "fixture",
                    "schedule": "auto",
                    "target": "day",
                    "levels": [50] * 5,
                    "baseline": {},
                },
            )

        connection = await setup_editor_for_test(runtime, call)
        connection.send_error.assert_called_once()
        d._async_send_packet.assert_not_awaited()

    asyncio.run(run())


def pro_points(count=5):
    return [{"minute": minute, **{f"channel_{i}": 50 for i in range(1, count + 1)}} for minute in (60, 480, 900, 1200)]


@pytest.mark.parametrize(
    "transport,count", [("classic", 4), ("classic", 5), ("facebd", 4), ("facebd", 5), ("spp", 4), ("spp", 5)]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_professional_timing_batch_is_one_verified_native_write(transport, count, reverse):
    async def run():
        d = make_device(532 if count == 4 else 545, transport)
        d.values["mode"] = "professional"
        original = pro_points(count)
        changes = [
            {"target": 1, "levels": [60] * count, "times": 1150},
            {"target": 2, "levels": [70] * count, "times": 1100},
        ]
        if reverse:
            changes.reverse()
        expected = replace_professional_batch(original, channel_count=count, changes=changes)
        wire = professional_batch_packet(original, transport=transport, channel_count=count, changes=changes)
        d.values["native_pro_schedule"] = deepcopy(original)

        async def read(**kwargs):
            if d._async_send_packet.await_count:
                if transport == "classic":
                    raw = protocol.old_packet(bytes([0x68, 5, 2]) + wire[2:-1])
                else:
                    fields = protocol.decode_cbor_update(wire)
                    fields[103 if transport == "facebd" else 1] = 2
                    raw = (b"" if transport == "facebd" else b"\xd2") + protocol.cbor_map(fields)
                assert d.decode_update_packet(raw)
            return True

        d.async_refresh_state = AsyncMock(side_effect=read)
        d._async_send_packet = AsyncMock(return_value=True)

        async def call(save, hass, connection):
            await save(
                hass,
                connection,
                {"id": 1, "entry_id": "fixture", "schedule": "professional", "baseline": original, "changes": changes},
            )

        with patch("custom_components.fluvalble.schedule_editor.asyncio.sleep", new=AsyncMock()):
            connection = await setup_editor_for_test([FluvalRuntimeData(device=d)], call)
        connection.send_result.assert_called_once_with(1, {"schedule": expected})
        d._async_send_packet.assert_awaited_once_with(wire)
        assert [point["minute"] for point in expected] == [60, 1100, 1150, 1200]
        assert [point["channel_1"] for point in expected] == [50, 70, 60, 50]
        assert [point["minute"] for point in original] == [60, 480, 900, 1200]

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        [],
        [{"target": 1, "levels": [50] * 5, "times": 60}],
        [{"target": 1, "levels": [50] * 5}, {"target": 1, "levels": [50] * 5}],
        [{"target": True, "levels": [50] * 5}],
        [{"target": 9, "levels": [50] * 5}],
        [{"target": 1, "levels": [True] * 5}],
        [{"target": 1, "levels": [50] * 4}],
        [{"target": 1, "levels": [50] * 5, "times": 1440}],
        [{"target": 1, "levels": [50] * 5, "extra": 1}],
    ],
)
def test_invalid_professional_batches_do_not_mutate_original(changes):
    original = pro_points()
    before = deepcopy(original)
    with pytest.raises(ValueError):
        replace_professional_batch(original, channel_count=5, changes=changes)
    assert original == before


def test_dst_switch_appears_once_after_late_transport_resolution_and_unsubscribes():
    from custom_components.fluvalble.switch import setup_switch_entities

    d = make_device(532, "classic")
    d._uses_wifi_protocol = type(d)._uses_wifi_protocol.__get__(d)
    runtime = FluvalRuntimeData(device=d)
    entry = SimpleNamespace(async_on_unload=MagicMock())
    added = []
    with patch("custom_components.fluvalble.switch.require_entry_runtime_data", return_value=runtime):
        setup_switch_entities(None, entry, d, added.extend)
        assert not added
        d.client = SimpleNamespace(
            command_write_uuid="facebd01-7261-6262-6974-696f74626c65", wifi_facebd=True, spp_transport=False
        )
        for _ in range(2):
            d._decode_wifi_update({99: True, 103: 0, 104: True, 110: 0, 111: 0, 112: 0, 113: 0})
        assert len(added) == 1
        assert added[0]._attr_is_on is True
        assert added[0]._attr_available
        runtime.unload_callbacks[0]()
        assert not d.updates_component


def test_product_281_uses_active_apk_reef_labels_and_spectrum():
    d = make_device(281, "classic")
    assert [d.entity_name(c) for c in d.numbers()] == ["Pink", "Cyan", "Blue", "Purple", "Cold White"]
    assert d.spectrum_profile() == "reef_current"
