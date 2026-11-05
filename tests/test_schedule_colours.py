"""Schedule colour edits preserve hardware timing and use native writes."""

from copy import deepcopy
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.fluvalble.core.schedule_colours import colour_packet, replace_schedule_colours
from custom_components.fluvalble.core import protocol


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
