"""FFC DTX text archives (text/*): a flat list of UTF-8 strings.

  0x00 "DTX\x00"
  0x04 u32 stringCount
  0x08 u32 indicesOffset (0xC)
  0x0C u32[stringCount] offsets to null-terminated UTF-8 strings
  strings, tightly packed; the file is padded to 4 bytes at the end

Unlike DMG archives, entries carry no message index -- the string's position
in the list is its id. Round-trips byte-identically against the retail files.
"""

from __future__ import annotations

import struct

DTX_MAGIC = b"DTX\x00"


def parse_dtx(data: bytes) -> list[str]:
    if data[:4] != DTX_MAGIC:
        raise ValueError("Not a DTX file")
    count, indices_off = struct.unpack_from("<II", data, 4)
    offsets = struct.unpack_from(f"<{count}I", data, indices_off)
    out: list[str] = []
    for off in offsets:
        end = data.index(0, off)
        out.append(data[off:end].decode("utf-8"))
    return out


def build_dtx(strings: list[str]) -> bytes:
    count = len(strings)
    indices_off = 0xC
    header = struct.pack("<4sII", DTX_MAGIC, count, indices_off)
    offsets: list[int] = []
    blobs: list[bytes] = []
    cursor = indices_off + count * 4
    for text in strings:
        encoded = text.encode("utf-8") + b"\x00"
        blobs.append(encoded)
        offsets.append(cursor)
        cursor += len(encoded)
    body = b"".join(blobs)
    padding = b"\x00" * (-(len(header) + count * 4 + len(body)) % 4)
    return header + struct.pack(f"<{count}I", *offsets) + body + padding
