"""Convert Home Assistant RGB colours using FluvalConnect spectrum data.

The matrices below are CIE XYZ integrals of the per-channel spectral power
curves bundled with FluvalConnect.  They preserve both the chromaticity and the
relative output of each physical channel; they are not hand-picked RGB colour
approximations.
"""

from __future__ import annotations

from itertools import combinations
from math import isfinite

# Each column is the XYZ integral of one APK asset channel, in the exact order
# used by LightDeviceUtils.getLightChannel().  The source mapping is selected by
# LightDeviceUtils.getLightTypeAndOld() in ManFragment.initBar():
#
# aquasky_current -> 532_new.txt
# aquasky_legacy  -> 532_old_new.txt
# plant_current   -> 540_plant.txt
# plant_legacy    -> 540_plant_old.txt
# reef_current    -> 540_reef.txt
# reef_legacy     -> 540_reef_old.txt
#
# Integration used the official CIE 1931 2-degree colour-matching functions at
# 1 nm resolution (CIE data set checksum MD5 17cca777db64b17170f06f67ce9d3ab7).
SPECTRAL_XYZ: dict[str, tuple[tuple[float, float, float], ...]] = {
    "aquasky_current": (
        (14.5725630448, 6.3977117394, 0.0104668074),
        (4.0578962452, 22.2267611072, 4.5719882134),
        (5.6006505536, 2.4837638299, 33.7614664017),
        (316.6410796045, 311.8652052385, 356.9797398030),
    ),
    "aquasky_legacy": (
        (14.4952121592, 6.3739456768, 0.0027240755),
        (4.0033321812, 22.4033468558, 5.0930792057),
        (5.8176866649, 2.3163175784, 34.6791069239),
        (339.3290280419, 368.2726006804, 380.4439928677),
    ),
    "plant_current": (
        (22.3920710574, 10.2409999495, 40.1904407109),
        (7.5923003076, 3.4514639199, 45.2223151866),
        (24.8292440366, 24.6469740840, 42.8391163250),
        (58.1555996981, 61.9973500549, 68.8180915292),
        (71.8207040683, 65.6183704781, 27.1511230517),
    ),
    "plant_legacy": (
        (22.0389051094, 10.1233670406, 39.0451709251),
        (6.9314130860, 6.0176577047, 43.0590354081),
        (25.8046339000, 25.7268397946, 44.3796639732),
        (37.4220980337, 39.0112522774, 44.7017976560),
        (77.6318767766, 71.5037597465, 30.1989268509),
    ),
    "reef_current": (
        (21.7906687386, 9.9414676113, 38.7075292164),
        (5.4942322607, 3.2727742297, 34.4387197724),
        (8.2095208752, 1.1990824139, 43.3592065119),
        (3.0753180557, 0.2259742721, 14.7089812048),
        (25.9009870538, 26.2050707095, 43.5070407982),
    ),
    "reef_legacy": (
        (21.9184044110, 10.0444275092, 38.7498718862),
        (3.6674008169, 5.5959704945, 26.0899144099),
        (8.7265542733, 1.3138488662, 46.1883541949),
        (2.4131607742, 0.1893350214, 11.5215579244),
        (26.6416974623, 27.1054049962, 42.6408272959),
    ),
}

_SRGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
_XYZ_TO_SRGB = (
    (3.2404542, -1.5371385, -0.4985314),
    (-0.9692660, 1.8760108, 0.0415560),
    (0.0556434, -0.2040259, 1.0572252),
)
_EPSILON = 1e-10


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _mat_vec(
    matrix: tuple[tuple[float, ...], ...],
    vector: tuple[float, ...],
) -> tuple[float, ...]:
    return tuple(_dot(row, vector) for row in matrix)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Solve a small square system with partial-pivot Gaussian elimination."""
    size = len(vector)
    augmented = [matrix[row][:] + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= _EPSILON:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                current - factor * source for current, source in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[row][-1] for row in range(size)]


def _least_squares(
    columns: tuple[tuple[float, float, float], ...],
    target: tuple[float, float, float],
) -> tuple[float, ...] | None:
    gram = [[_dot(left, right) for right in columns] for left in columns]
    rhs = [_dot(column, target) for column in columns]
    solution = _solve(gram, rhs)
    if solution is None or any(value < -_EPSILON or not isfinite(value) for value in solution):
        return None
    return tuple(max(0.0, value) for value in solution)


def _nonnegative_xyz_fit(
    columns: tuple[tuple[float, float, float], ...],
    target: tuple[float, float, float],
) -> tuple[float, ...]:
    """Find the closest non-negative channel mix to a target XYZ colour."""
    best: tuple[float, float, tuple[float, ...]] | None = None
    # A point in three-dimensional XYZ needs at most three active emitters.
    for count in range(1, min(3, len(columns)) + 1):
        for indexes in combinations(range(len(columns)), count):
            active = tuple(columns[index] for index in indexes)
            solution = _least_squares(active, target)
            if solution is None:
                continue
            levels = [0.0] * len(columns)
            for index, value in zip(indexes, solution, strict=True):
                levels[index] = value
            predicted = tuple(
                sum(column[axis] * level for column, level in zip(columns, levels, strict=True)) for axis in range(3)
            )
            error = sum((actual - wanted) ** 2 for actual, wanted in zip(predicted, target, strict=True))
            drive = sum(level**2 for level in levels)
            candidate = (error, drive, tuple(levels))
            if best is None or error < best[0] - 1e-12 or (abs(error - best[0]) <= 1e-12 and drive < best[1]):
                best = candidate
    return best[2] if best is not None else (0.0,) * len(columns)


def _srgb_to_linear(component: int) -> float:
    value = max(0, min(255, int(component))) / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(component: float) -> int:
    value = max(0.0, min(1.0, component))
    encoded = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return max(0, min(255, round(encoded * 255)))


def rgb_to_channel_percentages(
    profile: str,
    rgb: tuple[int, int, int],
    brightness: int,
    *,
    channel_count: int | None = None,
) -> tuple[int, ...]:
    """Fit an sRGB colour to one APK spectrum profile."""
    columns = SPECTRAL_XYZ[profile]
    if channel_count is not None:
        columns = columns[:channel_count]
    linear_rgb = tuple(_srgb_to_linear(component) for component in rgb)
    target = _mat_vec(_SRGB_TO_XYZ, linear_rgb)
    levels = _nonnegative_xyz_fit(columns, target)
    peak = max(levels, default=0.0)
    if peak <= _EPSILON:
        return (0,) * len(columns)
    scale = max(0, min(255, int(brightness))) / 255
    return tuple(max(0, min(100, round(level / peak * scale * 100))) for level in levels)


def channel_percentages_to_rgb(
    profile: str,
    percentages: tuple[int, ...],
) -> tuple[int, int, int]:
    """Report physical Fluval channels as their APK-spectrum sRGB colour."""
    columns = SPECTRAL_XYZ[profile][: len(percentages)]
    xyz = tuple(
        sum(column[axis] * max(0, min(100, level)) / 100 for column, level in zip(columns, percentages, strict=True))
        for axis in range(3)
    )
    linear_rgb = _mat_vec(_XYZ_TO_SRGB, xyz)
    peak = max(linear_rgb, default=0.0)
    if peak <= _EPSILON:
        return (0, 0, 0)
    return tuple(_linear_to_srgb(component / peak) for component in linear_rgb)  # type: ignore[return-value]
