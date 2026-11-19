"""Offline native MQTT fixture tests; no network, broker or BLE hardware."""

import asyncio
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fluvalble.config_flow import ConfigFlow, OptionsFlowHandler
from custom_components.fluvalble.core import protocol
from custom_components.fluvalble.core.entity import FluvalEntity
from custom_components.fluvalble.core.mqtt_client import MqttClient, decode_uplink, native_topic
from custom_components.fluvalble.core.mqtt_device import MqttDevice
from custom_components.fluvalble.core.mqtt_provisioning import broker_frame, provisioning_wifi_mac, wifi_frame

BLE_MAC = "AA:BB:CC:DD:EE:01"
WIFI_MAC = "AA:BB:CC:DD:EE:02"
STATE = {103: 0, 104: True, 110: 10, 111: 20, 112: 30, 113: 40}


def report(state):
    return "id:1;type:property_post;param:" + protocol.cbor_map(state).hex() + ";;"


@pytest.fixture
def broker(monkeypatch):
    """A bounded in-memory fixture, not a live MQTT connection."""
    import importlib

    mqtt = SimpleNamespace(
        is_connected=MagicMock(return_value=True),
        async_wait_for_mqtt_client=AsyncMock(return_value=True),
        async_subscribe=AsyncMock(),
        async_subscribe_connection_status=MagicMock(),
        async_publish=AsyncMock(),
    )
    mqtt.state = dict(STATE)
    mqtt.unsubscribe = MagicMock()
    mqtt.unsubscribe_status = MagicMock()
    mqtt.async_subscribe.return_value = mqtt.unsubscribe
    mqtt.async_subscribe_connection_status.return_value = mqtt.unsubscribe_status

    async def publish(hass, topic, payload, **kwargs):
        if "type:property_set" in payload:
            mqtt.state.update(protocol.decode_cbor_map(bytes.fromhex(payload.split("param:")[1][:-2])))
        elif "type:property_get" in payload:
            callback = mqtt.async_subscribe.call_args.args[2]
            callback(SimpleNamespace(payload=report(mqtt.state), retain=False))

    mqtt.async_publish.side_effect = publish
    monkeypatch.setattr(sys.modules["homeassistant.components"], "mqtt", mqtt, raising=False)
    monkeypatch.setitem(sys.modules, "homeassistant.components.mqtt", mqtt)
    exceptions = sys.modules["homeassistant.exceptions"]
    if not hasattr(exceptions, "ConfigEntryNotReady"):
        monkeypatch.setattr(
            exceptions, "ConfigEntryNotReady", type("ConfigEntryNotReady", (Exception,), {}), raising=False
        )
    monkeypatch.setattr(importlib.import_module("custom_components.fluvalble.core.mqtt_client"), "STATE_TIMEOUT", 0.03)
    return mqtt


def client():
    hass = SimpleNamespace(async_create_background_task=create_background_task)
    return MqttClient(hass, WIFI_MAC, MagicMock(), MagicMock(return_value=True), lambda state: 103 in state)


def test_mqtt_transport_does_not_inherit_ble_lifecycle():
    from custom_components.fluvalble.core.client import Client

    assert not issubclass(MqttClient, Client)


@pytest.mark.asyncio
async def test_mqtt_partial_subscription_failure_rolls_back_and_can_retry(broker):
    c = client()
    broker.async_subscribe_connection_status.side_effect = [KeyError("MQTT reloading"), broker.unsubscribe_status]
    try:
        assert not await c.ensure_connected()
        assert not c._unsubscribers and c._monitor is None
        broker.unsubscribe.assert_called_once()
        assert await c.ensure_connected()
    finally:
        await c.stop()
    assert broker.unsubscribe.call_count == 2


def create_background_task(coro, name):
    return asyncio.create_task(coro, name=name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        "success",
        "no_mqtt",
        "rejected",
        "timeout",
        "missing_characteristic",
        "restore_failed",
        "cancel_stop",
        "cancel_start",
    ],
)
async def test_ha_provisioning_uses_existing_gatt_and_requires_mqtt_response(broker, monkeypatch, outcome):
    from custom_components.fluvalble import wifi_setup

    hass = SimpleNamespace(async_create_background_task=create_background_task)
    device = MqttDevice("Tank", hass=hass, config_data={"mac": BLE_MAC, "wifi_mac": WIFI_MAC})
    characteristic = SimpleNamespace(properties=["write-without-response"])
    gatt = SimpleNamespace(
        services=SimpleNamespace(
            get_characteristic=lambda _: None if outcome == "missing_characteristic" else characteristic
        ),
        read_gatt_char=AsyncMock(return_value=f"brand:Fluval;mac:{WIFI_MAC};;".encode()),
        start_notify=AsyncMock(),
        stop_notify=AsyncMock(),
        is_connected=True,
    )
    written = bytearray()
    wifi = wifi_frame("Tank", "test-only", 0)
    settings = broker_frame("broker.lan", 1883, "tank", "lamp", "test-only")
    started = asyncio.Event()
    continue_write = asyncio.Event()

    async def write(_characteristic, chunk, *, response):
        assert not response and len(chunk) <= 20
        if not written and outcome == "success":
            started.set()
            await continue_write.wait()
        written.extend(chunk)
        receive = gatt.start_notify.call_args.args[1]
        if written == wifi:
            receive(None, b"ip:192.0.2.")
            receive(None, b"1;;")
        elif written == wifi + settings and outcome == "rejected":
            receive(None, b"err:broker;;")
        elif written == wifi + settings and outcome != "timeout":
            receive(None, b"mqtt:connected;;")

    gatt.write_gatt_char = AsyncMock(side_effect=write)
    from custom_components.fluvalble.wifi_setup import PROVISION_UUID

    device.client = SimpleNamespace(
        _ensure_client=AsyncMock(return_value=gatt),
        _command_lock=asyncio.Lock(),
        notify_uuids=[PROVISION_UUID],
        notify_callback=MagicMock(),
        _safe_disconnect=AsyncMock(),
    )
    device._async_prepare_command = AsyncMock(return_value=True)
    if outcome == "restore_failed":
        gatt.start_notify.side_effect = [None, RuntimeError("proxy lost the subscription")]
    if outcome in {"cancel_stop", "cancel_start"}:
        cleanup_started = asyncio.Event()
        active_callback = device.client.notify_callback

        async def start_notify(_, callback):
            nonlocal active_callback
            if callback is device.client.notify_callback and outcome == "cancel_start":
                cleanup_started.set()
                await asyncio.Future()
            active_callback = callback

        async def stop_notify(_):
            nonlocal active_callback
            if gatt.stop_notify.await_count == 2 and outcome == "cancel_stop":
                cleanup_started.set()
                await asyncio.Future()
            active_callback = None

        async def disconnect():
            nonlocal active_callback
            active_callback = None

        gatt.start_notify.side_effect = start_notify
        gatt.stop_notify.side_effect = stop_notify
        device.client._safe_disconnect.side_effect = disconnect
        setup = asyncio.create_task(wifi_setup.provision(hass, device, wifi, settings))
        await asyncio.wait_for(cleanup_started.wait(), 1)
        setup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await setup
        device.client._safe_disconnect.assert_awaited_once()
        assert active_callback is None
        assert not device.client._command_lock.locked()
        broker.async_subscribe.assert_not_awaited()
        return
    if outcome == "success":

        async def light_command():
            async with device.command_transaction():
                assert written == wifi + settings

        setup = asyncio.create_task(wifi_setup.provision(hass, device, wifi, settings))
        await asyncio.wait_for(started.wait(), 1)
        command = asyncio.create_task(light_command())
        await asyncio.sleep(0)
        assert not command.done()
        continue_write.set()
        assert await asyncio.wait_for(setup, 1) == WIFI_MAC
        await asyncio.wait_for(command, 1)
    elif outcome == "no_mqtt":
        broker.async_publish.side_effect = None
        with pytest.raises(ConnectionError, match="did not respond"):
            await wifi_setup.provision(hass, device, wifi, settings)
    elif outcome == "missing_characteristic":
        with pytest.raises(ConnectionError, match="does not expose"):
            await wifi_setup.provision(hass, device, wifi, settings)
        assert not written
        gatt.start_notify.assert_not_awaited()
        broker.async_subscribe.assert_not_awaited()
        return
    elif outcome == "timeout":
        monkeypatch.setattr(wifi_setup, "BLE_SETUP_TIMEOUT", 0.2)
        with pytest.raises(TimeoutError):
            await wifi_setup.provision(hass, device, wifi, settings)
    elif outcome == "restore_failed":
        assert await wifi_setup.provision(hass, device, wifi, settings) == WIFI_MAC
    else:
        with pytest.raises(ConnectionError, match="rejected"):
            await wifi_setup.provision(hass, device, wifi, settings)
    assert written == wifi + settings
    assert gatt.stop_notify.await_count == 2
    gatt.start_notify.assert_awaited_with(characteristic, device.client.notify_callback)
    assert device.client._safe_disconnect.await_count == int(outcome == "restore_failed")
    assert not device.client._command_lock.locked()
    assert broker.unsubscribe.call_count == int(outcome in {"success", "no_mqtt", "restore_failed"})


@pytest.mark.asyncio
@pytest.mark.parametrize("unexpected_failure", [False, True])
async def test_poll_recovers_immediately_on_broker_reconnect(broker, unexpected_failure):
    c = client()
    try:
        assert await c.ensure_connected()
        broker.is_connected.return_value = False
        c._broker_status(False)
        broker.is_connected.return_value = True
        if unexpected_failure:
            original_read = c.request_state
            failed = asyncio.Event()

            async def fail_once(**kwargs):
                c.request_state = original_read
                failed.set()
                raise RuntimeError("unexpected read failure")

            c.request_state = fail_once
            c._broker_status(True)
            await asyncio.wait_for(failed.wait(), 1)
            assert not c._monitor.done()
            assert not c._online
        refreshed = asyncio.Event()
        c.status_callback.side_effect = lambda connected: refreshed.set() if connected else None
        c._broker_status(True)
        await asyncio.wait_for(refreshed.wait(), 1)
        assert c._online
    finally:
        await c.stop()


def test_topic_matches_apk_not_ble_address():
    assert native_topic(WIFI_MAC) == "cyd/dev/Fluval/Fluval-532/AABBCCDDEE02"


@pytest.mark.parametrize("mac", ["", "../../a", "#", "+", "AA:BB:CC:DD:EE:GG", "AABBCCDDEE0200"])
def test_invalid_topic_identity(mac):
    with pytest.raises(ValueError):
        native_topic(mac)


def test_native_state_envelope():
    assert decode_uplink(report(STATE)) == protocol.cbor_map(STATE)
    assert decode_uplink(report(STATE).encode()) == protocol.cbor_map(STATE)


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        "x" * 16385,
        "id:1;type:heartbeat;;",
        "id:1;type:version_post;version:10;;",
        "id:1;id:2;type:property_post;param:a0;;",
        "id:1;type:property_post;param:0;;",
        "id:1;type:property_post;param:ffff;;",
        "id:1;type:property_post;param:a0;;",
        "id:1;type:property_post;param:a1616101;;",
        "id:1;type:property_post;param:a118670000;;",
        "id:1;type:property_post;param:a1186700",
        "id:1;type:upgrade;param:a1186700;;",
    ],
)
def test_invalid_messages_cannot_supply_state(payload):
    assert decode_uplink(payload) is None


@pytest.mark.asyncio
async def test_subscribe_before_read_and_complete_cleanup(broker):
    c = client()
    assert await c.ensure_connected()
    assert c.observed_state == STATE
    assert broker.async_subscribe.call_args.args[1].endswith("/uplink")
    assert broker.async_subscribe.call_args.kwargs == {"qos": 0, "encoding": None}
    assert broker.async_publish.call_args.args[2] == "id:1;type:property_get;;"
    assert broker.async_publish.call_args.kwargs == {"qos": 0, "retain": False}
    await c.stop()
    broker.unsubscribe.assert_called_once()
    broker.unsubscribe_status.assert_called_once()
    assert not await c.ensure_connected()
    await c.stop()
    broker.unsubscribe.assert_called_once()


@pytest.mark.asyncio
async def test_write_uses_existing_cbor_and_fresh_readback(broker):
    c = client()
    try:
        assert await c.send_now(protocol.wifi_single_zone_packet(0, 61), expected_state={110: 61})
        packets = [call.args[2] for call in broker.async_publish.call_args_list]
        assert any(
            "type:property_set;param:" + protocol.wifi_single_zone_packet(0, 61).hex() in packet for packet in packets
        )
        assert c.last_write_verified
        assert broker.state[110] == 61
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_retained_or_old_state_does_not_confirm_online(broker):
    c = client()
    await c.start()
    broker.async_publish.side_effect = None
    c._message(SimpleNamespace(payload=report(STATE), retain=True))
    assert not c.observed_state
    c._message(SimpleNamespace(payload=report(STATE), retain=False))
    assert not await c.request_state(timeout=0.01)
    assert not c._online
    await c.stop()


@pytest.mark.asyncio
async def test_mismatching_readback_is_not_success(broker):
    c = client()
    try:
        assert not await c.send_now(protocol.wifi_switch_packet(True), expected_state={104: False})
        assert not c.last_write_verified
        assert c.last_verification_mismatches[104]["confirmed"] is True
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_broker_disconnect_clears_online_and_blocks_publish(broker):
    c = client()
    assert await c.ensure_connected()
    broker.is_connected.return_value = False
    c._broker_status(False)
    broker.async_publish.reset_mock()
    assert not await c.send_now(protocol.wifi_switch_packet(False))
    broker.async_publish.assert_not_called()
    assert not c._online
    await c.stop()


@pytest.mark.asyncio
async def test_unload_wakes_pending_read(broker):
    c = client()
    await c.start()
    broker.async_publish.side_effect = None
    read = asyncio.create_task(c.request_state(timeout=30))
    await asyncio.sleep(0)
    await c.stop()
    assert not await asyncio.wait_for(read, 0.2)
    c.update_callback.reset_mock()
    c._message(SimpleNamespace(payload=report(STATE), retain=False))
    c.update_callback.assert_not_called()


@pytest.mark.asyncio
async def test_split_maps_are_accumulated_only_within_fresh_read(broker):
    c = client()
    await c.start()
    c.state_validator = lambda state: all(key in state for key in STATE)

    async def split(*args, **kwargs):
        c._message(SimpleNamespace(payload=report({103: 0, 104: True}), retain=False))
        c._message(
            SimpleNamespace(payload=report({key: value for key, value in STATE.items() if key >= 110}), retain=False)
        )

    broker.async_publish.side_effect = split
    assert await c.request_state(state_validator=c.state_validator)
    await c.stop()


@pytest.mark.asyncio
async def test_native_device_never_looks_up_ble_and_keeps_entity_ids(broker, monkeypatch):
    import importlib

    monkeypatch.setattr(
        importlib.import_module("custom_components.fluvalble.core.device").bluetooth,
        "async_ble_device_from_address",
        MagicMock(side_effect=AssertionError("No BLE lookup allowed")),
    )
    d = MqttDevice(
        "Tank",
        hass=MagicMock(async_create_background_task=create_background_task),
        config_data={"mac": BLE_MAC, "wifi_mac": WIFI_MAC},
    )
    try:
        assert await d._async_prepare_command()
        assert d.product_id == 532
        assert len(d.numbers()) == 4
        assert d.sensors() == ["last_seen"]
        entity = FluvalEntity(d, "channel_1")
        assert entity._attr_unique_id == "AABBCCDDEE01_channel_1"
        assert entity._attr_device_info["connections"] == {("mac", WIFI_MAC)}
        assert "gatt_connected" not in d.attribute("connection")["extra"]
    finally:
        await d.client.stop()


@pytest.mark.asyncio
async def test_transport_options_preserve_entry_identity_and_settings(broker):
    flow = OptionsFlowHandler()
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda _: [SimpleNamespace(disabled_by=None)])
    )
    flow.config_entry.data = {"mac": BLE_MAC, "product_id": 532}
    flow.config_entry.options = {"active_time": 60, "lamp_profile": "aquasky3"}
    flow.async_create_entry = MagicMock(side_effect=lambda **kwargs: kwargs)
    flow.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
    assert (await flow.async_step_init())["step_id"] == "connection"
    assert (await flow.async_step_connection({"transport": "local_mqtt"}))["step_id"] == "mqtt_options"
    result = await flow.async_step_mqtt_options({"wifi_mac": WIFI_MAC})
    assert result["data"]["transport"] == "local_mqtt"
    assert result["data"]["active_time"] == 60
    assert flow.config_entry.data["mac"] == BLE_MAC
    flow.config_entry.options = result["data"]
    result = await flow.async_step_bluetooth_options({"active_time": 60})
    assert result["data"]["transport"] == "bluetooth"
    assert result["data"]["wifi_mac"] == WIFI_MAC


@pytest.mark.asyncio
@pytest.mark.parametrize("entries", [[], [SimpleNamespace(disabled_by="user")]])
async def test_ble_only_setup_and_options_keep_original_flow(monkeypatch, entries):
    from importlib import import_module

    module = import_module("custom_components.fluvalble.config_flow")
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _: entries))
    flow = ConfigFlow()
    flow.hass = hass
    flow._async_current_entries = MagicMock(return_value=[])
    flow.async_step_manual = AsyncMock(return_value={"step_id": "manual"})
    monkeypatch.setattr(module, "_get_discovered_devices", AsyncMock(return_value={}))
    assert (await flow.async_step_user())["step_id"] == "manual"
    assert module.MQTT_ENTRY not in flow._device_options(set())

    options = OptionsFlowHandler()
    options.hass = hass
    options.config_entry.data = {"mac": BLE_MAC, "product_id": 532}
    options.config_entry.options = {"active_time": 60}
    options.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
    options.add_suggested_values_to_schema = MagicMock()
    assert (await options.async_step_init())["step_id"] == "init"
    options.config_entry.options = {"transport": "local_mqtt", "wifi_mac": WIFI_MAC, "active_time": 60}
    options.async_create_entry = MagicMock(side_effect=lambda **kwargs: kwargs)
    updated = (await options.async_step_init({"active_time": 90}))["data"]
    assert updated == {"transport": "local_mqtt", "wifi_mac": WIFI_MAC, "active_time": 90}


def test_ble_import_does_not_load_optional_mqtt_modules():
    conftest = Path(__file__).resolve().with_name("conftest.py")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; runpy.run_path(sys.argv[1]); "
            "import custom_components.fluvalble.config_flow, custom_components.fluvalble.core.device; "
            "assert not any(name in sys.modules for name in ("
            "'homeassistant.components.mqtt', 'custom_components.fluvalble.core.mqtt_client', "
            "'custom_components.fluvalble.wifi_setup'))",
            str(conftest),
        ],
        check=True,
        cwd=conftest.parent.parent,
    )


@pytest.mark.asyncio
async def test_mqtt_downlink_allows_only_property_messages(broker):
    c = client()
    for kind, packet in [
        ("ota", b"url"),
        ("url", b"http"),
        ("http", b"ota"),
        ("property_get", b"x"),
        ("property_set", None),
        ("property_set;url:http", b"x"),
        ("property_set", protocol.cbor_map({200: "http://example.invalid/fw.bin"})),
        ("property_set", protocol.cbor_map({104: True, 201: "ota"})),
        ("property_set", protocol.cbor_map({123: 1})),
        ("property_set", protocol.cbor_map({104: "find"})),
        ("property_set", protocol.cbor_map({52: "not-find"})),
        ("property_set", protocol.cbor_map({114: ["unexpected"]})),
        ("property_set", bytes.fromhex("a21868f41868f5")),
        ("property_set", protocol.spp_command({2: True})),
        ("property_set", b"not CBOR"),
    ]:
        with pytest.raises(ValueError, match="Unsupported"):
            await c._publish(kind, packet)
    broker.async_publish.assert_not_awaited()
    await c.start()
    try:
        await c._publish("property_get")
        await c._publish("property_set", protocol.cbor_map({104: True}))
        payloads = [call.args[2] for call in broker.async_publish.await_args_list]
        assert payloads == ["id:1;type:property_get;;", "id:2;type:property_set;param:a11868f5;;"]
        assert not any(token in payload.lower() for payload in payloads for token in ("ota", "url", "http"))
        for packet in (
            protocol.wifi_find_packet(),
            protocol.wifi_dst_packet(True),
            protocol.wifi_timezone_packet(),
            protocol.wifi_clock_packet(),
            protocol.wifi_mode_packet(1),
            protocol.wifi_effect_packet(4),
            protocol.wifi_all_zone_packet([10, 20, 30, 40, 50]),
            protocol.cbor_map({114: [360, 420], 115: [1020, 1080], 116: 65535, 117: b"1234", 118: b"0000"}),
            protocol.cbor_map({120: 2, 121: [360, 1080], 122: b"12340000"}),
        ):
            await c._publish("property_set", packet)
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_mqtt_options_require_broker_and_valid_wifi_mac(broker):
    flow = OptionsFlowHandler()
    flow.hass = object()
    flow.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
    assert (await flow.async_step_mqtt_options({"wifi_mac": "#"}))["errors"] == {"base": "invalid_format"}
    broker.async_wait_for_mqtt_client.return_value = False
    assert (await flow.async_step_mqtt_options({"wifi_mac": WIFI_MAC}))["errors"] == {"base": "mqtt_required"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured_host", "source_ip", "default_host"),
    [
        ("mqtt.internal", "192.0.2.10", "mqtt.internal"),
        ("core-mosquitto", "192.0.2.10", "192.0.2.10"),
        ("localhost", "192.0.2.10", "192.0.2.10"),
        ("127.0.0.1", "192.0.2.10", "192.0.2.10"),
        ("::1", "192.0.2.10", "192.0.2.10"),
        ("core-mosquitto", "127.0.0.1", ""),
        ("core-mosquitto", None, ""),
    ],
)
async def test_provisioning_defaults_to_ha_broker_and_requires_host_mismatch_confirmation(
    broker, monkeypatch, configured_host, source_ip, default_host
):
    import importlib
    from types import ModuleType

    from homeassistant.exceptions import HomeAssistantError

    class Marker(str):
        def __new__(cls, name, *, default=None):
            marker = super().__new__(cls, name)
            marker.default = lambda: default
            return marker

    vol = importlib.import_module("voluptuous")
    monkeypatch.setattr(vol, "Required", Marker)
    monkeypatch.setattr(vol, "Optional", Marker)
    selector = ModuleType("homeassistant.helpers.selector")
    selector.TextSelector = lambda _: str
    selector.TextSelectorConfig = dict
    selector.TextSelectorType = SimpleNamespace(PASSWORD="password")
    monkeypatch.setitem(sys.modules, selector.__name__, selector)
    network = ModuleType("homeassistant.components.network")
    network.async_get_source_ip = AsyncMock(return_value=source_ip)
    if source_ip is None:
        network.async_get_source_ip.side_effect = HomeAssistantError("No usable adapter")
    monkeypatch.setitem(sys.modules, network.__name__, network)
    monkeypatch.setattr(sys.modules["homeassistant.components"], "network", network, raising=False)
    integration = importlib.import_module("custom_components.fluvalble")
    wifi_setup = importlib.import_module("custom_components.fluvalble.wifi_setup")
    device = object()
    provision = AsyncMock(return_value=WIFI_MAC)
    monkeypatch.setattr(integration, "entry_runtime_data", lambda *_: SimpleNamespace(device=device))
    monkeypatch.setattr(wifi_setup, "provision", provision)
    flow = OptionsFlowHandler()
    mqtt_entry = SimpleNamespace(disabled_by=None, data={"broker": configured_host})
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _: [mqtt_entry]))
    flow.config_entry.data = {"mac": BLE_MAC, "product_id": 532}
    flow.config_entry.options = {}
    flow.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
    flow.async_create_entry = MagicMock(side_effect=lambda **kwargs: kwargs)
    form = await flow.async_step_provision_wifi()
    fields = {str(key): key for key in form["data_schema"].schema}
    assert fields["broker_host"].default() == default_host
    assert network.async_get_source_ip.await_count == int(configured_host != "mqtt.internal")
    values = {
        "confirm": True,
        "ssid": "Tank",
        "wifi_password": "wifi-secret",
        "broker_host": "broker.lan",
        "broker_port": 1883,
        "broker_user": "tank",
        "broker_password": "mqtt-secret",
    }
    warning = await flow.async_step_provision_wifi(values)
    assert warning["errors"] == {"base": "wifi_broker_host_mismatch"}
    provision.assert_not_awaited()
    for key in warning["data_schema"].schema:
        if str(key) in {"wifi_password", "broker_password"}:
            assert key.default() == ""
    for field in ("ssid", "wifi_password", "broker_password"):
        invalid = {**values, "confirm_broker_host": True, field: "bad;value"}
        result = await flow.async_step_provision_wifi(invalid)
        assert result["errors"] == {"base": "wifi_invalid_characters"}
        provision.assert_not_awaited()
    if default_host:
        result = await flow.async_step_provision_wifi({**values, "broker_host": default_host})
        provision.assert_awaited_once()
        assert provision.await_args.args[3].startswith(f"host:{default_host};".encode())
        assert result["data"] == {"wifi_mac": WIFI_MAC, "transport": "local_mqtt"}
        provision.reset_mock()
    result = await flow.async_step_provision_wifi({**values, "confirm_broker_host": True})
    provision.assert_awaited_once()
    assert result["data"] == {"wifi_mac": WIFI_MAC, "transport": "local_mqtt"}


def test_provisioning_frames_are_exact_and_use_local_credentials():
    assert wifi_frame("Tank", "wifi-secret", -210) == b"ssid:Tank;password:wifi-secret;timeoffset:-210;;"
    assert (
        broker_frame("mqtt.lan", 1883, "tank", "lamp", "secret")
        == b"host:mqtt.lan;port:1883;clientid:tank;username:lamp;password:secret;;"
    )
    assert provisioning_wifi_mac("brand:Fluval;mac:AABBCCDDEE02;version:10;;") == WIFI_MAC
    assert provisioning_wifi_mac("ip:192.0.2.1;;") is None


@pytest.mark.asyncio
async def test_initial_mqtt_flow_uses_ble_identity_for_future_switching(broker):
    flow = ConfigFlow()
    flow.hass = object()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow._async_current_entries = MagicMock(return_value=[])
    flow.async_create_entry = MagicMock(side_effect=lambda **kwargs: kwargs)
    result = await flow.async_step_local_mqtt({"mac": BLE_MAC, "wifi_mac": WIFI_MAC, "name": "Tank"})
    assert result["data"]["mac"] == BLE_MAC
    assert result["data"]["wifi_mac"] == WIFI_MAC
    flow.async_set_unique_id.assert_awaited_once_with(BLE_MAC.lower())


@pytest.mark.parametrize("value", ["x;y", "x:y", "x\n", "x\x00", "é", "x" * 64])
def test_provisioning_rejects_injected_fields(value):
    with pytest.raises(ValueError):
        broker_frame("mqtt.lan", 1883, "tank", "user", value)


@pytest.mark.parametrize("port", [0, -1, 65536, True])
def test_provisioning_rejects_invalid_port(port):
    with pytest.raises(ValueError):
        broker_frame("mqtt.lan", port, "tank", "", "")


@pytest.mark.asyncio
async def test_entry_setup_reload_unload_has_no_ble_registration(broker, monkeypatch):
    import importlib

    integration = importlib.import_module("custom_components.fluvalble")
    storage = importlib.import_module("custom_components.fluvalble.manual_settings")
    entry = SimpleNamespace(
        entry_id="mqtt_test",
        title="Tank",
        data={"mac": BLE_MAC, "wifi_mac": WIFI_MAC, "product_id": 532},
        options={"transport": "local_mqtt"},
        runtime_data=None,
    )
    hass = SimpleNamespace(
        data={},
        async_create_background_task=create_background_task,
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(), async_unload_platforms=AsyncMock(return_value=True)
        ),
    )
    attach = MagicMock()
    monkeypatch.setattr(storage, "async_manual_settings_storage", AsyncMock(return_value=attach))
    monkeypatch.setattr(integration, "_sync_connection_diagnostic_registry_entries", MagicMock())
    monkeypatch.setattr(
        integration.bluetooth, "async_register_callback", MagicMock(side_effect=AssertionError("No BLE registration"))
    )
    assert await integration.async_setup_entry(hass, entry)
    first = entry.runtime_data.device.client
    attach.assert_called_once()
    assert await integration.async_unload_entry(hass, entry)
    assert first._stopping and not first._unsubscribers and first._monitor is None
    assert await integration.async_setup_entry(hass, entry)
    assert entry.runtime_data.device.client is not first
    assert await integration.async_unload_entry(hass, entry)
    assert broker.unsubscribe.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_client", [True, False])
async def test_entry_setup_failure_leaves_no_subscription_or_task(broker, monkeypatch, missing_client):
    import importlib

    integration = importlib.import_module("custom_components.fluvalble")
    storage = importlib.import_module("custom_components.fluvalble.manual_settings")
    from homeassistant.exceptions import ConfigEntryNotReady

    entry = SimpleNamespace(
        entry_id="mqtt_failure",
        title="Tank",
        data={"mac": BLE_MAC, "wifi_mac": WIFI_MAC, "product_id": 532, "transport": "local_mqtt"},
        options={},
        runtime_data=None,
    )
    hass = SimpleNamespace(data={}, async_create_background_task=create_background_task)
    cleanup = MagicMock()

    async def storage_setup(hass, config_entry):
        config_entry.runtime_data.unload_callbacks.append(cleanup)
        return MagicMock()

    monkeypatch.setattr(storage, "async_manual_settings_storage", storage_setup)
    if missing_client:
        module = importlib.import_module("custom_components.fluvalble.core.mqtt_device")

        class DeviceWithoutClient(MqttDevice):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.client = None

        monkeypatch.setattr(module, "MqttDevice", DeviceWithoutClient)
    broker.async_publish.side_effect = None
    with pytest.raises(ConfigEntryNotReady):
        await integration.async_setup_entry(hass, entry)
    assert entry.entry_id not in hass.data[integration.DOMAIN]
    if not missing_client:
        assert entry.runtime_data.device.client._monitor is None
        broker.unsubscribe.assert_called_once()
    else:
        broker.async_subscribe.assert_not_awaited()
    cleanup.assert_called_once()


def test_transport_diagnostics_do_not_publish_wifi_identity():
    from custom_components.fluvalble.diagnostics import _redact_diagnostics

    assert WIFI_MAC not in str(_redact_diagnostics({"entry": {"data": {"wifi_mac": WIFI_MAC}}}))
    keys = ("ssid", "psk", "wifi_password", "broker_host", "broker_user", "broker_password", "client_id")
    raw = {key: "secret-" + key for key in keys}
    assert "secret-" not in str(_redact_diagnostics({"entry": {"options": raw}}))


def test_transport_switch_disables_only_inapplicable_diagnostics(monkeypatch):
    import importlib
    from types import ModuleType

    er = ModuleType("homeassistant.helpers.entity_registry")
    er.RegistryEntryDisabler = SimpleNamespace(INTEGRATION=object())
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", er)
    monkeypatch.setattr(sys.modules["homeassistant.helpers"], "entity_registry", er, raising=False)
    integration = importlib.import_module("custom_components.fluvalble")
    rows = [
        SimpleNamespace(entity_id="sensor.rssi", unique_id="AABB_rssi", disabled_by=None),
        SimpleNamespace(entity_id="sensor.source", unique_id="AABB_active_connection_source", disabled_by=None),
        SimpleNamespace(entity_id="sensor.seen", unique_id="AABB_last_seen", disabled_by=None),
    ]
    registry = MagicMock()
    monkeypatch.setattr(er, "async_get", MagicMock(return_value=registry), raising=False)
    monkeypatch.setattr(er, "async_entries_for_config_entry", MagicMock(return_value=rows), raising=False)
    integration._sync_connection_diagnostic_registry_entries(object(), SimpleNamespace(entry_id="x"), native_mqtt=True)
    assert registry.async_update_entity.call_count == 2
    registry.async_remove.assert_not_called()
    for row in rows[:2]:
        row.disabled_by = er.RegistryEntryDisabler.INTEGRATION
    registry.async_update_entity.reset_mock()
    integration._sync_connection_diagnostic_registry_entries(object(), SimpleNamespace(entry_id="x"))
    assert registry.async_update_entity.call_count == 2


@pytest.mark.asyncio
async def test_native_controls_use_rgbw_channels_and_native_schedule_packets(broker):
    d = MqttDevice(
        "Tank",
        hass=MagicMock(async_create_background_task=create_background_task),
        config_data={"mac": BLE_MAC, "wifi_mac": WIFI_MAC},
    )
    d.configure_manual_settings(None, AsyncMock())
    try:
        assert await d.async_set_channels({"channel_1": 61, "channel_2": 0, "channel_3": 83, "channel_4": 0})
        assert d.values["channel_1"] == 61
        assert d.values["channel_4"] == 0
        assert await d.async_set_channels({channel: 0 for channel in d.numbers()})
        assert not d.values["led_on_off"]
        bank = d._last_manual_settings
        assert bank["channel_1"] == 61
    finally:
        await d.client.stop()


@pytest.mark.asyncio
async def test_publish_timeout_returns_command_failure(broker):
    c = client()
    assert await c.ensure_connected()

    async def hang(*args, **kwargs):
        await asyncio.sleep(10)

    broker.async_publish.side_effect = hang
    try:
        assert not await asyncio.wait_for(c.send_now(protocol.wifi_switch_packet(False), verify=False), 0.3)
        assert "Timed out publishing" in c.last_error
        assert not c._online
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_mqtt_runtime_removal_is_reported_as_offline(broker):
    c = client()
    assert await c.ensure_connected()
    broker.is_connected.side_effect = KeyError("mqtt")
    try:
        assert not await c.send_now(protocol.wifi_switch_packet(False))
        assert not c._online
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_native_disconnect_does_not_create_ble_reachability_timer(broker):
    d = MqttDevice(
        "Tank",
        hass=MagicMock(async_create_background_task=create_background_task),
        config_data={"mac": BLE_MAC, "wifi_mac": WIFI_MAC},
    )
    d._schedule_reachability_refresh = MagicMock(side_effect=AssertionError("No BLE grace timer"))
    assert await d.client.ensure_connected()
    await d.client.stop()
    assert not d.is_reachable()
    assert d._reachability_unsub is None


@pytest.mark.asyncio
async def test_provisioning_does_not_accept_old_broker_notification(monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts/provision_native_mqtt.py"
    spec = importlib.util.spec_from_file_location("provision_native_mqtt", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeBleakClient:
        def __init__(self, *args, **kwargs):
            self.services = SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(properties=["write"]))
            self.frame = bytearray()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def start_notify(self, _uuid, callback):
            self.callback = callback

        async def write_gatt_char(self, _char, data, **kwargs):
            self.frame.extend(data)
            if self.frame.endswith(b";;"):
                if self.frame.startswith(b"ssid:"):
                    self.callback(None, b"ip:192.0.2.1;;mqtt:connected;;")
                self.frame.clear()

    monkeypatch.setattr(sys.modules["bleak"], "BleakClient", FakeBleakClient)
    args = SimpleNamespace(ble_address=BLE_MAC)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            module.provision(
                args,
                b"ssid:Tank;password:x;timeoffset:0;;",
                b"host:mqtt.lan;port:1883;clientid:tank;username:;password:;;",
            ),
            0.1,
        )
