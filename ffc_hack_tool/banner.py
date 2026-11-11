"""Patch the NDS icon/banner title (shown in the DS menu) with CRC fixes."""

from __future__ import annotations

TITLE_OFFSETS = [0x240 + i * 0x100 for i in range(8)]  # JP,EN,FR,DE,IT,ES,ZH,KR


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def set_banner_title(banner: bytes, title: str) -> bytes:
    """Write `title` (use \\n for line breaks, max 3 lines) into every
    language slot present in the banner and fix the checksums."""
    buf = bytearray(banner)
    version = buf[0] | (buf[1] << 8)

    encoded = title.encode("utf-16-le")[:0xFE]
    slot = encoded + b"\x00" * (0x100 - len(encoded))

    title_count = {0x0001: 6, 0x0002: 7, 0x0003: 8, 0x0103: 8}.get(version, 6)
    for offset in TITLE_OFFSETS[:title_count]:
        if offset + 0x100 <= len(buf):
            buf[offset : offset + 0x100] = slot

    # checksums: crcA always; crcB/C for v2/v3; crcD for DSi animated banners
    buf[0x02:0x04] = crc16(buf[0x20:0x840]).to_bytes(2, "little")
    if version >= 0x0002:
        buf[0x04:0x06] = crc16(buf[0x20:0x940]).to_bytes(2, "little")
    if version >= 0x0003:
        buf[0x06:0x08] = crc16(buf[0x20:0xA40]).to_bytes(2, "little")
    if version & 0x0100 and len(buf) >= 0x23C0:
        buf[0x08:0x0A] = crc16(buf[0x1240:0x23C0]).to_bytes(2, "little")
    return bytes(buf)
