"""Change schedule emitter levels without modifying fixture timing."""

from copy import deepcopy
from typing import Any

from . import protocol


def colour_packet(schedule: Any, *, transport: str, channel_count: int, levels: list[int], target: str | int) -> bytes:
    """Build a colour-only change from complete fixture-owned readback."""
    edited = replace_schedule_colours(schedule, channel_count=channel_count, levels=levels, target=target)
    if isinstance(edited, dict):
        if transport == "facebd":
            return protocol.cbor_map({117 if target == "day" else 118: bytes(levels)})
        if transport == "spp":
            return protocol.spp_command({11 if target == "day" else 12: bytes(levels)})
        sunrise, sunset = edited["sunrise"], edited["sunset"]
        start = sunrise["hour"] * 60 + sunrise["minute"]
        end = sunset["hour"] * 60 + sunset["minute"]
        times = (start, (start + sunrise["ramp"]) % 1440, (end - sunset["ramp"]) % 1440, end)
        payload = bytearray((0x68, 0x07))
        payload.extend((times[0] // 60, times[0] % 60, times[1] // 60, times[1] % 60))
        payload.extend(edited["day_levels"])
        payload.extend((times[2] // 60, times[2] % 60, times[3] // 60, times[3] % 60))
        payload.extend(edited["night_levels"])
        if edited.get("sleep") is not None:
            payload.extend((1, edited["sleep"]["hour"], edited["sleep"]["minute"]))
        return protocol.old_packet(bytes(payload))
    pro_times = [point["minute"] for point in edited]
    flat = bytes(point[f"channel_{index}"] for point in edited for index in range(1, channel_count + 1))
    if transport == "facebd":
        return protocol.cbor_map({120: len(edited), 121: pro_times, 122: flat})
    blob = bytearray((len(edited),))
    for point in edited:
        minute = point["minute"]
        blob.extend((minute // 60, minute % 60))
        blob.extend(point[f"channel_{index}"] for index in range(1, channel_count + 1))
    if transport == "spp":
        return protocol.spp_command({13: bytes(blob)})
    return protocol.old_packet(bytes((0x68, 0x10)) + blob)


def replace_schedule_colours(
    schedule: dict[str, Any] | list[dict[str, Any]],
    *,
    channel_count: int,
    levels: list[int],
    target: str | int,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Copy a complete readback and replace only the selected colour bank.

    Auto targets are day/night; Professional targets are existing point indexes.
    No caller can insert a point or modify a time through this interface.
    """
    if channel_count not in (4, 5) or len(levels) != channel_count:
        raise ValueError("Levels must match the fixture's physical channels")
    if any(type(level) is not int or not 0 <= level <= 100 for level in levels):
        raise ValueError("Channel levels must be integers from 0 to 100")
    result = deepcopy(schedule)
    if isinstance(result, dict):
        if target not in ("day", "night"):
            raise ValueError("Select the day or night bank")
        key = f"{target}_levels"
        if not isinstance(result.get(key), list) or len(result[key]) != channel_count:
            raise ValueError("Complete fixture schedule readback is required")
        result[key] = list(levels)
    elif isinstance(result, list):
        if type(target) is not int or not 0 <= target < len(result):
            raise ValueError("Select an existing Professional timepoint")
        point = result[target]
        if not isinstance(point, dict) or "minute" not in point:
            raise ValueError("Complete fixture schedule readback is required")
        for index, level in enumerate(levels, 1):
            key = f"channel_{index}"
            if key not in point:
                raise ValueError("Complete fixture channel readback is required")
            point[key] = level
    else:
        raise ValueError("Fixture schedule readback is required")
    return result
