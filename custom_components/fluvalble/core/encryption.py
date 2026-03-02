"""Encrypts/decrypts BLE packets for the Fluval LED controller.

Uses the Planted Tank / Fluval Plant 3.0 scheme: [IV][Length][Key][payload]
with rand=0 so payload is sent as-is. See reverse-engineering thread and MRZOTTEL_FEEDBACK.md.
"""


def encrypt(source: bytearray) -> bytearray:
    """Encrypt a BLE packet using Planted Tank format (IV=0x54, rand=0, payload unchanged)."""
    raw_len = len(source)
    # [IV] [Length] [Key] [byte1, byte2, ...] — with rand=0: key=0x54, bytes XOR 0
    encoded = bytearray([0x54, (raw_len + 1) ^ 0x54, 0x54])
    for b in source:
        encoded.append(b ^ 0)  # rand=0, so payload unchanged
    return encoded


def decrypt(source: bytes | bytearray) -> bytes:
    """Decrypt a BLE packet from the Fluval LED controller."""
    key = source[0] ^ source[2]
    length = len(source)
    decrypted = bytearray()
    for i in range(3, length):
        decrypted.append(source[i] ^ key)
    return decrypted


def add_crc(source: bytearray) -> bytes:
    """Calculate CRC for the packet."""
    crc = 0x0
    for b in source:
        crc = b ^ crc
    source.append(crc)
    return source
