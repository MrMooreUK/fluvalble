# Lovelace dashboard cards

This integration includes optional Lovelace cards for previewing and editing an
AquaSky 3.0 schedule from a Home Assistant dashboard.

> Preview notice: these cards and schedule tools have only been tested with
> AquaSky 3.0. They are not suitable or validated for aquarium use until
> reviewed, validated, and published from the main branch. Use with caution and
> back up existing Home Assistant setups before testing. For issues with other
> Fluval lights, please open a GitHub issue with the light model, Home Assistant
> version, diagnostics output, and relevant logs.

## Add the card resource

After installing the integration and restarting Home Assistant, add the card
module as a dashboard resource:

1. Open **Settings** > **Dashboards**.
2. Open the dashboard menu and select **Resources**.
3. Add a new JavaScript module resource:

   ```yaml
   url: /fluvalble/fluvalble-schedule-card.js
   type: module
   ```

4. Refresh the browser after saving the resource. If Home Assistant still shows
   `Custom element doesn't exist`, clear the browser cache or reload the page
   with cache bypass.

## Add the cards

The same JavaScript resource registers three custom cards:

- `custom:fluvalble-schedule-card` shows the 24-hour channel schedule, schedule
  mode and data source, physical preview controls, and the selected time slider.
- `custom:fluvalble-spectrum-card` shows editable channel bars for the selected
  schedule time.
- `custom:fluvalble-wavelength-card` shows a wavelength-style preview based on
  the selected schedule time and channel levels.

Add the cards to a dashboard using YAML mode or a manual card:

```yaml
type: vertical-stack
cards:
  - type: custom:fluvalble-schedule-card
    title: AquaSky 24 Hour Schedule
    physical_preview: false
    preview_duration: 60
    step_seconds: 2
    points:
      - time: "00:00"
        red: 0
        green: 0
        blue: 0
        white: 0
      - time: "10:00"
        red: 0
        green: 0
        blue: 0
        white: 0
      - time: "11:00"
        red: 10
        green: 10
        blue: 25
        white: 5
      - time: "16:00"
        red: 10
        green: 10
        blue: 25
        white: 5
      - time: "19:00"
        red: 3
        green: 0
        blue: 8
        white: 0
      - time: "20:00"
        red: 0
        green: 0
        blue: 0
        white: 0

  - type: custom:fluvalble-spectrum-card
    title: AquaSky Spectrum Bars
    points:
      - time: "00:00"
        red: 0
        green: 0
        blue: 0
        white: 0
      - time: "10:00"
        red: 0
        green: 0
        blue: 0
        white: 0
      - time: "11:00"
        red: 10
        green: 10
        blue: 25
        white: 5
      - time: "16:00"
        red: 10
        green: 10
        blue: 25
        white: 5
      - time: "19:00"
        red: 3
        green: 0
        blue: 8
        white: 0
      - time: "20:00"
        red: 0
        green: 0
        blue: 0
        white: 0

  - type: custom:fluvalble-wavelength-card
    title: AquaSky Wavelength Preview
    points:
      - time: "00:00"
        red: 0
        green: 0
        blue: 0
        white: 0
      - time: "10:00"
        red: 0
        green: 0
        blue: 0
        white: 0
      - time: "11:00"
        red: 10
        green: 10
        blue: 25
        white: 5
      - time: "16:00"
        red: 10
        green: 10
        blue: 25
        white: 5
      - time: "19:00"
        red: 3
        green: 0
        blue: 8
        white: 0
      - time: "20:00"
        red: 0
        green: 0
        blue: 0
        white: 0
```

The complete dashboard example is available in
[`docs/lovelace-fluvalble-card.yaml`](lovelace-fluvalble-card.yaml).

## Using the cards

The schedule card is the source of truth for the selected time. Moving its time
slider updates the spectrum and wavelength cards. When **Physical preview** is
enabled, applying or previewing a schedule also sends the selected levels to the
light.

Use **Apply Schedule** to save the current schedule. **Fixture native** uploads
4-10 points for classic/OLD controllers or 4-12 points for FACEBD/MESH
controllers once as the light's Professional schedule, then the controller
follows its own clock. Manual saves the curve without activating it.

Use **Load from fixture** to request fresh controller state and explicitly import
its reported Professional curve into the editor. Loading does not save, activate,
or overwrite the Home Assistant copy until **Apply Schedule** is selected. If the
fixture reports an Auto sunrise/sunset schedule instead, the card leaves the
current curve untouched because Auto data cannot be losslessly represented as a
Professional curve. The subtitle identifies a Home Assistant copy, an uploaded
curve awaiting readback, or confirmed fixture readback.

Use **Play 24h preview** to loop through the schedule visually. Physical preview
writes are throttled to 30-minute schedule intervals to avoid unnecessary BLE
traffic. Use **Stop preview** to stop playback. Fixture-native mode is
reactivated after a physical preview; Manual mode restores the prior static
levels.

