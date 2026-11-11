"""Dig-site fossil records inside FFC map/m/* MAP files.

The tables the game rolls when you dig are streams of 8-byte records
embedded in each dig-site map:

    +0x00 u16 param A (spawn weight/chance, <= 2000)
    +0x02 u16 param B (<= 2000)
    +0x04 u16 zone code (two bytes, each 1-8: area/layer)
    +0x06 u16 kaseki id (fossil rock, indexes etc/kaseki_defs)

Each kaseki id resolves to a (vivosaur, body part) via kaseki_defs, whose
FFC entries carry the vivosaur array index at +0x10 and the part number at
+0x08 (ids outside that mapping are jewels / droppings / dark fossils).

Ground truth: map 3000's records decode to Sucho / Goyle / Proto / Tricera /
Shoni / Raja / Menchi / Pacro / Thalasso -- the exact Treasure Lake pool
observed in-game. Records are located by strict validation in runs of 3+,
and only the kaseki id field is ever rewritten, so map geometry and record
weights are never touched and file sizes never change.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAP_MAGIC = b"MAP\x00"
RLS_MAGIC = b"RLS\x00"


# ---------------------------------------------------------------------------
# kaseki_defs index: rock id <-> (vivosaur, part)


@dataclass
class KasekiIndex:
    vivo_part: dict[int, tuple[int, int]]  # kaseki id -> (vivo index, part 1-4)
    rock_of: dict[tuple[int, int], int]    # (vivo index, part) -> kaseki id
    valid_ids: set[int]                    # every defined kaseki id (incl. specials)


def build_kaseki_index(kaseki_payload: bytes, vivo_ids: set[int]) -> KasekiIndex:
    if kaseki_payload[:4] != RLS_MAGIC:
        raise ValueError("Not an RLS (kaseki_defs) file")
    count, offsets_off = struct.unpack_from("<II", kaseki_payload, 4)
    offsets = struct.unpack_from(f"<{count}I", kaseki_payload, offsets_off)

    vivo_part: dict[int, tuple[int, int]] = {}
    rock_of: dict[tuple[int, int], int] = {}
    valid: set[int] = set()
    for kaseki_id, off in enumerate(offsets):
        if not off or off + 0x18 > len(kaseki_payload):
            continue
        valid.add(kaseki_id)
        part = struct.unpack_from("<H", kaseki_payload, off + 0x08)[0]
        vivo = struct.unpack_from("<H", kaseki_payload, off + 0x10)[0]
        if vivo in vivo_ids and 1 <= part <= 4:
            vivo_part[kaseki_id] = (vivo, part)
            rock_of.setdefault((vivo, part), kaseki_id)
    return KasekiIndex(vivo_part=vivo_part, rock_of=rock_of, valid_ids=valid)


# ---------------------------------------------------------------------------
# dig records inside a MAP payload


@dataclass
class DigRecord:
    offset: int  # absolute offset of the 8-byte record
    kaseki_id: int


def _looks_like_record(data: bytes, o: int, valid_ids: set[int]) -> bool:
    if o + 8 > len(data):
        return False
    a, b, zone, kaseki = struct.unpack_from("<4H", data, o)
    lo, hi = zone & 0xFF, zone >> 8
    return a <= 2000 and b <= 2000 and 1 <= lo <= 8 and 1 <= hi <= 8 and kaseki in valid_ids


def find_dig_records(data: bytes, valid_ids: set[int], min_run: int = 3) -> list[DigRecord]:
    if data[:4] != MAP_MAGIC:
        return []
    records: list[DigRecord] = []
    o = 0
    while o + 8 <= len(data):
        if _looks_like_record(data, o, valid_ids):
            run: list[DigRecord] = []
            while _looks_like_record(data, o, valid_ids):
                run.append(DigRecord(offset=o, kaseki_id=struct.unpack_from("<H", data, o + 6)[0]))
                o += 8
            if len(run) >= min_run:
                records.extend(run)
        else:
            o += 2
    return records


def find_isolated_records(
    data: bytes, valid_ids: set[int], species_rocks: set[int]
) -> list[DigRecord]:
    """Single dig records embedded inside per-spot structures, outside any
    contiguous run. Only hits whose rock id is a real species rock are
    returned. A candidate must not overlap ANY byte of a run record --
    misaligned windows straddling two run records can pass the field
    validation by chance (map 3000 alone has ~54 such phantoms), and
    writing to them would corrupt the params of real records."""
    if data[:4] != MAP_MAGIC:
        return []
    covered: set[int] = set()
    for run in find_dig_records(data, valid_ids):
        covered.update(range(run.offset, run.offset + 8))
    records: list[DigRecord] = []
    o = 0
    while o + 8 <= len(data):
        if (
            _looks_like_record(data, o, valid_ids)
            and not any(x in covered for x in range(o, o + 8))
        ):
            kaseki = struct.unpack_from("<H", data, o + 6)[0]
            if kaseki in species_rocks:
                records.append(DigRecord(offset=o, kaseki_id=kaseki))
            o += 8
        else:
            o += 2
    return records


def write_record_kaseki(data: bytearray, record: DigRecord, kaseki_id: int) -> None:
    struct.pack_into("<H", data, record.offset + 6, kaseki_id)
    record.kaseki_id = kaseki_id
