"""Tests for classic APK-native effect metadata."""

from custom_components.fluvalble.core.effects import (
    EFFECT_NONE,
    PLANT_PRO_EFFECTS,
    WEATHER_EFFECTS,
    effect_id,
    effect_list,
    plant_pro_effect_id,
    plant_pro_effect_list,
    plant_pro_effect_name,
)


def test_classic_weather_effect_catalog_is_stable():
    assert effect_list() == [EFFECT_NONE, *WEATHER_EFFECTS]
    assert effect_id("Lightning") == 2
    assert effect_id("Colour cycle") == 4
    assert effect_id("Full moon") == 9
    assert effect_id("Not a Fluval effect") is None


def test_plant_pro_effect_catalog_matches_apk_ids():
    assert plant_pro_effect_list() == [EFFECT_NONE, *PLANT_PRO_EFFECTS]
    assert plant_pro_effect_id("Thunderstorm") == 1
    assert plant_pro_effect_id("Colour cycle") == 4
    assert plant_pro_effect_name(3) == "Sun and lightning"
    assert plant_pro_effect_name(99) is None
