"""Tests for APK-spectrum colour conversion."""

import pytest

from custom_components.fluvalble.core.color import (
    SPECTRAL_XYZ,
    channel_percentages_to_rgb,
    rgb_to_channel_percentages,
)


def test_all_apk_spectrum_profiles_have_the_expected_channel_count():
    assert {profile: len(columns) for profile, columns in SPECTRAL_XYZ.items()} == {
        "aquasky_current": 4,
        "aquasky_legacy": 4,
        "plant_current": 5,
        "plant_legacy": 5,
        "reef_current": 5,
        "reef_legacy": 5,
    }


def test_product_328_profile_fits_mauve_without_white():
    assert rgb_to_channel_percentages(
        "aquasky_legacy",
        (215, 150, 255),
        255,
        channel_count=3,
    ) == (94, 34, 100)
    assert channel_percentages_to_rgb("aquasky_legacy", (94, 34, 100)) == (
        215,
        151,
        255,
    )


def test_aquasky_calibration_accounts_for_measured_primary_chromaticity():
    assert rgb_to_channel_percentages(
        "aquasky_legacy",
        (255, 0, 0),
        255,
        channel_count=3,
    ) == (100, 5, 1)
    assert rgb_to_channel_percentages(
        "aquasky_legacy",
        (0, 255, 0),
        255,
        channel_count=3,
    ) == (65, 100, 0)
    assert rgb_to_channel_percentages(
        "aquasky_legacy",
        (0, 0, 255),
        255,
        channel_count=3,
    ) == (5, 0, 100)


@pytest.mark.parametrize(
    "rgb",
    [
        (255, 0, 0),
        (255, 128, 0),
        (255, 255, 0),
        (128, 255, 0),
        (0, 255, 0),
        (0, 255, 128),
        (0, 255, 255),
        (0, 128, 255),
        (0, 0, 255),
        (128, 0, 255),
        (255, 0, 255),
        (255, 0, 128),
    ],
)
def test_product_328_saturated_hue_wheel_round_trips(rgb):
    channels = rgb_to_channel_percentages(
        "aquasky_legacy",
        rgb,
        255,
        channel_count=3,
    )
    reported = channel_percentages_to_rgb("aquasky_legacy", channels)

    assert max(abs(actual - expected) for actual, expected in zip(reported, rgb, strict=True)) <= 38


def test_colour_fit_scales_only_with_home_assistant_brightness():
    full = rgb_to_channel_percentages(
        "aquasky_legacy",
        (215, 150, 255),
        255,
        channel_count=3,
    )
    half = rgb_to_channel_percentages(
        "aquasky_legacy",
        (215, 150, 255),
        128,
        channel_count=3,
    )
    assert full == (94, 34, 100)
    assert half == (47, 17, 50)


def test_black_has_no_channel_output():
    assert rgb_to_channel_percentages(
        "aquasky_legacy",
        (0, 0, 0),
        255,
        channel_count=3,
    ) == (0, 0, 0)
