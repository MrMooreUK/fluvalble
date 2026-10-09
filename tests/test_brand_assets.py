"""Brand images must meet the Home Assistant brands image specification."""

import struct
from pathlib import Path

import pytest

BRAND = Path(__file__).resolve().parent.parent / "custom_components" / "fluvalble" / "brand"
ALLOWED = {
    "icon.png",
    "icon@2x.png",
    "dark_icon.png",
    "dark_icon@2x.png",
    "logo.png",
    "logo@2x.png",
    "dark_logo.png",
    "dark_logo@2x.png",
}


def _png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", header[16:24])


def test_brand_folder_only_contains_known_images():
    assert {p.name for p in BRAND.iterdir()} <= ALLOWED
    assert {"icon.png", "logo.png"} <= {p.name for p in BRAND.iterdir()}


@pytest.mark.parametrize("name", sorted(n for n in ALLOWED if "icon" in n))
def test_icons_are_square_at_spec_size(name):
    path = BRAND / name
    if not path.exists():
        pytest.skip(f"{name} not shipped")
    expected = 512 if "@2x" in name else 256
    assert _png_size(path) == (expected, expected)


@pytest.mark.parametrize("name", sorted(n for n in ALLOWED if "logo" in n))
def test_logos_have_spec_shortest_side(name):
    path = BRAND / name
    if not path.exists():
        pytest.skip(f"{name} not shipped")
    low, high = (256, 512) if "@2x" in name else (128, 256)
    assert low <= min(_png_size(path)) <= high
