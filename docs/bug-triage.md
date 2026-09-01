# Resolved Bug Triage

This document records the resolution and remaining hardware-validation
boundaries for the two protocol bugs that originally blocked reliable AquaSky
2.0 control and fixture clock synchronization. Both upstream issues are now
closed.

| # | Title | Resolution |
|---|-------|------------|
| [#6](https://github.com/MrMooreUK/fluvalble/issues/6) | AquaSky 2.0 connected but did not respond to commands | Fixed by [PR #20](https://github.com/MrMooreUK/fluvalble/pull/20) |
| [#8](https://github.com/MrMooreUK/fluvalble/issues/8) | Automatic schedule drifted after a power cut | Fixed by [PR #25](https://github.com/MrMooreUK/fluvalble/pull/25) |

---

## #6 — AquaSky 2.0 commands ignored

**Original symptom:** The integration connected to an AquaSky 2.0, but power
or channel commands did not affect the fixture. The controller briefly
disconnected and returned with its preceding state.

**Resolution:** PR #20 aligned the classic BLE transport with the affected
controller by:

- preferring GATT write-without-response when the characteristic supports it;
- decoding classic channel status using the controller's 0–1000 wire scale;
- logging the selected GATT response mode and raw/encrypted payloads for future
  protocol diagnosis.

An affected AquaSky 2.0 user reported working control before the issue was
closed. The same issue also exposed a missing Sync clock entity in the tested
release; PR #25 restored that entity and the current button platform includes
it.

---

## #8 — Schedule drift after power cut

**Original symptom:** A power interruption reset the fixture's internal
real-time clock, causing its Automatic or Professional schedule to run at the
wrong time until the clock was synchronized again.

**Resolution:** PR #25 added:

- automatic clock synchronization after a fresh BLE connection;
- a **Sync clock** button for a forced synchronization from Home Assistant;
- a reset of the synchronization flag on disconnect so the next session
  synchronizes again.

The classic OLD BLE `0x0E` clock command was validated on physical four-channel
hardware. The FACEBD timezone/clock keys and Plant Pro/mesh clock frame are
covered by unit tests, but their physical behavior should still be confirmed on
representative AquaSky 3.0 and Plant Pro hardware when available.

---

## Reporting a new bug

When a new issue is opened, ask the reporter to:

1. Confirm the integration version from **Settings → Devices & services →
   Fluval Aquarium LED → info**.
2. Enable debug logging:

   ```yaml
   logger:
     default: info
     logs:
       custom_components.fluvalble: debug
   ```

3. Capture the log snippet around one failing command with Bluetooth addresses
   and other identifiers redacted.
4. Note the exact lamp model and Bluetooth route, such as a built-in adapter or
   ESPHome Bluetooth proxy.
5. Describe what the physical fixture did; Home Assistant state alone does not
   prove that a BLE command succeeded.
