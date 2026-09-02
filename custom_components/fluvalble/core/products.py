"""Fluval product identities decoded from BLE advertisements.

Legacy controllers put the first two ASCII product-ID characters in the
Bluetooth manufacturer/company field and the remaining two at the start of
the manufacturer payload. This mirrors FluvalSmart's scanner instead of
treating the following firmware bytes as an ID.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FluvalProduct:
    """APK-defined identity and channel layout for a Fluval fixture."""

    model: str | None
    spectrum: str
    spectrum_profile: str
    channel_count: int
    native_effect_count: int


def _products(
    ids: dict[int, str | None],
    spectrum: str,
    spectrum_profile: str,
    channel_count: int,
    native_effect_count: int,
) -> dict[int, FluvalProduct]:
    return {
        product_id: FluvalProduct(
            model,
            spectrum,
            spectrum_profile,
            channel_count,
            native_effect_count,
        )
        for product_id, model in ids.items()
    }


# DeviceUtil's exact device-name table, extended with the current add-device
# catalogue where that newer UI supersedes an older reused product name.
PRODUCTS: dict[int, FluvalProduct] = {
    **_products(
        {
            # LightDeviceUtils.getLightTypeAndOld() falls product 281 through
            # to type 1, which ManFragment maps to the current Reef asset.
            281: None,
        },
        "marine",
        "reef_current",
        5,
        0,
    ),
    **_products(
        {
            289: "Marine & Reef 500mm",
            290: "Marine & Reef 800mm",
            291: "Marine & Reef 1100mm",
            292: "Marine & Reef 1000mm",
            293: "Marine & Reef 380mm",
            294: "Marine & Reef 750mm",
            337: "Wing Nano Marine",
            536: None,
            640: None,
        },
        "marine",
        "reef_legacy",
        5,
        0,
    ),
    **_products(
        {
            385: "A-Sky Aqua 1025mm",
            546: "Fluval Reef 4.0 LED",
            547: "Fluval Reef Nano 4.0 LED",
        },
        "marine",
        "reef_current",
        5,
        4,
    ),
    **_products(
        {
            305: "Fresh & Plant 500mm",
            306: "Fresh & Plant 800mm",
            307: "Fresh & Plant 1100mm",
            308: "Fresh & Plant 1000mm",
            309: "Fresh & Plant 380mm",
            310: "Fresh & Plant 600mm",
            311: "Fresh & Plant 900mm",
            338: "Wing Nano Fresh",
            373: "Vicenza 180",
            374: "Vicenza 260",
            375: "Venezia 190",
            376: "Venezia 350A",
            377: "Venezia 350B",
            387: "Plant Aqua 875mm",
            388: "Plant Aqua 1075mm",
            537: None,
            641: None,
            29058: None,
        },
        "plant",
        "plant_legacy",
        5,
        0,
    ),
    **_products(
        {
            # The current FluvalConnect add-device flow maps type 0182 to
            # product 0386 and labels it "Fluval Plant PRO LED". DeviceUtil's
            # older Plant Aqua size name for this reused ID is stale.
            386: "Fluval Plant PRO LED",
            545: "Fluval Plant 4.0 LED",
            548: "Fluval Plant Nano 4.0 LED",
            563: "Fluval Siena 2.0",
        },
        "plant",
        "plant_current",
        5,
        4,
    ),
    **_products(
        {
            321: "Aquasky 600mm",
            322: "Aquasky 900mm",
            323: "Aquasky 1200mm",
            324: "Aquasky 380mm",
            325: "Aquasky 530mm",
            326: "Aquasky 835mm",
            327: "Aquasky 990mm",
            328: "Aquasky 750mm",
            329: "Aquasky 1150mm",
            336: "Aquasky 910mm",
            369: "Roma90",
            370: "Roma125",
            371: "Roma200",
            372: "Roma240",
            384: "A-Sky Aqua 679mm",
            609: None,
            29057: None,
        },
        "rgbw",
        "aquasky_legacy",
        4,
        11,
    ),
    **_products(
        {
            532: "Fluval Aquasky 3.0 LED",
            564: "Fluval Roma & Shaker 2.0",
        },
        "rgbw",
        "aquasky_current",
        4,
        11,
    ),
}


def product_from_id(product_id: int | None) -> FluvalProduct | None:
    """Return the APK product definition for an ID, when present."""
    return PRODUCTS.get(product_id) if product_id is not None else None


def product_id_from_manufacturer_data(
    manufacturer_data: dict[Any, bytes | bytearray],
) -> int | None:
    """Decode an APK-known product ID from HA manufacturer data."""
    for raw_key, raw_value in manufacturer_data.items():
        try:
            company_id = int(raw_key)
            company_bytes = company_id.to_bytes(2, "little", signed=False)
            value = bytes(raw_value)
        except (OverflowError, TypeError, ValueError):
            continue

        # FluvalSmart prepends the company bytes to the payload, then parses
        # the first four ASCII hex characters as the fixture product ID.
        if len(value) >= 2:
            candidate = company_bytes + value[:2]
            if all(byte in b"0123456789abcdefABCDEF" for byte in candidate):
                product_id = int(candidate.decode("ascii"), 16)
                if product_id in PRODUCTS:
                    return product_id

        # FluvalConnect checks raw company bytes FFFF/FF01 and reads the
        # big-endian product ID at raw offsets 27/28. The manufacturer payload
        # starts immediately after those company bytes (raw offset 19).
        if company_bytes in (b"\xff\xff", b"\xff\x01") and len(value) >= 10:
            product_id = int.from_bytes(value[8:10], "big")
            if product_id in PRODUCTS:
                return product_id

    return None
