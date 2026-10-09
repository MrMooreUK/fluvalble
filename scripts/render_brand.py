"""Render the Home Assistant brand images from the SVG sources.

Writes ``custom_components/fluvalble/brand/`` to the Home Assistant brands
specification (https://github.com/home-assistant/brands#image-specification):

- ``icon.png`` 256x256 and ``icon@2x.png`` 512x512 (square).
- ``logo.png`` / ``dark_logo.png`` with a 256 px shortest side, and the
  ``@2x`` variants at 512 px, trimmed to their visible content.

The icon is a self-contained card that reads on light and dark themes, so no
``dark_icon`` variant is shipped; Home Assistant falls back to ``icon.png``.

Usage (from the repository root):

    python3 -m pip install cairosvg pillow
    python3 scripts/render_brand.py
"""

from __future__ import annotations

import io
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "custom_components" / "fluvalble" / "brand"
ICON_SVG = ROOT / "custom_components" / "fluvalble" / "icon.svg"
LOGO_SVG = ROOT / "images" / "brand-logo.svg"
DARK_LOGO_SVG = ROOT / "images" / "brand-logo-dark.svg"

ICON_SIZES = {"icon.png": 256, "icon@2x.png": 512}
LOGO_HEIGHTS = {"": 256, "@2x": 512}
# Render oversized, then downsample, so trimmed edges stay crisp.
SUPERSAMPLE = 4


def _render(svg: Path, *, width: int | None = None, height: int | None = None) -> Image.Image:
    png = cairosvg.svg2png(url=str(svg), output_width=width, output_height=height)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _trim(image: Image.Image) -> Image.Image:
    """Crop transparent padding so the image has minimal empty edges."""
    bbox = image.getchannel("A").getbbox()
    return image.crop(bbox) if bbox else image


def _save(image: Image.Image, path: Path) -> None:
    image.save(path, format="PNG", optimize=True)
    print(f"wrote {path.relative_to(ROOT)} ({image.width}x{image.height})")


def render_icons() -> None:
    master = _trim(_render(ICON_SVG, width=512 * SUPERSAMPLE, height=512 * SUPERSAMPLE))
    for name, size in ICON_SIZES.items():
        _save(master.resize((size, size), Image.LANCZOS), BRAND / name)
    # README / marketing copy of the square icon.
    _save(master.resize((512, 512), Image.LANCZOS), ROOT / "images" / "icon.png")


def render_logos() -> None:
    for prefix, svg in (("", LOGO_SVG), ("dark_", DARK_LOGO_SVG)):
        master = _trim(_render(svg, height=512 * SUPERSAMPLE))
        for suffix, height in LOGO_HEIGHTS.items():
            width = round(master.width * height / master.height)
            _save(master.resize((width, height), Image.LANCZOS), BRAND / f"{prefix}logo{suffix}.png")


if __name__ == "__main__":
    BRAND.mkdir(parents=True, exist_ok=True)
    render_icons()
    render_logos()
