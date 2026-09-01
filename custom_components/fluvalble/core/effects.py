"""APK-native effects supported by classic Fluval controllers."""

from __future__ import annotations

from collections.abc import Mapping

EFFECT_NONE = "None"

# FluvalConnect maps these names to classic command 0x0A effect IDs. The APK
# presents its icons in the order 9, 10, 11, 5, 6, 7, 8, 1, 2, 3, 4.
WEATHER_EFFECTS: Mapping[str, int] = {
    "Thunderstorm": 1,
    "Lightning": 2,
    "Sun and lightning": 3,
    "Colour cycle": 4,
    "Mostly sunny": 5,
    "Partly sunny": 6,
    "Partly cloudy": 7,
    "Mostly cloudy": 8,
    "Full moon": 9,
    "Half moon": 10,
    "Crescent moon": 11,
}

# FluvalConnect exposes this four-effect subset on Plant Pro / mesh controllers
# through CBOR key 14. The app orders the IDs as 4, 3, 1, 2 in its picker,
# while the stable Home Assistant order below follows the effect IDs.
PLANT_PRO_EFFECTS: Mapping[str, int] = {
    "Thunderstorm": 1,
    "Lightning": 2,
    "Sun and lightning": 3,
    "Colour cycle": 4,
}


def effect_list() -> list[str]:
    """Return the classic effects in their stable Home Assistant order."""
    return [EFFECT_NONE, *WEATHER_EFFECTS]


def effect_id(effect: str) -> int | None:
    """Return the classic effect ID for a Home Assistant effect name."""
    return WEATHER_EFFECTS.get(effect)


def effect_name(effect_id: int) -> str | None:
    """Return the Home Assistant name for a classic/FACEBD effect ID."""
    return next((name for name, value in WEATHER_EFFECTS.items() if value == effect_id), None)


def plant_pro_effect_list() -> list[str]:
    """Return the Plant Pro effects in stable Home Assistant order."""
    return [EFFECT_NONE, *PLANT_PRO_EFFECTS]


def plant_pro_effect_id(effect: str) -> int | None:
    """Return the Plant Pro CBOR effect ID for a Home Assistant name."""
    return PLANT_PRO_EFFECTS.get(effect)


def plant_pro_effect_name(effect_id: int) -> str | None:
    """Return the Home Assistant name for a Plant Pro CBOR effect ID."""
    return next((name for name, value in PLANT_PRO_EFFECTS.items() if value == effect_id), None)
