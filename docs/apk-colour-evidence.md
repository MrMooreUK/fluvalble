# APK colour-control evidence

This integration treats FluvalConnect as the authority for fixture identity,
physical channel order, spectrum selection, and BLE commands. Home Assistant's
RGB picker is an additional presentation layer; FluvalConnect itself presents
the physical channels as independent percentage controls.

## Product 328

The decompiled `LightDeviceUtils` identifies product 328 as
`LIGHT_ID_AQUASKY_750`. Its relevant methods establish all of the following:

- `isOldLight(328)` is true.
- `getLightType(328)` returns type 3.
- Type 3 has four channels in the order Red, Green, Blue, White.
- `getLightTypeAndOld(328)` returns type 6.
- `ManFragment.initBar()` maps type 6 to the bundled spectrum asset
  `532_old_new.txt`.

`ManFragment` sends manual changes as channel percentages. For a classic
fixture, the protocol path encodes those values in the `6804` all-zone command;
there is no RGB-to-RGBW function in the app.

## Spectrum profiles

The decompiled `ManFragment.initBar()` switch selects these exact assets:

| Integration profile | APK light type | FluvalConnect asset | APK channel order |
|---|---:|---|---|
| `reef_current` | 1 | `540_reef.txt` | Pink, Cyan, Blue, Purple, Cold White |
| `plant_current` | 2 | `540_plant.txt` | Pink, Blue, Cold White, White, Warm White |
| `aquasky_current` | 3 | `532_new.txt` | Red, Green, Blue, White |
| `reef_legacy` | 4 | `540_reef_old.txt` | Pink, Cyan, Blue, Purple, Cold White |
| `plant_legacy` | 5 | `540_plant_old.txt` | Pink, Blue, Cold White, White, Warm White |
| `aquasky_legacy` | 6 | `532_old_new.txt` | Red, Green, Blue, White |

The product-to-profile table in `core/products.py` mirrors
`LightDeviceUtils.getLightTypeAndOld()`.

## Home Assistant translation

Each FluvalConnect asset contains a measured spectral power value for every
physical channel at each wavelength from 320 to 800 nm. `core/color.py`
integrates those curves against the official CIE 1931 2-degree standard
observer functions to obtain one XYZ vector per channel. Its checked CIE data
set has MD5 `17cca777db64b17170f06f67ce9d3ab7`.

For an RGB request, the integration:

1. linearizes the requested sRGB colour and converts it to CIE XYZ;
2. finds the closest non-negative mix of the product's measured channel XYZ
   vectors;
3. normalizes that mix to the requested Home Assistant brightness; and
4. sends those physical percentages with the APK-defined protocol command.

AquaSky RGB requests fit only its Red, Green, and Blue curves and explicitly
set White to zero. Home Assistant exposes the dedicated White emitter as a
separate White mode. This prevents the framework's generic RGBW extraction
from adding uncalibrated white to chromatic colours.

The inverse display path sums the same measured channel XYZ vectors and
converts the result back to sRGB. A recently commanded RGB value is retained
for the short interval in which a classic controller can report one stale
pre-command status packet; it is discarded when later channel state differs.

The APK does not provide an arbitrary RGB-picker conversion to copy: its
manual screen exposes one percentage slider per physical emitter. The colour
picker is therefore a Home Assistant adapter built on the APK's measured
spectra, channel order, and packet format. For example, sRGB `(215, 150, 255)`
is intentionally a pale mauve with about 41% HSV saturation; the dedicated
White emitter still remains at zero. Fully saturated sRGB magenta maps to the
APK-defined AquaSky emitters as Red 100%, Green 5%, Blue 94%, White 0% and was
verified on product 328 as visibly purple.

## Primary references

- FluvalConnect decompilation: `LightDeviceUtils.java`, `ManFragment.java`,
  `SpectrumUtil.java`, and the six spectrum assets listed above.
- CIE 1931 2-degree colour-matching functions, data set DOI
  `10.25039/CIE.DS.xvudnb9b` (CIE 018:2019, Table 6).
