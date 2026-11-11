"""FFC/FF1 DMG message archives (see carbonizer DMG.swift).

  0x00 "DMG\x00"
  0x04 u32 stringCount
  0x08 u32 indicesOffset (0xC)
  0x0C u32[stringCount] offsets to string records
  record: u32 index, u32 stringOffset (8), null-terminated UTF-8,
          padded to 4 bytes

Round-trips byte-identically against the retail files.
"""

from __future__ import annotations

import struct

DMG_MAGIC = b"DMG\x00"


def parse_dmg(data: bytes) -> list[tuple[int, str]]:
    if data[:4] != DMG_MAGIC:
        raise ValueError("Not a DMG file")
    count, indices_off = struct.unpack_from("<II", data, 4)
    offsets = struct.unpack_from(f"<{count}I", data, indices_off)
    out: list[tuple[int, str]] = []
    for off in offsets:
        idx, s_off = struct.unpack_from("<II", data, off)
        end = data.index(0, off + s_off)
        out.append((idx, data[off + s_off : end].decode("utf-8")))
    return out


def build_dmg(entries: list[tuple[int, str]]) -> bytes:
    count = len(entries)
    indices_off = 0xC
    header = struct.pack("<4sII", DMG_MAGIC, count, indices_off)
    offsets: list[int] = []
    blobs: list[bytes] = []
    cursor = indices_off + count * 4
    for idx, text in entries:
        encoded = text.encode("utf-8") + b"\x00"
        size = (8 + len(encoded) + 3) // 4 * 4
        blobs.append(struct.pack("<II", idx, 8) + encoded + b"\x00" * (size - 8 - len(encoded)))
        offsets.append(cursor)
        cursor += size
    return header + struct.pack(f"<{count}I", *offsets) + b"".join(blobs)


def patch_dmg(data: bytes, replacements: dict[int, str]) -> tuple[bytes, int]:
    """Replace strings by message index. Returns (new file, replaced count)."""
    entries = parse_dmg(data)
    hits = 0
    patched: list[tuple[int, str]] = []
    for idx, text in entries:
        if idx in replacements:
            patched.append((idx, replacements[idx]))
            hits += 1
        else:
            patched.append((idx, text))
    return build_dmg(patched), hits
