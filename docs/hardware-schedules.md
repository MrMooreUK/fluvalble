# Hardware schedules

Use Fluval Connect to program Auto, Professional, and supported weather
schedules directly on the fixture. The light stores and runs its schedules
independently of Home Assistant.

## Program a schedule

1. Allow Home Assistant's idle Bluetooth connection to expire without sending
   further commands. The active connection window is configurable from 30 to
   600 seconds, with a default of 120 seconds.
2. Open Fluval Connect, select the fixture, and edit and save its schedule.
3. Disconnect Fluval Connect when finished so Home Assistant can reconnect.
4. Select Automatic or Professional in Home Assistant to use the corresponding
   schedule saved on the fixture.

## Everyday Home Assistant control

Use the standard light entity for power, brightness, colour and supported
native effects. Physical channel sliders provide exact emitter control.
Mode selection, manual presets and fixture schedule readback are also available.

Under **Developer tools → Actions**, use `fluvalble.set_channels`,
`fluvalble.recall_manual_preset`, and `fluvalble.save_manual_preset` for
channel and preset operations. Ordinary Home Assistant light automations work
alongside these controls.

Classic fixtures expose expected scheduled on/off state rather than measured
illumination. See [scheduled-state reporting](scheduled-state-evidence.md)
for the evidence and limitations.
