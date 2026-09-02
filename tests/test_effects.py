"""Tests for classic APK-native effect metadata."""

from custom_components.fluvalble.core.effects import (
    EFFECT_NONE,
    FOUR_EFFECTS,
    PLANT_PRO_EFFECTS,
    WEATHER_EFFECTS,
    effect_id,
    effect_list,
    effect_name,
    four_effect_id,
    four_effect_list,
    four_effect_name,
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
    assert effect_name(2) == "Lightning"
    assert effect_name(99) is None


def test_four_effect_catalog_matches_apk_weather_mesh_index():
    assert list(FOUR_EFFECTS.items()) == [
        ("Crescent moon", 4),
        ("Partly cloudy", 3),
        ("Lightning", 1),
        ("Sun and lightning", 2),
    ]
    assert four_effect_list() == [EFFECT_NONE, *FOUR_EFFECTS]
    assert four_effect_id("Lightning") == 1
    assert four_effect_id("Sun and lightning") == 2
    assert four_effect_name(3) == "Partly cloudy"
    assert four_effect_name(99) is None


def test_plant_pro_effect_helpers_remain_compatible_aliases():
    assert PLANT_PRO_EFFECTS is FOUR_EFFECTS
    assert plant_pro_effect_list() == [EFFECT_NONE, *PLANT_PRO_EFFECTS]
    assert plant_pro_effect_id("Lightning") == 1
    assert plant_pro_effect_id("Crescent moon") == 4
    assert plant_pro_effect_name(3) == "Partly cloudy"
    assert plant_pro_effect_name(99) is None
