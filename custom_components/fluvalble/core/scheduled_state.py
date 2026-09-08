"""Read-only classic schedule projection; never sends fixture commands."""

from collections.abc import Sequence


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
