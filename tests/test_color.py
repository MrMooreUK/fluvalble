"""Tests for APK-spectrum colour conversion."""

import pytest

from custom_components.fluvalble.core.color import (
    SPECTRAL_XYZ,
    channel_percentages_to_rgb,
    rgb_to_channel_percentages,
)
from custom_components.fluvalble.core.products import PRODUCTS


def test_all_apk_spectrum_profiles_have_the_expected_channel_count():
    assert {profile: len(columns) for profile, columns in SPECTRAL_XYZ.items()} == {
        "aquasky_current": 4,
        "aquasky_legacy": 4,
        "plant_current": 5,
        "plant_legacy": 5,
        "reef_current": 5,
        "reef_legacy": 5,
    }


def test_every_known_apk_product_uses_a_matching_spectrum_channel_count():
    for product in PRODUCTS.values():
        assert product.spectrum_profile in SPECTRAL_XYZ
        assert len(SPECTRAL_XYZ[product.spectrum_profile]) == product.channel_count


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


@pytest.mark.parametrize("profile", sorted(SPECTRAL_XYZ))
@pytest.mark.parametrize(
    "rgb",
    [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)],
)
def test_every_apk_profile_produces_bounded_full_brightness_channels(profile, rgb):
    channels = rgb_to_channel_percentages(profile, rgb, 255)

    assert len(channels) == len(SPECTRAL_XYZ[profile])
    assert all(0 <= value <= 100 for value in channels)
    assert max(channels) == 100


@pytest.mark.parametrize("profile", sorted(SPECTRAL_XYZ))
def test_every_apk_profile_reports_each_physical_emitter_as_valid_rgb(profile):
    for index in range(len(SPECTRAL_XYZ[profile])):
        channels = tuple(100 if position == index else 0 for position in range(len(SPECTRAL_XYZ[profile])))
        rgb = channel_percentages_to_rgb(profile, channels)

        assert len(rgb) == 3
        assert all(0 <= value <= 255 for value in rgb)
        assert max(rgb) == 255
