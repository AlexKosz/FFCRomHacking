"""In-place NDS ROM patching that preserves the original file layout.

Fossil Fighters games are built with the assumption that files sit at fixed
card addresses: carbonizer's pack step deliberately re-uses every file's
original FAT slot and only relocates files that outgrew it (to fresh space
past the end of the original data, 0x200-aligned). Rebuilding the ROM with a
generic packer (ndspy.saveToFile) instead moves ~9,800 files and drops the
DSi-enhanced region -- the result boots on lenient emulators but crashes on
accurate ones (melonDS).

This module reproduces carbonizer's placement rules directly on the ROM
bytes: nothing outside the replaced files' extents changes, the FNT, banner,
arm9/arm7, overlays and DSi region are untouched, and the FAT only changes
for files that had to be relocated.
"""

from __future__ import annotations

import bisect
import struct

import ndspy.fnt

from .banner import crc16, set_banner_title

BANNER_SIZES = {0x0001: 0x840, 0x0002: 0x940, 0x0003: 0xA40, 0x0103: 0x23C0}


class InPlaceRom:
    def __init__(self, data: bytes | bytearray):
        self.data = bytearray(data)
        (self.fnt_off, self.fnt_len, self.fat_off, self.fat_len) = struct.unpack_from(
            "<4I", self.data, 0x40
        )
        self.banner_off = struct.unpack_from("<I", self.data, 0x68)[0]
        self.file_count = self.fat_len // 8
        self.names = ndspy.fnt.load(bytes(self.data[self.fnt_off : self.fnt_off + self.fnt_len]))
        self._staged: dict[int, tuple[str, bytes]] = {}
        self._boundaries: list[int] | None = None

    # ------------------------------------------------------------- reading

    def file_id(self, path: str) -> int:
        fid = self.names.idOf(path)
        if fid is None:
            raise FileNotFoundError(f"no such file in ROM: {path}")
        return fid

    def fat_entry(self, fid: int) -> tuple[int, int]:
        return struct.unpack_from("<II", self.data, self.fat_off + fid * 8)

    def read_file(self, path: str) -> bytes:
        start, end = self.fat_entry(self.file_id(path))
        return bytes(self.data[start:end])

    def list_folder(self, path: str) -> list[str]:
        folder = self.names
        for part in path.split("/"):
            folder = folder.subfolder(part)
        return list(folder.files)

    # ------------------------------------------------------------- editing

    def replace_file(self, path: str, blob: bytes) -> None:
        self._staged[self.file_id(path)] = (path, bytes(blob))

    def slot_size(self, path: str) -> int:
        """Bytes available at the file's current address without touching any
        other data: its FAT extent plus the alignment padding that follows it
        (retail files start 0x200-aligned, leaving a gap after each one)."""
        start, _ = self.fat_entry(self.file_id(path))
        return self._next_boundary(start) - start

    def _next_boundary(self, start: int) -> int:
        boundaries = self._boundaries
        if boundaries is None:
            boundaries = sorted(
                {self.fat_entry(fid)[0] for fid in range(self.file_count)}
                | {self.fnt_off, self.fat_off, self.banner_off, len(self.data)}
            )
            self._boundaries = boundaries
        i = bisect.bisect_right(boundaries, start)
        return boundaries[i] if i < len(boundaries) else len(self.data)

    def set_banner_title(self, title: str) -> None:
        version = struct.unpack_from("<H", self.data, self.banner_off)[0]
        size = BANNER_SIZES.get(version, 0x840)
        banner = bytes(self.data[self.banner_off : self.banner_off + size])
        self.data[self.banner_off : self.banner_off + size] = set_banner_title(banner, title)

    def save(self) -> dict:
        """Write staged replacements into the ROM image. A file stays at its
        original address if it fits its FAT extent plus the 0x200-alignment
        padding that follows it (a file that grew into that padding gets its
        FAT end updated; leftover bytes are left as-is). Only a file too big
        for the whole gap is relocated: placed after the end of all current
        data, 0x200-aligned, with its FAT entry rewritten. Returns
        {"in_place": [...], "relocated": [...]}."""
        ends = [self.fnt_off + self.fnt_len, self.fat_off + self.fat_len]
        ends.append(struct.unpack_from("<I", self.data, 0x80)[0])  # declared used size
        for fid in range(self.file_count):
            ends.append(self.fat_entry(fid)[1])
        cursor = max(ends)

        in_place: list[str] = []
        relocated: list[str] = []
        for fid in sorted(self._staged):
            path, blob = self._staged[fid]
            start, end = self.fat_entry(fid)
            if len(blob) <= self._next_boundary(start) - start:
                self.data[start : start + len(blob)] = blob
                if len(blob) > end - start:  # grew into the trailing padding
                    struct.pack_into("<II", self.data, self.fat_off + fid * 8, start, start + len(blob))
                in_place.append(path)
            else:
                new_start = (cursor + 0x1FF) & ~0x1FF
                new_end = new_start + len(blob)
                if new_end > len(self.data):
                    raise ValueError(
                        f"{path}: relocated file exceeds the ROM capacity "
                        f"({new_end} > {len(self.data)})"
                    )
                self.data[new_start:new_end] = blob
                struct.pack_into("<II", self.data, self.fat_off + fid * 8, new_start, new_end)
                cursor = new_end
                relocated.append(path)

        if relocated:
            declared = struct.unpack_from("<I", self.data, 0x80)[0]
            if cursor > declared:
                struct.pack_into("<I", self.data, 0x80, cursor)
                struct.pack_into("<H", self.data, 0x15E, crc16(bytes(self.data[:0x15E])))

        self._staged.clear()
        return {"in_place": in_place, "relocated": relocated}
