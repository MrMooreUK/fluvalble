# Channel reporting and schedule values

FluvalConnect 1.0.15 (version code 110), SHA-256
9c3cecf8edebff06ac945d7431b078813af9d4fd86ba9fba40453dc612be3415.

## APK separation

- ManFragment.java, onMqttDataEvent, around lines 1059–1175: SPP keys 3–7
  update the five Manual colour controls. The same handler separately
  processes FACEBD channel keys 110–113.
- AutoFragment.java, around lines 708–780: SPP keys 8/9 carry sunrise and
  sunset timing; keys 11/12 populate the Day/Night banks. They are not
  substituted for keys 3–7 in the Manual controls.
- LightInstructionsKxtKt.createLightTimeAutoData, around lines 385–409:
  Professional points use SPP key 13 or FACEBD keys 120–122, with a separate
  classic encoder.
- Classic 6805 mode-0 responses contain Manual channels; mode-1/mode-2
  responses contain schedules, not a corresponding live channel sample.

## Hardware capture

[Jules's public capture](https://github.com/MrMooreUK/fluvalble/issues/133#issuecomment-6895548202)
reports SPP mode 1, channel keys 3–7 as 0/100/0/0/0, Day levels as
50/50/50/50/50 and Night levels as zero, plus all eight Professional points.
These coexist in one response: they are distinct fields, not alternative
formats for a single current-output reading.

The regression test_issue_133_actual_spp_capture_preserves_auto_and_all_eight_pro_points
keeps those fields separate and round-trips the schedule banks unchanged.
The integration therefore preserves reported Manual channel controls rather
than replacing them with a schedule estimate. A report is not a physical light
measurement. This audit makes no command or channel-reporting runtime changes.

## Local Manual recall

LightKxtKt.java lines 384–410 saves and retrieves non-classic P1–P4 colour banks
through LightColorCache, whose MMKV storage is local to the app. ManFragment.java
lines 740–770 explicitly recalls a bank through createLightAllZoneData.
onHiddenChanged (around lines 400–438) only redraws the colour adapter; it does
not automatically restore a bank on returning to the Manual screen.

The HA last-Manual feature uses the same local-bank/full-channel-recall pattern,
not a new firmware command. It is an HA-specific single last-confirmed bank,
not a claim that the app has an automatic last-used restore feature. Storage is
per config entry and bound to MAC, product ID, channel count and spectrum
profile. Only successful HA channel writes with complete fresh matching Manual
readback are saved. An explicit restore selects Manual and applies all channels
with fresh readback confirmation; ordinary notifications never invoke it.

The APK does not contain the controller firmware or a distinct marker proving
that a given channel report came from the top button. No automatic physical-
button detection or firmware-reset workaround is inferred.
