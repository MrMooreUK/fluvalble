# Fluval BLE branding

Fluval BLE uses a dark, premium aquarium-lighting identity: deep navy surfaces, cyan light beams, subtle violet accents, and clean technical typography.

## Assets

- `images/logo.svg` — source banner artwork for README and marketing surfaces.
- `images/logo.png` — rendered README banner, 1120 × 360.
- `images/icon.png` — rendered square icon, 512 × 512.
- `custom_components/fluvalble/icon.svg` — Home Assistant integration SVG icon source.
- `custom_components/fluvalble/brand/logo.png` — bundled integration logo.
- `custom_components/fluvalble/brand/icon.png` — bundled integration icon.

## Visual language

- **Background:** near-black navy gradients (`#05070b`, `#081522`, `#031b2c`).
- **Primary glow:** reef cyan / aqua (`#54f7ff`, `#00c8ff`, `#54ffcf`).
- **Accent:** restrained violet (`#5e6ad2`, `#7c6dff`).
- **Mood:** premium, local-first, aquarium ambience, Home Assistant friendly.

## Regenerating PNGs

If the SVG artwork changes, regenerate the PNG assets with:

```bash
python3 -m pip install pillow cairosvg
python3 - <<'PY'
import cairosvg, shutil
cairosvg.svg2png(url='images/logo.svg', write_to='images/logo.png', output_width=1120, output_height=360)
cairosvg.svg2png(url='custom_components/fluvalble/icon.svg', write_to='images/icon.png', output_width=512, output_height=512)
shutil.copyfile('images/logo.png', 'custom_components/fluvalble/brand/logo.png')
shutil.copyfile('images/icon.png', 'custom_components/fluvalble/brand/icon.png')
PY
```
