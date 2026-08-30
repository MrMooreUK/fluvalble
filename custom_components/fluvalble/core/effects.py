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


def effect_list() -> list[str]:
    """Return the classic effects in their stable Home Assistant order."""
    return [EFFECT_NONE, *WEATHER_EFFECTS]


def effect_id(effect: str) -> int | None:
    """Return the classic effect ID for a Home Assistant effect name."""
    return WEATHER_EFFECTS.get(effect)
