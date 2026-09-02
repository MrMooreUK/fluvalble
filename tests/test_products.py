"""Tests for APK-backed Fluval product identity parsing."""

import pytest

from custom_components.fluvalble.core.products import (
    PRODUCTS,
    product_from_id,
    product_id_from_manufacturer_data,
)


@pytest.mark.parametrize(
    ("manufacturer_data", "expected"),
    [
        ({12592: b"480103"}, 328),  # ASCII 0148 + firmware 0103
        ({"12592": bytearray(b"310203")}, 305),  # ASCII 0131
        ({65535: b"\x00" * 8 + b"\x02\x14"}, 532),
        ({511: b"\x00" * 8 + b"\x02\x21"}, 545),
    ],
)
def test_product_id_from_apk_advertisement_layout(manufacturer_data, expected):
    assert product_id_from_manufacturer_data(manufacturer_data) == expected


@pytest.mark.parametrize(
    "manufacturer_data",
    [
        {},
        {12592: b"01"},  # Reconstructs unknown 0x0101.
        {12592: b"\xff\xff0103"},
        {65535: b"\x00" * 9},
        {"not-an-id": b"480103"},
    ],
)
def test_product_id_rejects_malformed_or_unknown_data(manufacturer_data):
    assert product_id_from_manufacturer_data(manufacturer_data) is None


def test_apk_product_catalog_defines_fixture_model_and_channels():
    aquasky = product_from_id(328)
    plant = product_from_id(305)

    assert aquasky is not None
    assert aquasky.model == "Aquasky 750mm"
    assert aquasky.spectrum == "rgbw"
    assert aquasky.channel_count == 4
    assert plant is not None
    assert plant.model == "Fresh & Plant 500mm"
    assert plant.spectrum == "plant"
    assert plant.channel_count == 5


def test_apk_product_catalog_defines_native_effect_counts():
    assert product_from_id(305).native_effect_count == 0
    assert product_from_id(328).native_effect_count == 11
    assert product_from_id(532).native_effect_count == 11
    assert product_from_id(545).native_effect_count == 4
    assert product_from_id(546).native_effect_count == 4
    assert product_from_id(547).native_effect_count == 4
    assert product_from_id(548).native_effect_count == 4
    assert product_from_id(563).native_effect_count == 4
    assert product_from_id(564).native_effect_count == 11


def test_catalog_matches_apk_native_effect_groups():
    four_effect = {385, 386, 545, 546, 547, 548, 563}
    eleven_effect = {
        321,
        322,
        323,
        324,
        325,
        326,
        327,
        328,
        329,
        336,
        369,
        370,
        371,
        372,
        384,
        532,
        564,
        609,
        29057,
    }

    assert {product_id for product_id, product in PRODUCTS.items() if product.native_effect_count == 4} == four_effect
    assert {
        product_id for product_id, product in PRODUCTS.items() if product.native_effect_count == 11
    } == eleven_effect
    assert {product_id for product_id, product in PRODUCTS.items() if product.native_effect_count == 0} == set(
        PRODUCTS
    ) - four_effect - eleven_effect


def test_catalog_matches_apk_channel_groups_and_excludes_firmware_0103():
    four_channel = {
        321,
        322,
        323,
        324,
        325,
        326,
        327,
        328,
        329,
        336,
        369,
        370,
        371,
        372,
        384,
        532,
        564,
        609,
        29057,
    }
    five_channel = {
        281,
        289,
        290,
        291,
        292,
        293,
        294,
        305,
        306,
        307,
        308,
        309,
        310,
        311,
        337,
        338,
        373,
        374,
        375,
        376,
        377,
        385,
        386,
        387,
        388,
        536,
        537,
        545,
        546,
        547,
        548,
        563,
        640,
        641,
        29058,
    }

    assert {product_id for product_id, product in PRODUCTS.items() if product.channel_count == 4} == four_channel
    assert {product_id for product_id, product in PRODUCTS.items() if product.channel_count == 5} == five_channel
    assert set(PRODUCTS) == four_channel | five_channel
    assert 259 not in PRODUCTS


@pytest.mark.parametrize("product_id", PRODUCTS)
def test_every_apk_product_id_decodes_from_classic_advertisement(product_id):
    encoded = f"{product_id:04X}".encode("ascii")
    company_id = int.from_bytes(encoded[:2], "little")

    assert product_id_from_manufacturer_data({company_id: encoded[2:] + b"0103"}) == product_id


@pytest.mark.parametrize("product_id", PRODUCTS)
def test_every_apk_product_id_decodes_from_binary_advertisement(product_id):
    payload = b"\x00" * 8 + product_id.to_bytes(2, "big")

    assert product_id_from_manufacturer_data({65535: payload}) == product_id


def test_newer_product_names_match_apk_add_device_catalog():
    assert product_from_id(532).model == "Fluval Aquasky 3.0 LED"
    assert product_from_id(545).model == "Fluval Plant 4.0 LED"
    assert product_from_id(546).model == "Fluval Reef 4.0 LED"
    assert product_from_id(547).model == "Fluval Reef Nano 4.0 LED"
    assert product_from_id(548).model == "Fluval Plant Nano 4.0 LED"
    assert product_from_id(563).model == "Fluval Siena 2.0"
    assert product_from_id(564).model == "Fluval Roma & Shaker 2.0"
