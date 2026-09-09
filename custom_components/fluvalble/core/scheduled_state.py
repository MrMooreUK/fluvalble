"""Read-only classic schedule projection; never sends fixture commands."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any


def weather_may_be_active(windows: Sequence[dict[str, Any]], moment: datetime) -> bool:
    """Limit static-output uncertainty to enabled timed-weather windows.

    Weekday flags are Monday first, as in the integration's APK packet
    encoder. For a midnight-spanning interval, the early-hours portion
    belongs to the day on which the interval started.
    """
    minute = moment.hour * 60 + moment.minute
    for window in windows:
        if not window.get("enabled"):
            continue
        try:
            start_h, start_m = map(int, window["start"].split(":"))
            end_h, end_m = map(int, window["end"].split(":"))
            days = window["weekdays"]
            if not (0 <= start_h < 24 and 0 <= end_h < 24 and 0 <= start_m < 60 and 0 <= end_m < 60):
                return True
            if len(days) != 7 or any(not isinstance(day, bool) for day in days):
                return True
        except (KeyError, TypeError, ValueError, AttributeError):
            return True
        start, end = start_h * 60 + start_m, end_h * 60 + end_m
        weekday = moment.weekday()
        if start < end:
            active = start <= minute < end
        elif start > end:
            active = minute >= start or minute < end
            if minute < end:
                weekday = (weekday - 1) % 7
        else:
            # Equal endpoints have no established zero-duration semantics.
            # Conservatively withhold static projection on enabled days.
            active = True
        if active and days[weekday]:
            return True
    return False


def interpolate_levels(points: Sequence[tuple[int, tuple[int, ...]]], minute: int) -> tuple[int, ...] | None:
    """Project APK preview points in tenths of a percent, across midnight.

    FluvalConnect AutoFragment.getBright and ProFragment.getBrights use
    integer arithmetic at 0..1000. Stable ordering preserves Auto's two
    sleep-time points: night before the boundary, zero after it.
    """
    if len(points) < 2 or not 0 <= minute < 1440:
        return None
    ordered = sorted(points, key=lambda point: point[0])
    count = len(ordered[0][1])
    if count not in (4, 5) or any(
        not 0 <= time < 1440 or len(levels) != count or any(not 0 <= level <= 100 for level in levels)
        for time, levels in ordered
    ):
        return None
    if len({time for time, _ in ordered}) < 2:
        return None
    previous, following = ordered[-1], ordered[0]
    for index, point in enumerate(ordered):
        if point[0] <= minute:
            previous, following = point, ordered[(index + 1) % len(ordered)]
    duration = (following[0] - previous[0]) % 1440
    elapsed = (minute - previous[0]) % 1440
    if not duration:
        return None
    # Python // floors negative values; Java/Kotlin integer division instead
    # truncates toward zero. Preserve descending ramps without a float.
    result = []
    for start, end in zip(previous[1], following[1], strict=True):
        numerator = (end - start) * 10 * elapsed
        delta = abs(numerator) // duration
        result.append(start * 10 + (delta if numerator >= 0 else -delta))
    return tuple(result)
