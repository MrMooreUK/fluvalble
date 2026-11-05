"""Schedule colour edits preserve hardware timing and use native writes."""

from copy import deepcopy
from contextlib import asynccontextmanager
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.fluvalble.core.schedule_colours import colour_packet, replace_schedule_colours
from custom_components.fluvalble.core import protocol


@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
@pytest.mark.parametrize("success", [True, False])
def test_classic_commit_settle_precedes_return(transport, success):
    from custom_components.fluvalble.schedule_editor import _write_schedule_packet

    events = []

    async def send(packet):
        events.append("write")
        return success

    async def wait(delay):
        assert delay == 1.5
        events.append("settled")

    device = SimpleNamespace(_async_send_packet=AsyncMock(side_effect=send))
    with patch("custom_components.fluvalble.schedule_editor.asyncio.sleep", side_effect=wait):
        assert asyncio.run(_write_schedule_packet(device, b"packet", transport)) is success
    assert events == (["write", "settled"] if success and transport == "classic" else ["write"])


def test_editor_registers_static_asset_and_commands_once():
    from custom_components.fluvalble.schedule_editor import async_setup_editor

    frontend = SimpleNamespace(add_extra_js_url=MagicMock())
    hass = SimpleNamespace(data={"fluvalble": {}}, http=SimpleNamespace(register_static_path=MagicMock()))
    with (
        patch.dict(sys.modules, {"homeassistant.components.frontend": frontend}),
        patch("custom_components.fluvalble.schedule_editor.vol.Any", lambda *args: object, create=True),
        patch("custom_components.fluvalble.schedule_editor.websocket_api.async_register_command") as register,
    ):
        asyncio.run(async_setup_editor(hass))
        asyncio.run(async_setup_editor(hass))
    hass.http.register_static_path.assert_called_once()
    frontend.add_extra_js_url.assert_called_once()
    assert register.call_count == 2


@pytest.mark.parametrize("count", [4, 5])
@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
def test_auto_colour_write_preserves_times(count, transport):
    original = {
        "sunrise": {"hour": 23, "minute": 30, "ramp": 60},
        "sunset": {"hour": 20, "minute": 0, "ramp": 30},
        "sleep": {"hour": 22, "minute": 0},
        "day_levels": [50] * count,
        "night_levels": [5] * count,
    }
    before = deepcopy(original)
    packet = colour_packet(original, transport=transport, channel_count=count, levels=[25] * count, target="day")
    assert original == before
    if transport == "facebd":
        assert protocol.decode_cbor_map(packet) == {117: bytes([25] * count)}
    elif transport == "spp":
        assert protocol.decode_cbor_update(packet) == {11: bytes([25] * count)}
    else:
        assert packet[:6] == bytes([0x68, 7, 23, 30, 0, 30])
        assert packet[6 : 6 + count] == bytes([25] * count)
        assert packet[-4:-1] == bytes([1, 22, 0])


@pytest.mark.parametrize("count", [4, 5])
@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
def test_pro_changes_only_selected_point(count, transport):
    original = [{"minute": time, **{f"channel_{i}": 10 for i in range(1, count + 1)}} for time in [60, 480, 900, 1200]]
    before = deepcopy(original)
    edited = replace_schedule_colours(original, channel_count=count, levels=[70] * count, target=2)
    assert original == before
    assert [point["minute"] for point in edited] == [60, 480, 900, 1200]
    assert edited[0] == before[0]
    assert edited[2]["channel_1"] == 70
    assert colour_packet(original, transport=transport, channel_count=count, levels=[70] * count, target=2)


@pytest.mark.parametrize("levels", [[True] * 4, [-1] * 4, [101] * 4, [1] * 5])
def test_invalid_levels_are_rejected(levels):
    with pytest.raises(ValueError):
        replace_schedule_colours({"day_levels": [0] * 4}, channel_count=4, levels=levels, target="day")


def auto_schedule(count=4):
    return {
        "sunrise": {"hour": 8, "minute": 0, "ramp": 30},
        "sunset": {"hour": 20, "minute": 0, "ramp": 30},
        "sleep": {"hour": 22, "minute": 0},
        "day_levels": [50] * count,
        "night_levels": [5] * count,
    }


@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
@pytest.mark.parametrize("count", [4, 5])
@pytest.mark.parametrize("sleep_enabled", [True, False])
def test_auto_time_edits_use_native_formats(transport, count, sleep_enabled):
    original = auto_schedule(count)
    original["sleep"] = {"hour": 22, "minute": 0} if sleep_enabled else None
    before = deepcopy(original)
    times = {
        "sunrise": {"hour": 23, "minute": 30, "ramp": 60},
        "sunset": {"hour": 4, "minute": 0, "ramp": 45},
        "sleep": {"hour": 5, "minute": 0} if sleep_enabled else None,
    }
    expected = replace_schedule_colours(original, channel_count=count, levels=[60] * count, target="day", times=times)
    packet = colour_packet(
        original, transport=transport, channel_count=count, levels=[60] * count, target="day", times=times
    )
    assert original == before
    assert expected["night_levels"] == before["night_levels"]
    if transport == "facebd":
        fields = protocol.decode_cbor_map(packet)
        assert fields[114] == [1410, 30]
        assert fields[115] == [195, 240]
        assert fields[116] == (300 if sleep_enabled else 65535)
        assert protocol.decode_wifi_auto_schedule(fields, channel_count=count) == expected
    elif transport == "spp":
        fields = protocol.decode_cbor_update(packet)
        assert fields[8] == bytes([23, 30, 60])
        assert fields[9] == bytes([4, 0, 45])
        assert fields[10] == (bytes([5, 0]) if sleep_enabled else b"\xff\xff")
        assert fields[12] == bytes([5] * count)
    else:
        assert packet[2:6] == bytes([23, 30, 0, 30])
        assert packet[6 + count : 10 + count] == bytes([3, 15, 4, 0])
        assert packet[-4:-1] == bytes([1, 5, 0]) if sleep_enabled else len(packet) == 11 + count * 2


@pytest.mark.parametrize("transport", ["classic", "facebd", "spp"])
@pytest.mark.parametrize("count", [4, 5])
def test_pro_time_changes_preserve_other_points_and_channels(transport, count):
    original = [{"minute": time, **{f"channel_{i}": i for i in range(1, count + 1)}} for time in [60, 480, 900, 1200]]
    before = deepcopy(original)
    packet = colour_packet(
        original, transport=transport, channel_count=count, levels=list(range(1, count + 1)), target=1, times=500
    )
    expected = deepcopy(original)
    expected[1]["minute"] = 500
    if transport == "facebd":
        decoded = protocol.decode_wifi_pro_schedule(protocol.decode_cbor_map(packet), channel_count=count)
    elif transport == "spp":
        decoded = protocol.decode_spp_pro_schedule(protocol.decode_cbor_update(packet), channel_count=count)
        decoded = [
            {
                "minute": int(point["time"][:2]) * 60 + int(point["time"][3:]),
                **{f"channel_{i}": value for i, value in enumerate(point["levels"], 1)},
            }
            for point in decoded
        ]
    else:
        decoded = protocol.decode_old_pro_schedule(bytes([2]) + packet[2:-1], channel_count=count)
    assert decoded == expected
    assert original == before


@pytest.mark.parametrize("times", [-1, 1440, True, 480.5, 60, 1100])
def test_pro_rejects_invalid_duplicate_or_out_of_order_time(times):
    points = [{"minute": minute, **{f"channel_{i}": 0 for i in range(1, 5)}} for minute in [60, 480, 900, 1200]]
    with pytest.raises(ValueError):
        colour_packet(points, transport="classic", channel_count=4, levels=[0] * 4, target=1, times=times)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sunrise", {"hour": 24, "minute": 0, "ramp": 30}),
        ("sunrise", {"hour": 8, "minute": 60, "ramp": 30}),
        ("sunrise", {"hour": True, "minute": 0, "ramp": 30}),
        ("sunrise", {"hour": 8, "minute": 0, "ramp": 241}),
        ("sunrise", {"hour": 8, "minute": 0, "ramp": -1}),
        ("sunset", {"hour": 8, "minute": 10, "ramp": 30}),
        ("sleep", {"hour": 12, "minute": 0}),
    ],
)
def test_invalid_auto_times_are_rejected(field, value):
    original = auto_schedule()
    times = {name: deepcopy(original[name]) for name in ("sunrise", "sunset", "sleep")}
    times[field] = value
    with pytest.raises(ValueError):
        colour_packet(original, transport="facebd", channel_count=4, levels=[50] * 4, target="day", times=times)


@pytest.mark.parametrize("confirmed", [True, False])
def test_editor_time_save_requires_exact_hardware_readback(confirmed):
    from custom_components.fluvalble.schedule_editor import async_setup_editor

    original = auto_schedule()
    times = {name: deepcopy(original[name]) for name in ("sunrise", "sunset", "sleep")}
    times["sunrise"]["minute"] = 15
    expected = replace_schedule_colours(original, channel_count=4, levels=[50] * 4, target="day", times=times)

    @asynccontextmanager
    async def transaction():
        yield

    device = SimpleNamespace(
        command_transaction=transaction,
        numbers=lambda: range(4),
        _uses_wifi_protocol=lambda: True,
        _uses_spp_protocol=lambda: False,
        values={"mode": "automatic", "native_auto_schedule": original},
        _async_send_packet=AsyncMock(return_value=True),
    )

    async def refresh():
        if device._async_send_packet.await_count and confirmed:
            device.values["native_auto_schedule"] = expected
        return True

    device.async_refresh_state = refresh
    hass = SimpleNamespace(
        data={"fluvalble": {}},
        http=SimpleNamespace(register_static_path=MagicMock()),
        config_entries=SimpleNamespace(async_get_entry=lambda _: SimpleNamespace(domain="fluvalble")),
    )
    connection = SimpleNamespace(require_admin=MagicMock(), send_result=MagicMock(), send_error=MagicMock())
    with (
        patch.dict(sys.modules, {"homeassistant.components.frontend": SimpleNamespace(add_extra_js_url=MagicMock())}),
        patch("custom_components.fluvalble.schedule_editor.vol.Any", lambda *args: object, create=True),
        patch("custom_components.fluvalble.schedule_editor.websocket_api.async_register_command") as register,
        patch("custom_components.fluvalble.entry_runtime_data", return_value=SimpleNamespace(device=device)),
    ):
        asyncio.run(async_setup_editor(hass))
        save = register.call_args_list[1].args[1]
        asyncio.run(
            save(
                hass,
                connection,
                {
                    "id": 1,
                    "entry_id": "fixture",
                    "schedule": "auto",
                    "target": "day",
                    "levels": [50] * 4,
                    "baseline": deepcopy(original),
                    "times": times,
                },
            )
        )
    device._async_send_packet.assert_awaited_once()
    connection.require_admin.assert_called_once()
    if confirmed:
        connection.send_result.assert_called_once_with(1, True)
        connection.send_error.assert_not_called()
    else:
        connection.send_error.assert_called_once()
        connection.send_result.assert_not_called()
