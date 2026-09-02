# Lovelace dashboard cards

This integration includes optional Lovelace cards for previewing and editing
Fluval channel schedules and fixture-native timed effects from a Home Assistant
dashboard.

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

The same JavaScript resource registers four custom cards:

- `custom:fluvalble-schedule-card` shows the 24-hour channel schedule, schedule
  mode and data source, physical preview controls, and the selected time slider.
- `custom:fluvalble-spectrum-card` shows editable channel bars for the selected
  schedule time.
- `custom:fluvalble-wavelength-card` shows the selected schedule levels against
  the exact current or legacy AquaSky, Plant, or Reef spectrum data bundled in
  FluvalConnect.
- `custom:fluvalble-effect-schedule-card` edits up to seven timed native-effect
  windows stored and executed by a supported Fluval controller.

Add the cards to a dashboard using YAML mode or a manual card:

```yaml
type: vertical-stack
cards:
  - type: custom:fluvalble-effect-schedule-card
    title: Fluval Timed Effects

  - type: custom:fluvalble-schedule-card
    title: AquaSky 24 Hour Schedule
    physical_preview: false
    preview_duration: 60
    step_seconds: 2
    points:
      - time: "00:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0
      - time: "10:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0
      - time: "11:00"
        channel_1: 10
        channel_2: 10
        channel_3: 25
        channel_4: 5
      - time: "16:00"
        channel_1: 10
        channel_2: 10
        channel_3: 25
        channel_4: 5
      - time: "19:00"
        channel_1: 3
        channel_2: 0
        channel_3: 8
        channel_4: 0
      - time: "20:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0

  - type: custom:fluvalble-spectrum-card
    title: AquaSky Spectrum Bars
    points:
      - time: "00:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0
      - time: "10:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0
      - time: "11:00"
        channel_1: 10
        channel_2: 10
        channel_3: 25
        channel_4: 5
      - time: "16:00"
        channel_1: 10
        channel_2: 10
        channel_3: 25
        channel_4: 5
      - time: "19:00"
        channel_1: 3
        channel_2: 0
        channel_3: 8
        channel_4: 0
      - time: "20:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0

  - type: custom:fluvalble-wavelength-card
    title: AquaSky Wavelength Preview
    points:
      - time: "00:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0
      - time: "10:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0
      - time: "11:00"
        channel_1: 10
        channel_2: 10
        channel_3: 25
        channel_4: 5
      - time: "16:00"
        channel_1: 10
        channel_2: 10
        channel_3: 25
        channel_4: 5
      - time: "19:00"
        channel_1: 3
        channel_2: 0
        channel_3: 8
        channel_4: 0
      - time: "20:00"
        channel_1: 0
        channel_2: 0
        channel_3: 0
        channel_4: 0
```

The complete dashboard example is available in
[`docs/lovelace-fluvalble-card.yaml`](lovelace-fluvalble-card.yaml).

When more than one Fluval light is configured, set `entry_id` or `mac` on each
card so its editor and actions target the intended fixture. With one configured
light, the integration resolves that single entry automatically.

The wavelength card loads the fixture profile itself, so it also works outside
the example vertical stack. Product-ID detection selects the matching APK asset.
For a manually configured fixture whose product ID cannot be read, an explicit
card override may be set to `aquasky_current`, `aquasky_legacy`,
`plant_current`, `plant_legacy`, `reef_current`, or `reef_legacy`:

```yaml
type: custom:fluvalble-wavelength-card
entry_id: your_config_entry_id
spectrum_profile: plant_current
```

Without a positively identified product or explicit override, the card reports
that wavelength data is unavailable instead of displaying another fixture's
spectrum.

## Using the cards

The schedule card provides separate **Professional** and **Auto** editors.
Professional remains the source of truth for the selected preview time: moving
its time slider updates the spectrum and wavelength cards. When **Physical
preview** is enabled, applying or previewing a Professional schedule also sends
the selected levels to the light.

Use **Apply Schedule** to save the current schedule. **Fixture native** uploads
4-10 points for classic/OLD controllers or 4-12 points for FACEBD/MESH
controllers once as the light's Professional schedule, then the controller
follows its own clock. Manual saves the curve without activating it.

Use **Load from fixture** in the Professional editor to request fresh controller
state and explicitly import its reported Professional curve. Loading does not
save, activate, or overwrite the Home Assistant copy until **Apply Schedule** is
selected. If no Professional curve is reported, the current editor remains
untouched. The subtitle identifies a Home Assistant copy, an uploaded curve
awaiting readback, or confirmed fixture readback.

Select **Auto** under Schedule type to edit the fixture's native sunrise and
sunset times, ramp durations, optional sleep time, and day/night channel levels.
**Save Auto to fixture** uploads the complete Auto schedule once and activates
Automatic mode. **Load Auto from fixture** explicitly refreshes and imports the
controller's Auto readback without modifying the Professional editor. Channel
labels follow the configured fixture profile, including four-channel AquaSky and
five-channel Plant/Plant Pro layouts.

Card schedule points use positional `channel_1` through `channel_5` keys. Their
display labels come from the detected fixture's APK-backed product profile, so
the same card schema maps correctly to AquaSky, Plant, Plant Pro, and Marine
channel layouts. Existing RGB-style point keys remain accepted and are migrated
when the schedule is loaded or saved.

Use **Preview fixture time** or **Play fixture schedule** to invoke the APK's
native preview path against the schedule already loaded from the controller.
Preview never uploads the editor copy: load or save and then explicitly load the
fixture schedule first. Classic fixtures receive `680B` preview levels and
`680C` to stop; FACEBD and Plant Pro/MESH fixtures evaluate their stored
schedule at the requested minute. **Stop preview** restores the prior fixture
mode.

Use **Play editor preview** for the existing Professional graph simulation.
When **Physical preview** is enabled, its ordinary channel writes remain
throttled to 30-minute schedule intervals. This editor-owned path is separate
from fixture-native preview and can display unsaved Professional changes.

### Timed effects

The timed-effects card loads the effect catalog reported by the positively
identified controller: 11 weather effects for supported classic and AquaSky
3.0/FACEBD fixtures, or the four Plant Pro effects. Each weekday can belong to
only one window, matching FluvalConnect, and each window requires an effect,
start and end time, and at least one weekday.

Use **Apply to fixture** to upload the complete set of windows once. The fixture
then runs them from its own clock. **Clear fixture schedule** sends the
controller's native empty schedule. Both operations save the submitted windows
as the Home Assistant copy. **Load from fixture** explicitly replaces the
editor with controller readback but does not upload it again.

FACEBD and Plant Pro controllers can report the complete timed-effect schedule.
Classic state responses expose only one embedded timed-effect slot, so the card
labels that readback as partial and retains the complete Home Assistant copy
until the user explicitly chooses **Load from fixture**.
