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

# FluvalConnect's four-effect picker uses weatherMeshIndex [4, 3, 1, 2].
# Its matching assets are weather_3, weather_7, weather_9, and weather_11.
# Preserve that APK picker order here; the values are the IDs sent on the wire.
FOUR_EFFECTS: Mapping[str, int] = {
    "Crescent moon": 4,
    "Partly cloudy": 3,
    "Lightning": 1,
    "Sun and lightning": 2,
}

# Backward-compatible public name retained for callers of earlier releases.
PLANT_PRO_EFFECTS = FOUR_EFFECTS


def effect_list() -> list[str]:
    """Return the classic effects in their stable Home Assistant order."""
    return [EFFECT_NONE, *WEATHER_EFFECTS]


def effect_id(effect: str) -> int | None:
    """Return the classic effect ID for a Home Assistant effect name."""
    return WEATHER_EFFECTS.get(effect)


def effect_name(effect_id: int) -> str | None:
    """Return the Home Assistant name for a classic/FACEBD effect ID."""
    return next((name for name, value in WEATHER_EFFECTS.items() if value == effect_id), None)


def four_effect_list() -> list[str]:
    """Return the APK four-effect catalogue in picker order."""
    return [EFFECT_NONE, *FOUR_EFFECTS]


def four_effect_id(effect: str) -> int | None:
    """Return the wire ID for an APK four-effect name."""
    return FOUR_EFFECTS.get(effect)


def four_effect_name(effect_id: int) -> str | None:
    """Return the APK four-effect name for a wire ID."""
    return next((name for name, value in FOUR_EFFECTS.items() if value == effect_id), None)


def plant_pro_effect_list() -> list[str]:
    """Return the four-effect catalogue (compatibility wrapper)."""
    return four_effect_list()


def plant_pro_effect_id(effect: str) -> int | None:
    """Return a four-effect wire ID (compatibility wrapper)."""
    return four_effect_id(effect)


def plant_pro_effect_name(effect_id: int) -> str | None:
    """Return a four-effect name (compatibility wrapper)."""
    return four_effect_name(effect_id)
