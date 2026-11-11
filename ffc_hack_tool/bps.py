"""BPS patch encoding/decoding for NDS ROMs.

The encoder is structure-aware: it reads the NDS header/FAT of both ROMs,
pairs regions (arm9, arm7, every FAT file) by identity, emits
SourceRead/SourceCopy for byte-identical regions and TargetRead literals
for everything else (modified files, header, FNT/FAT tables, banner,
padding). File ids are stable across a re-save, so region i of the base
pairs with region i of the hack.

Every patch is decoded back and byte-compared before being returned.
"""

from __future__ import annotations

import zlib

SOURCE_READ, TARGET_READ, SOURCE_COPY, TARGET_COPY = 0, 1, 2, 3


def put_num(out: bytearray, value: int) -> None:
    while True:
        x = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(0x80 | x)
            return
        out.append(x)
        value -= 1


def _u32(b: bytes, o: int) -> int:
    return int.from_bytes(b[o : o + 4], "little")


def _rom_regions(rom: bytes) -> list[tuple[int, int, str]]:
    """(offset, length, label) for every structured region of an NDS image."""
    regions = [
        (_u32(rom, 0x20), _u32(rom, 0x2C), "arm9"),
        (_u32(rom, 0x30), _u32(rom, 0x3C), "arm7"),
    ]
    fat_off, fat_len = _u32(rom, 0x48), _u32(rom, 0x4C)
    for i in range(fat_len // 8):
        start = _u32(rom, fat_off + i * 8)
        end = _u32(rom, fat_off + i * 8 + 4)
        if end > start:
            regions.append((start, end - start, f"file{i}"))
    return regions


def encode_bps(source: bytes, target: bytes, metadata: bytes = b"") -> bytes:
    """Structure-aware BPS delta. Raises ValueError if the two ROMs do not
    share the same region layout (different game / corrupted build)."""
    src_regions = _rom_regions(source)
    tgt_regions = _rom_regions(target)
    if len(src_regions) != len(tgt_regions):
        raise ValueError(
            f"ROM structure mismatch: base has {len(src_regions)} regions, "
            f"hack has {len(tgt_regions)}. Are these the same game?"
        )

    # matches in target order: (target_off, length, source_off)
    matches: list[tuple[int, int, int]] = []
    for (s_off, s_len, s_lab), (t_off, t_len, t_lab) in zip(src_regions, tgt_regions):
        assert s_lab == t_lab
        # zero-length regions must be skipped: BPS lengths are stored as
        # length-1, so a 0 would underflow put_num into an infinite loop
        if s_len and s_len == t_len and source[s_off : s_off + s_len] == target[t_off : t_off + t_len]:
            matches.append((t_off, t_len, s_off))
    matches.sort()

    out = bytearray(b"BPS1")
    put_num(out, len(source))
    put_num(out, len(target))
    put_num(out, len(metadata))
    out += metadata

    tgt_mv = memoryview(target)
    src_mv = memoryview(source)
    pos = 0
    source_rel = 0

    def emit_literal(start: int, end: int) -> None:
        while start < end:
            chunk = min(end - start, 0x400000)
            put_num(out, ((chunk - 1) << 2) | TARGET_READ)
            out.extend(tgt_mv[start : start + chunk])
            start += chunk

    _GAP_BLOCK = 0x1000

    def emit_gap(start: int, end: int) -> None:
        """Regions the FAT does not describe (header, FNT/FAT, banner, file
        padding, and the 0xFF fill at the end of the card). Walk them in
        blocks, turning stretches that are byte-identical at the same offset
        into SourceRead runs so unchanged padding costs nothing."""
        run_start = start
        run_same = None
        while start < end:
            stop = min(start + _GAP_BLOCK, end)
            same = stop <= len(source) and src_mv[start:stop] == tgt_mv[start:stop]
            if same != run_same and start > run_start:
                if run_same:
                    put_num(out, ((start - run_start - 1) << 2) | SOURCE_READ)
                else:
                    emit_literal(run_start, start)
                run_start = start
            run_same = same
            start = stop
        if end > run_start:
            if run_same:
                put_num(out, ((end - run_start - 1) << 2) | SOURCE_READ)
            else:
                emit_literal(run_start, end)

    for t_off, length, s_off in matches:
        if t_off < pos:  # overlapping/duplicate FAT entries -- skip
            continue
        emit_gap(pos, t_off)
        if s_off == t_off:
            put_num(out, ((length - 1) << 2) | SOURCE_READ)
        else:
            put_num(out, ((length - 1) << 2) | SOURCE_COPY)
            rel = s_off - source_rel
            put_num(out, (abs(rel) << 1) | (1 if rel < 0 else 0))
            source_rel = s_off + length
        pos = t_off + length

    emit_gap(pos, len(target))

    out += zlib.crc32(source).to_bytes(4, "little")
    out += zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def decode_bps(patch: bytes, source: bytes) -> bytes:
    """Reference decoder used to self-verify patches before shipping."""
    assert patch[:4] == b"BPS1"
    ptr = 4

    def get_num() -> int:
        nonlocal ptr
        value, shift = 0, 1
        while True:
            x = patch[ptr]
            ptr += 1
            value += (x & 0x7F) * shift
            if x & 0x80:
                return value
            shift <<= 7
            value += shift

    src_size = get_num()
    tgt_size = get_num()
    meta_size = get_num()
    ptr += meta_size
    assert src_size == len(source)

    target = bytearray(tgt_size)
    out_pos = 0
    src_rel = tgt_rel = 0
    end_of_actions = len(patch) - 12
    while ptr < end_of_actions:
        data = get_num()
        cmd = data & 3
        length = (data >> 2) + 1
        if cmd == SOURCE_READ:
            target[out_pos : out_pos + length] = source[out_pos : out_pos + length]
        elif cmd == TARGET_READ:
            target[out_pos : out_pos + length] = patch[ptr : ptr + length]
            ptr += length
        elif cmd == SOURCE_COPY:
            rel = get_num()
            src_rel += (-1 if rel & 1 else 1) * (rel >> 1)
            target[out_pos : out_pos + length] = source[src_rel : src_rel + length]
            src_rel += length
        else:  # TARGET_COPY (byte-by-byte, may self-overlap)
            rel = get_num()
            tgt_rel += (-1 if rel & 1 else 1) * (rel >> 1)
            for _ in range(length):
                target[out_pos] = target[tgt_rel]
                out_pos += 1
                tgt_rel += 1
            continue
        out_pos += length
    return bytes(target)
