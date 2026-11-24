# Channel reporting and schedule values

Derived from FluvalConnect 1.0.15 for interoperability.

## App field separation

- The app's Manual screen state handler: SPP keys 3–7 update the five Manual
  colour controls. The same handler separately
  processes FACEBD channel keys 110–113.
- The app's Auto screen: SPP keys 8/9 carry sunrise and
  sunset timing; keys 11/12 populate the Day/Night banks. They are not
  substituted for keys 3–7 in the Manual controls.
- The app's schedule data builder: Professional points use SPP key 13 or FACEBD keys 120–122, with a separate
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
measurement. That channel-reporting review did not change native command formats.

## Local Manual recall

The app saves and retrieves non-classic P1–P4 colour banks in storage local to
the app. Its Manual screen explicitly recalls a bank through the all-zone
channel command. Returning to the Manual screen only redraws the colour
controls; it does not automatically restore a bank.

The HA last-Manual feature uses the same local-bank/full-channel-recall pattern,
not a new firmware command. It is an HA-specific single last-confirmed bank,
not a claim that the app has an automatic last-used restore feature. Storage is
per config entry and bound to MAC, product ID, channel count and spectrum
profile. Only successful HA channel writes with complete fresh matching Manual
readback are saved. An explicit restore reads the current mode, requires Manual
without selecting it, and applies all channels with fresh readback confirmation;
ordinary notifications never invoke it.

The APK does not contain the controller firmware or a distinct marker proving
that a given channel report came from the top button. No automatic physical-
button detection or firmware-reset workaround is inferred.
