# mrzottel Feedback Review

This document tracks the original owner’s feedback ([GitHub issue #2](https://github.com/mrzottel/fluvalble/issues/2)) and how the integration addresses it.

---

## 1. Encryption

**Feedback:** *"Most likely stuff like encryption needs an overhaul."*

**Current state:**  
We use a fixed XOR scheme: header `[0x54, (len+1)^0x54, 0x5A]`, payload bytes XOR’d with `0x0E`, CRC XOR’d over all bytes.

**Reference (Planted Tank / Fluval Plant 3.0):**  
- Format: `[IV] [Length] [Key] [byte1, byte2, ...]`  
- IV = `0x54`, Length = `(raw_len+1) ^ 0x54`, Key = `rand ^ 0x54`  
- Payload bytes XOR’d with `rand` (often 0 for sends)  
- CRC = XOR of all bytes in the plaintext message  

**Differences:**  
- Planted Tank uses a per-message random key; we use a fixed XOR.  
- Some devices/firmware may expect the Planted Tank scheme.  

**Action:**  
- Keep current scheme as default (it works for some devices).  
- Add a comment in `encryption.py` referencing the Planted Tank protocol.  
- If users report “lamp connected but doesn’t respond,” consider adding an optional encryption variant (e.g. config option or device-type detection) to use the Planted Tank scheme.  

---

## 2. Channel Count (4 vs 5)

**Feedback:** *"The number of channels for different lamp types need to be accounted for. Some lamps use 4 channels, like the Aquasky 2.0, others have 5 channels."*

**Current state:**  
We hardcode 5 channels for all devices.

**Change made:**  
- Detect channel count from the first received packet.  
- If packet length ≥ 15 bytes (includes channel 5), use 5 channels.  
- Otherwise use 4 channels (Aquasky 2.0).  
- `device.numbers()` returns only the channels for that device.  
- Brightness commands only send the channels the device supports.  

---

## 3. BLE Packet Size (13 bytes payload)

**Feedback:** *"BLE packets are limited to 13 bytes payload, so sometimes there are more than 1 packet inbound/outbound."*

**Current state:**  
- **Inbound:** We reassemble multi-packet payloads. The first fragment is 17 decrypted bytes; the final fragment can differ. We buffer and deliver the full payload.  
- **Outbound:** Our commands stay within limits:  
  - Power: `[0x68, 0x03, 0x00/0x01]` + CRC = 4 bytes  
  - Mode: `[0x68, 0x02, mode]` + CRC = 4 bytes  
  - Brightness: `[0x68, 0x04]` + 5×2 bytes + CRC = 13 bytes (at limit for 5-channel)  
  - For 4-channel: 2 + 8 + 1 = 11 bytes (within limit)  

**Action:**  
- No change needed for current commands.  
- If we add longer commands later, split into multiple BLE writes.  

---

## References

- [Reverse Engineering the Fluval Plant 3.0 BLE protocol](https://www.plantedtank.net/threads/reverse-engineering-the-fluval-plant-3-0-ble-protocol.1325539/)  
- [fluval-bluetooth-hub](https://github.com/TheRealFalseReality/fluval-bluetooth-hub) (ESPHome)  
- [ESPHome fluval_ble_led](https://esphome.io/components/fluval_ble_led.html) (if available)  

---

*Last updated to reflect mrzottel’s feedback and current implementation.*
