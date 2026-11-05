"""Edit existing hardware schedule colours and optional timing fields."""

from copy import deepcopy
from typing import Any

from . import protocol


def colour_packet(
    schedule: Any, *, transport: str, channel_count: int, levels: list[int], target: str | int, times: Any = None
) -> bytes:
    """Build a native schedule change from complete fixture-owned readback."""
    edited = replace_schedule_colours(schedule, channel_count=channel_count, levels=levels, target=target, times=times)
    if isinstance(edited, dict):
        sunrise, sunset = edited["sunrise"], edited["sunset"]
        start = sunrise["hour"] * 60 + sunrise["minute"]
        end = sunset["hour"] * 60 + sunset["minute"]
        if times is not None and transport in ("facebd", "spp"):
            sleep = edited.get("sleep")
            if transport == "facebd":
                return protocol.cbor_map(
                    {
                        114: [start, (start + sunrise["ramp"]) % 1440],
                        115: [(end - sunset["ramp"]) % 1440, end],
                        116: 0xFFFF if sleep is None else sleep["hour"] * 60 + sleep["minute"],
                        117: bytes(edited["day_levels"]),
                        118: bytes(edited["night_levels"]),
                    }
                )
            return protocol.spp_command(
                {
                    8: bytes((sunrise["hour"], sunrise["minute"], sunrise["ramp"])),
                    9: bytes((sunset["hour"], sunset["minute"], sunset["ramp"])),
                    10: b"\xff\xff" if sleep is None else bytes((sleep["hour"], sleep["minute"])),
                    11: bytes(edited["day_levels"]),
                    12: bytes(edited["night_levels"]),
                }
            )
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
    times: Any = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Copy a complete readback and replace only the selected colour bank.

    Auto targets are day/night; Professional targets are existing point indexes.
    Optional times edit existing hardware fields without inserting timepoints.
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
        if times is not None:
            if not isinstance(times, dict) or set(times) != {"sunrise", "sunset", "sleep"}:
                raise ValueError("Provide sunrise, sunset and sleep timing")
            for name in ("sunrise", "sunset"):
                window = times[name]
                if not isinstance(window, dict) or set(window) != {"hour", "minute", "ramp"}:
                    raise ValueError("Provide a complete sunrise/sunset window")
                _clock_minute(window)
                if type(window["ramp"]) is not int or not 0 <= window["ramp"] <= 240:
                    raise ValueError("Sunrise and sunset ramps must be 0 to 240 minutes")
            start = _clock_minute(times["sunrise"])
            end = _clock_minute(times["sunset"])
            daylight = (end - start) % 1440
            if daylight == 0 or daylight < times["sunrise"]["ramp"] + times["sunset"]["ramp"]:
                raise ValueError("Sunrise and sunset must not overlap")
            if times["sleep"] is not None:
                if result.get("sleep") is None:
                    raise ValueError("Enable night shutoff in Fluval Connect before editing its time")
                sleep = _clock_minute(times["sleep"])
                if not 0 < (sleep - end) % 1440 < (start - end) % 1440:
                    raise ValueError("Sleep must be after sunset and before sunrise")
            result.update(deepcopy(times))
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
        if times is not None:
            if type(times) is not int or not 0 <= times < 1440:
                raise ValueError("Timepoints must be minutes from 00:00 to 23:59")
            point["minute"] = times
            minutes = [item["minute"] for item in result]
            if (
                len(set(minutes)) != len(minutes)
                or sum((minutes[(i + 1) % len(minutes)] - minute) % 1440 for i, minute in enumerate(minutes)) != 1440
            ):
                raise ValueError("Timepoints must remain in chronological order without duplicates")
    else:
        raise ValueError("Fixture schedule readback is required")
    return result


def _clock_minute(value: Any) -> int:
    """Validate the APK's hour/minute representation before encoding."""
    if (
        not isinstance(value, dict)
        or type(value.get("hour")) is not int
        or type(value.get("minute")) is not int
        or not 0 <= value["hour"] <= 23
        or not 0 <= value["minute"] <= 59
    ):
        raise ValueError("Enter a valid time from 00:00 to 23:59")
    return value["hour"] * 60 + value["minute"]
