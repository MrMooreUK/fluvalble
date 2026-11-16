"""Confirmed Manual memory is independent of live readback and explicit to restore."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.device import Device
from custom_components.fluvalble.core.products import PRODUCTS
from custom_components.fluvalble import manual_settings
from custom_components.fluvalble.button import FluvalRestoreManualButton


@pytest.fixture(autouse=True)
def _fresh_manual_stores():
    manual_settings._STORES.clear()
    yield
    manual_settings._STORES.clear()


def saved(device, levels):
    return {
        "mac": device.mac,
        "product_id": device.product_id,
        "spectrum_profile": device.spectrum_profile(),
        "levels": list(levels),
    }


def report(device, transport, levels, mode=0):
    if transport == "classic":
        body = (
            bytes([mode, 1, 0])
            + b"".join((value * 10).to_bytes(2, "little") for value in levels)
            + bytes(len(levels) * 4)
        )
        packet = protocol.old_packet(bytes([0x68, 5]) + body)
    else:
        keys = protocol.SPP_CHANNEL_KEYS if transport == "spp" else protocol.WIFI_CHANNEL_KEYS
        fields = {
            1 if transport == "spp" else 103: mode,
            2 if transport == "spp" else 104: True,
            **dict(zip(keys, levels)),
        }
        packet = protocol.cbor_map(fields)
        if transport == "spp":
            packet = bytes([protocol.SPP_STATUS_HEADER]) + packet
    assert device.decode_update_packet(packet)


def make_device(product=545, transport="spp"):
    device = Device("Offline test", config_data={"mac": "AA:BB:CC:DD:EE:FF", "product_id": product})
    device._uses_wifi_protocol = lambda: transport == "facebd"
    device._uses_spp_protocol = lambda: transport == "spp"
    device._async_prepare_command = AsyncMock(return_value=True)
    device.async_refresh_state = AsyncMock(return_value=False)
    device.values.update(mode="automatic", led_on_off=True)
    return device


@pytest.mark.parametrize("product", sorted(PRODUCTS))
@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
def test_confirmed_bank_survives_unsolicited_reports_and_explicitly_restores(product, transport):
    async def run():
        device = make_device(product, transport)
        count = len(device.numbers())
        levels = [20 + i * 10 for i in range(count)]
        targets = dict(zip(device.numbers(), levels))
        persist = AsyncMock()
        device.configure_manual_settings(None, persist)
        builder = {
            "classic": protocol.old_all_zone_packet,
            "facebd": protocol.wifi_all_zone_packet,
            "spp": protocol.spp_all_zone_packet,
        }[transport]
        packet = builder(levels)

        async def send(value):
            if value == packet:
                report(device, transport, levels)
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        assert await device.async_set_channels(targets, force=True)
        persist.assert_awaited_once_with(targets)
        assert device.has_last_manual_settings()
        report(device, transport, [0, 100] + [0] * (count - 2))
        assert [device.values[c] for c in device.numbers()] == [0, 100] + [0] * (count - 2)
        assert device._last_manual_settings == targets
        calls = device._async_send_packet.await_count
        assert await device.async_restore_last_manual_settings()
        assert device._async_send_packet.await_count > calls
        assert [device.values[c] for c in device.numbers()] == levels
        persist.assert_awaited_once()
        device.async_refresh_state.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["write_failed", "no_readback", "mismatched", "partial"])
def test_bad_confirmation_or_storage_never_overwrites_saved_bank(kind):
    async def run():
        device = make_device()
        old = [10] * 5
        persist = AsyncMock()
        device.configure_manual_settings(saved(device, old), persist)
        targets = dict(zip(device.numbers(), [60] * 5))

        async def send(packet):
            if packet == protocol.spp_all_zone_packet([60] * 5):
                if kind == "mismatched":
                    report(device, "spp", [70] * 5)
                if kind == "partial":
                    device.decode_update_packet(bytes([protocol.SPP_STATUS_HEADER]) + protocol.cbor_map({1: 0, 3: 60}))
                if kind == "write_failed":
                    return False
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        assert await device.async_set_channels(targets, force=True) is (kind != "write_failed")
        assert device._last_manual_settings == dict(zip(device.numbers(), old))
        persist.assert_not_awaited()

    asyncio.run(run())


def test_unverified_write_requires_fresh_complete_report_before_saving():
    async def run():
        device = make_device()
        persist = AsyncMock()
        device.configure_manual_settings(None, persist)
        device._async_send_packet = AsyncMock(return_value=True)

        async def refresh():
            report(device, "spp", [45] * 5)
            return True

        device.async_refresh_state = AsyncMock(side_effect=refresh)
        assert await device.async_set_channels(dict(zip(device.numbers(), [45] * 5)), force=True)
        persist.assert_awaited_once()
        device.async_refresh_state.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("bad", ["mac", "product", "profile", "width", "bool", "range"])
def test_invalid_or_foreign_saved_bank_is_rejected_without_writes(bad):
    device = make_device()
    payload = saved(device, [40] * 5)
    if bad == "mac":
        payload["mac"] = "11:22:33:44:55:66"
    if bad == "product":
        payload["product_id"] = 532
    if bad == "profile":
        payload["spectrum_profile"] = "wrong"
    if bad == "width":
        payload["levels"] = [40] * 4
    if bad == "bool":
        payload["levels"][0] = True
    if bad == "range":
        payload["levels"][0] = 101
    device.configure_manual_settings(payload, AsyncMock())
    device._async_send_packet = AsyncMock()
    assert not asyncio.run(device.async_restore_last_manual_settings())
    device._async_send_packet.assert_not_awaited()


def test_restore_rechecks_identity_after_reconnecting_before_any_write():
    async def run():
        device = make_device()
        device.values["mode"] = "manual"
        device.configure_manual_settings(saved(device, [40] * 5), AsyncMock())

        async def reconnect():
            device.product_id = 532
            return True

        device._async_prepare_command = AsyncMock(side_effect=reconnect)
        device._async_send_packet = AsyncMock()
        assert not await device.async_restore_last_manual_settings()
        device._async_send_packet.assert_not_awaited()

    asyncio.run(run())


def test_restore_does_not_report_success_without_confirming_readback():
    device = make_device()
    device.values["mode"] = "manual"
    device.configure_manual_settings(saved(device, [40] * 5), AsyncMock())
    device._async_send_packet = AsyncMock(return_value=True)
    assert not asyncio.run(device.async_restore_last_manual_settings())
    assert device.diagnostics["status"] == "manual_restore_unconfirmed"


def test_storage_survives_new_device_and_is_removed_only_on_entry_deletion():
    from custom_components.fluvalble.manual_settings import async_manual_settings_storage, async_remove_manual_settings

    async def run():
        disk = {}

        class Store:
            def __init__(self, hass, version, key):
                self.key = key

            async def async_load(self):
                return deepcopy(disk.get(self.key))

            async def async_save(self, data):
                disk[self.key] = deepcopy(data)

            def async_delay_save(self, data_func, delay):
                disk[self.key] = deepcopy(data_func())

            async def async_remove(self):
                disk.pop(self.key, None)

        entry = SimpleNamespace(entry_id="one")
        with patch("custom_components.fluvalble.manual_settings.Store", Store):
            attach = await async_manual_settings_storage(None, entry)
            device = make_device()
            attach(device)
            before = dict(device.values)
            await device._manual_settings_save(dict(zip(device.numbers(), [35] * 5)))
            attach = await async_manual_settings_storage(None, entry)
            reloaded = make_device()
            attach(reloaded)
            assert reloaded.has_last_manual_settings()
            assert reloaded.values == before
            other = make_device()
            (await async_manual_settings_storage(None, SimpleNamespace(entry_id="two")))(other)
            assert not other.has_last_manual_settings()
            await async_remove_manual_settings(None, entry)
            assert disk == {}

    asyncio.run(run())


def test_restore_button_is_unavailable_until_saved_and_propagates_failures():
    device = make_device()
    device.client = SimpleNamespace()
    button = FluvalRestoreManualButton(device, "restore_last_manual")
    assert not button._attr_available
    device.configure_manual_settings(saved(device, [40] * 5), AsyncMock())
    button.internal_update()
    assert button._attr_available
    device.async_restore_last_manual_settings = AsyncMock(return_value=True)
    asyncio.run(button.async_press())
    device.async_restore_last_manual_settings.assert_awaited_once()


@pytest.mark.parametrize("fail_final", [False, True])
def test_transition_remembers_only_confirmed_final_bank(fail_final):
    async def run():
        device = make_device()
        persist = AsyncMock()
        device.configure_manual_settings(saved(device, [10] * 5), persist)
        targets = dict(zip(device.numbers(), [60] * 5))

        async def send(packet):
            fields = protocol.decode_cbor_update(packet)
            if all(key in fields for key in range(3, 8)):
                levels = [fields[key] for key in range(3, 8)]
                if fail_final and levels == [60] * 5:
                    return False
                report(device, "spp", levels)
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        with patch("custom_components.fluvalble.core.device.asyncio.sleep", new=AsyncMock()):
            assert await device.async_set_channels(targets, transition=3, step_seconds=1) is not fail_final
        if fail_final:
            persist.assert_not_awaited()
            assert device._last_manual_settings == dict(zip(device.numbers(), [10] * 5))
        else:
            persist.assert_awaited_once_with(targets)

    asyncio.run(run())


def test_storage_load_failure_does_not_prevent_integration_setup():
    from custom_components.fluvalble.manual_settings import async_manual_settings_storage

    async def run():
        store = SimpleNamespace(async_load=AsyncMock(side_effect=OSError("unreadable")), async_save=AsyncMock())
        with patch("custom_components.fluvalble.manual_settings.Store", return_value=store):
            attach = await async_manual_settings_storage(None, SimpleNamespace(entry_id="one"))
        device = make_device()
        attach(device)
        assert not device.has_last_manual_settings()
        device._async_prepare_command.assert_not_awaited()

    asyncio.run(run())


def make_unidentified_facebd_device():
    device = make_device(product=None, transport="facebd")
    assert device.lamp_profile == "auto"
    assert len(device.numbers()) == 5
    return device


def test_stored_four_channel_bank_becomes_restorable_after_facebd_readback():
    async def run():
        device = make_unidentified_facebd_device()
        levels = [30, 40, 50, 60]
        payload = saved(device, levels)
        device.configure_manual_settings(payload, AsyncMock())
        device.client = SimpleNamespace()
        button = FluvalRestoreManualButton(device, "restore_last_manual")
        device._async_send_packet = AsyncMock(return_value=True)
        assert not device.has_last_manual_settings()
        assert not button._attr_available
        assert not await device.async_restore_last_manual_settings()
        device._async_send_packet.assert_not_awaited()

        report(device, "facebd", [0, 0, 0, 0])
        assert len(device.numbers()) == 4
        assert device.has_last_manual_settings()
        button.internal_update()
        assert button._attr_available

        packet = protocol.wifi_all_zone_packet(levels)

        async def send(value):
            if value == packet:
                report(device, "facebd", levels)
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        assert await device.async_restore_last_manual_settings()
        assert packet in [call.args[0] for call in device._async_send_packet.await_args_list]
        assert [device.values[c] for c in device.numbers()] == levels

    asyncio.run(run())


def test_stored_five_channel_bank_is_dropped_when_readback_resolves_four_channels():
    async def run():
        device = make_unidentified_facebd_device()
        device.configure_manual_settings(saved(device, [40] * 5), AsyncMock())
        assert device.has_last_manual_settings()
        report(device, "facebd", [0, 0, 0, 0])
        assert len(device.numbers()) == 4
        assert not device.has_last_manual_settings()
        device._async_send_packet = AsyncMock(return_value=True)
        assert not await device.async_restore_last_manual_settings()
        device._async_send_packet.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("path", ["channels", "slider"])
def test_all_off_write_keeps_previous_bank_and_skips_persist(path):
    async def run():
        device = make_device()
        old = [10] * 5
        persist = AsyncMock()
        device.configure_manual_settings(saved(device, old), persist)

        async def send(packet):
            report(device, "spp", [0] * 5)
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        if path == "channels":
            assert await device.async_set_channels(dict(zip(device.numbers(), [0] * 5)), force=True)
        else:
            device.values.update({channel: 0 for channel in device.numbers()}, channel_1=50, mode="manual")
            assert await device.async_set_value("channel_1", 0)
            device.cancel_channel_mode_restore()
        device._async_send_packet.assert_awaited()
        persist.assert_not_awaited()
        assert device._last_manual_settings == dict(zip(device.numbers(), old))
        assert device.diagnostics["last_manual_settings_status"] == "skipped_all_off"

    asyncio.run(run())


def test_stored_four_channel_bank_restores_after_spp_readback_without_product_id():
    transport = "spp"

    async def run():
        device = make_device(product=None, transport=transport)
        assert len(device.numbers()) == 5
        levels = [25, 35, 45, 55]
        device.configure_manual_settings(saved(device, levels), AsyncMock())
        assert not device.has_last_manual_settings()
        report(device, transport, [0, 0, 0, 0])
        assert len(device.numbers()) == 4
        assert device.has_last_manual_settings()
        packet = protocol.spp_all_zone_packet(levels)

        async def send(value):
            if value == packet:
                report(device, transport, levels)
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        assert await device.async_restore_last_manual_settings()
        assert packet in [call.args[0] for call in device._async_send_packet.await_args_list]

    asyncio.run(run())


RESTORE_MODE_ERROR = "Switch the fixture to Manual mode before restoring saved Manual settings"


@pytest.mark.parametrize("mode", ["automatic", "professional"])
def test_restore_refuses_outside_manual_mode_without_sending(mode):
    from homeassistant.exceptions import HomeAssistantError

    async def run():
        device = make_device()
        device.client = SimpleNamespace(last_error=None)
        device.values["mode"] = mode
        device.configure_manual_settings(saved(device, [40] * 5), AsyncMock())
        device._async_send_packet = AsyncMock(return_value=True)
        assert not await device.async_restore_last_manual_settings()
        device._async_send_packet.assert_not_awaited()
        device._async_prepare_command.assert_not_awaited()
        assert device.values["mode"] == mode
        assert device.diagnostics["status"] == "manual_restore_requires_manual_mode"
        assert device.command_error_message() == RESTORE_MODE_ERROR
        button = FluvalRestoreManualButton(device, "restore_last_manual")
        with pytest.raises(HomeAssistantError, match="Switch the fixture to Manual mode"):
            await button.async_press()
        device._async_send_packet.assert_not_awaited()

    asyncio.run(run())


def test_restore_rechecks_mode_after_reconnecting():
    async def run():
        device = make_device()
        device.values["mode"] = "manual"
        device.configure_manual_settings(saved(device, [40] * 5), AsyncMock())

        async def reconnect():
            device.values["mode"] = "automatic"
            return True

        device._async_prepare_command = AsyncMock(side_effect=reconnect)
        device._async_send_packet = AsyncMock(return_value=True)
        assert not await device.async_restore_last_manual_settings()
        device._async_send_packet.assert_not_awaited()
        assert device.diagnostics["status"] == "manual_restore_requires_manual_mode"

    asyncio.run(run())


def test_restore_in_manual_mode_sends_bank_and_no_mode_packet():
    async def run():
        device = make_device()
        device.values["mode"] = "manual"
        levels = [40, 50, 60, 70, 80]
        device.configure_manual_settings(saved(device, levels), AsyncMock())
        packet = protocol.spp_all_zone_packet(levels)

        async def send(value):
            if value == packet:
                report(device, "spp", levels)
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        assert await device.async_restore_last_manual_settings()
        sent = [call.args[0] for call in device._async_send_packet.await_args_list]
        assert packet in sent
        assert protocol.spp_mode_packet(0) not in sent
        assert all(1 not in protocol.decode_cbor_update(value) for value in sent)

    asyncio.run(run())


class DelayStore:
    """Mimic HA Store debouncing: the last data func wins and is written once on flush."""

    instances: list["DelayStore"] = []

    def __init__(self, hass, version, key):
        self.key = key
        self.disk = None
        self.pending = None
        self.delays = []
        self.writes = 0
        self.async_save = AsyncMock()
        DelayStore.instances.append(self)

    async def async_load(self):
        return deepcopy(self.disk)

    def async_delay_save(self, data_func, delay):
        self.pending = data_func
        self.delays.append(delay)

    def flush(self):
        if self.pending is not None:
            self.disk = deepcopy(self.pending())
            self.pending = None
            self.writes += 1

    async def async_remove(self):
        self.pending = None
        self.disk = None


def test_rapid_confirmed_writes_produce_one_debounced_save():
    from custom_components.fluvalble.manual_settings import async_manual_settings_storage

    async def run():
        DelayStore.instances.clear()
        with patch("custom_components.fluvalble.manual_settings.Store", DelayStore):
            attach = await async_manual_settings_storage(None, SimpleNamespace(entry_id="one"))
        (store,) = DelayStore.instances
        device = make_device()
        attach(device)

        async def send(packet):
            fields = protocol.decode_cbor_update(packet)
            if all(key in fields for key in range(3, 8)):
                report(device, "spp", [fields[key] for key in range(3, 8)])
            return True

        device._async_send_packet = AsyncMock(side_effect=send)
        for level in (20, 30, 40):
            targets = dict(zip(device.numbers(), [level] * 5))
            assert await device.async_set_channels(targets, force=True)
            assert device._last_manual_settings == targets
        store.async_save.assert_not_awaited()
        assert store.delays == [manual_settings.SAVE_DELAY] * 3
        store.flush()
        assert store.writes == 1
        assert store.disk["levels"] == [40] * 5

    asyncio.run(run())


def test_entry_removal_cancels_pending_delayed_save():
    from custom_components.fluvalble.manual_settings import async_manual_settings_storage, async_remove_manual_settings

    async def run():
        DelayStore.instances.clear()
        entry = SimpleNamespace(entry_id="one")
        with patch("custom_components.fluvalble.manual_settings.Store", DelayStore):
            attach = await async_manual_settings_storage(None, entry)
            device = make_device()
            attach(device)
            await device._manual_settings_save(dict(zip(device.numbers(), [35] * 5)))
            await async_remove_manual_settings(None, entry)
        (store,) = DelayStore.instances
        store.flush()
        assert store.writes == 0
        assert store.disk is None
        assert "one" not in manual_settings._STORES

    asyncio.run(run())
