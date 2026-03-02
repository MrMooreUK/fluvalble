# mrzottel Feedback Review

Tracks the original owner’s feedback ([GitHub issue #2](https://github.com/mrzottel/fluvalble/issues/2)) and how the integration addresses it.

---

## 1. Encryption

**Feedback:** *"Most likely stuff like encryption needs an overhaul."*

**Current implementation:**  
Uses the **Planted Tank / Fluval Plant 3.0** scheme:
- Format: `[IV][Length][Key][payload]` with IV=0x54, Key=0x54 (rand=0), payload sent as-is
- CRC = XOR of all bytes in the plaintext message (added before encrypt)

**Reference:** [Reverse Engineering the Fluval Plant 3.0 BLE protocol](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3-0-ble-protocol.1325539/)

---

## 2. Channel Count (4 vs 5)

**Feedback:** *"Some lamps use 4 channels, like the Aquasky 2.0, others have 5 channels."*

**Current implementation:**
- Default 4 channels; upgrade to 5 when first packet has ≥15 bytes
- Brightness commands send only the channels the lamp supports
- `channel_5` entity shows unavailable for 4-channel lamps
- Channel values sent as 16-bit big-endian (high byte first)

---

## 3. BLE Packet Size (13 bytes payload)

**Feedback:** *"BLE packets are limited to 13 bytes payload, so sometimes there are more than 1 packet inbound/outbound."*

**Current implementation:**
- **Inbound:** Reassemble multi-packet payloads (17-byte fragments + final fragment)
- **Outbound:** Commands within limits; command queue with 200ms delay between sends
- Power: 4 bytes | Mode: 4 bytes | Brightness: 11–13 bytes depending on channel count

---

## References

- [Reverse Engineering the Fluval Plant 3.0 BLE protocol](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3-0-ble-protocol.1325539/)
- [fluval-bluetooth-hub](https://github.com/TheRealFalseReality/fluval-bluetooth-hub) (ESPHome)
