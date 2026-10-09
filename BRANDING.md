# Fluval BLE branding

Fluval BLE uses a dark, premium aquarium-lighting identity: deep navy surfaces, cyan light beams, subtle violet accents, and clean technical typography.

## Assets

- `images/logo.svg` — source banner artwork for README and marketing surfaces.
- `images/logo.png` — rendered README banner, 1120 × 360.
- `images/icon.png` — rendered square icon, 512 × 512.
- `images/brand-logo.svg` / `images/brand-logo-dark.svg` — icon + wordmark
  lockup for light and dark backgrounds. The wordmark is Inter ExtraBold
  converted to outlines, so rendering needs no installed fonts.
- `custom_components/fluvalble/icon.svg` — Home Assistant integration SVG icon source.
- `custom_components/fluvalble/brand/` — integration brand images shipped to
  Home Assistant (2026.3+ reads them locally):

  | File | Size |
  |---|---|
  | `icon.png` / `icon@2x.png` | 256 × 256 / 512 × 512 |
  | `logo.png` / `logo@2x.png` | 256 / 512 px tall, trimmed |
  | `dark_logo.png` / `dark_logo@2x.png` | 256 / 512 px tall, trimmed |

  The icon is a self-contained card that works on both themes, so there is
  no `dark_icon`; Home Assistant falls back to `icon.png`.
  `tests/test_brand_assets.py` enforces the
  [brands image specification](https://github.com/home-assistant/brands#image-specification).

## HACS store icon

Home Assistant shows the bundled `brand/` images on its Integrations page.
The HACS store currently loads icons only from its own data service and does
not yet fall back to local brand images
([hacs/integration#5171](https://github.com/hacs/integration/issues/5171)),
so the HACS listing may show a blank icon until HACS ships that fallback. The
`home-assistant/brands` repository no longer accepts custom integrations, so
the bundled `brand/` folder is the only supported source.

## Visual language

- **Background:** near-black navy gradients (`#05070b`, `#081522`, `#031b2c`).
- **Primary glow:** reef cyan / aqua (`#54f7ff`, `#00c8ff`, `#54ffcf`).
- **Accent:** restrained violet (`#5e6ad2`, `#7c6dff`).
- **Mood:** premium, local-first, aquarium ambience, Home Assistant friendly.

## Regenerating PNGs

If `icon.svg` or the brand logo SVGs change, regenerate the icon and brand
images with:

```bash
python3 -m pip install pillow cairosvg
python3 scripts/render_brand.py
```

The README banner (`images/logo.png`) uses live Inter text, so render it on a
machine with Inter installed:

```bash
python3 -c "import cairosvg; cairosvg.svg2png(url='images/logo.svg', write_to='images/logo.png', output_width=1120, output_height=360)"
```
