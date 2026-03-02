# Fluval BLE – Build / Codebase Review

A **Home Assistant custom component** that controls Fluval BLE aquarium LED lights. There is no traditional build (no npm/webpack); the integration loads and runs inside Home Assistant.

---

## Project overview

- **Type:** Home Assistant custom component (Python)
- **Location:** `custom_components/fluvalble/`
- **Stack:** HA config entries, BLE via `bluetooth` + `bleak` / `bleak_retry_connector`
- **Platforms:** `switch`, `number`, `select`, `binary_sensor`

---

## Current implementation

| Area | Status |
|------|--------|
| **Manifest** | `domain`, `config_flow`, `dependencies: ["bluetooth"]`, `documentation`, `issue_tracker`, `codeowners: @MrMooreUK` |
| **Config flow** | BLE discovery dropdown (Fluval devices only), manual MAC fallback, MAC normalization, duplicate check |
| **Switch** | `set_led_power()` sends CMD_SWITCH (0x03); on/off implemented |
| **Channels** | 4 (Aquasky 2.0) or 5 (Plant/Reef 3.0) detected from packet; big-endian; auto-switch to Manual when user changes a channel |
| **Mode** | CMD_MODE (0x02); Manual / Automatic / Professional |
| **Encryption** | Planted Tank format: `[IV][Length][Key][payload]` with rand=0 |
| **BLE packets** | Multi-packet reassembly for inbound; command queue with 200ms delay between sends |
| **Entity setup** | Device from BLE cache or callback; pending platforms when device arrives later |

---

## References

- [MRZOTTEL_FEEDBACK.md](MRZOTTEL_FEEDBACK.md) – Original owner feedback and protocol notes
- [README.md](README.md) – User-facing docs
