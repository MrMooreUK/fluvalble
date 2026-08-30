"""Tests for classic APK-native effect metadata."""

from custom_components.fluvalble.core.effects import (
    EFFECT_NONE,
    WEATHER_EFFECTS,
    effect_id,
    effect_list,
)


def test_classic_weather_effect_catalog_is_stable():
    assert effect_list() == [EFFECT_NONE, *WEATHER_EFFECTS]
    assert effect_id("Lightning") == 2
    assert effect_id("Colour cycle") == 4
    assert effect_id("Full moon") == 9
    assert effect_id("Not a Fluval effect") is None
