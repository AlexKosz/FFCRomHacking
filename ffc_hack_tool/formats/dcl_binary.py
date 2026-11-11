"""Patch FFC creature_defs (DCL) binary in place using tier multipliers.

Layout per carbonizer's DCL_FFC.swift. Vivosaurs are keyed by their
position in the offsets table (the same order as the entries in
creature_defs.dcl.json) because the `id` field at +0x34 is NOT unique --
30 vivosaurs (super evolvers, boss variants) share an id with their base
form, and battle files reference vivosaurs by array position.

All writes are fixed-size and in place: u8 stat fields, the u8 crit rate,
and the u16 healthAtEachRank table, whose offset at +0xB8 is relative to
the vivosaur's own start (this was previously misread as file-absolute,
which corrupted unrelated vivosaur data and crashed battles).
"""

from __future__ import annotations

import struct
from typing import Any

DCL_MAGIC = b"DCL\x00"
VIVO_FIXED_HEADER = 0xBC


def _scale_stat(data: bytearray, offset: int, mult: float) -> None:
    growth, rank10, rank01, rank20 = struct.unpack_from("<BBBB", data, offset)
    struct.pack_into(
        "<BBBB",
        data,
        offset,
        growth,  # growth curve id, not a magnitude -- leave untouched
        min(255, max(1, int(round(rank10 * mult)))),
        min(255, max(1, int(round(rank01 * mult)))),
        min(255, max(1, int(round(rank20 * mult)))),
    )


# stat-block offsets inside a vivosaur, in patch order
STAT_OFFSETS = (("attack", 0x02), ("defense", 0x06), ("accuracy", 0x0A), ("speed", 0x0E))


def _as_stat_mults(mult: float | dict[str, float]) -> dict[str, float]:
    """Normalize a flat multiplier or a per-stat dict to per-stat form.
    Dict keys: attack/defense/accuracy/speed/hp, plus optional 'power'
    (overall power multiplier, drives the crit-rate nudge)."""
    if isinstance(mult, dict):
        base = {name: float(mult.get(name, 1.0)) for name, _ in STAT_OFFSETS}
        base["hp"] = float(mult.get("hp", 1.0))
        base["power"] = float(mult.get("power", base["hp"]))
        return base
    m = float(mult)
    return {"attack": m, "defense": m, "accuracy": m, "speed": m, "hp": m, "power": m}


def patch_dcl_binary(
    data: bytes,
    index_multipliers: dict[int, float | dict[str, float]],
    hp_quantum: int = 1,
) -> bytes:
    """Scale stats/health per vivosaur. Keys are creature array indices;
    values are a flat multiplier or a per-stat dict (see _as_stat_mults).

    `hp_quantum` snaps every scaled HP value to the nearest multiple (e.g. 5).
    Vanilla HP tables are mostly 5-multiples, so quantizing restores the
    cross-vivosaur byte repetition the multipliers destroy -- the difference
    between the patched file compressing back into its retail ROM slot or
    overflowing it (a relocated creature_defs fails to load on real DS
    hardware). Max distortion at quantum 5 is 2.5 LP."""
    buf = bytearray(data)
    if buf[:4] != DCL_MAGIC:
        raise ValueError("Not a DCL_FFC file")

    # header: magic(4) + 14 x i16 unknowns(28) -> count at 0x20, then the
    # offset of the offsets table itself at 0x24 (always 0x28)
    count = struct.unpack_from("<I", buf, 0x20)[0]
    offsets_offset = struct.unpack_from("<I", buf, 0x24)[0]
    offsets = struct.unpack_from(f"<{count}I", buf, offsets_offset)

    for index, offset in enumerate(offsets):
        if offset == 0 or offset + VIVO_FIXED_HEADER > len(buf):
            continue
        if buf[offset] == 0:  # isEntry == false (null vivosaur)
            continue
        mult = index_multipliers.get(index)
        if mult is None or mult == 1.0:
            continue
        mults = _as_stat_mults(mult)

        # attack/defense/accuracy/speed stat blocks
        for name, stat_off in STAT_OFFSETS:
            if abs(mults[name] - 1.0) > 1e-9:
                _scale_stat(buf, offset + stat_off, mults[name])

        crit = buf[offset + 0x12]
        buf[offset + 0x12] = max(5, min(30, int(round(crit * (0.9 + mults["power"] * 0.1)))))

        rank_count = struct.unpack_from("<I", buf, offset + 0xB4)[0]
        health_off = struct.unpack_from("<I", buf, offset + 0xB8)[0]
        if rank_count and health_off and abs(mults["hp"] - 1.0) > 1e-9:
            for i in range(rank_count):
                pos = offset + health_off + i * 2  # relative to this vivosaur
                if pos + 2 > len(buf):
                    break
                hp = int(round(struct.unpack_from("<H", buf, pos)[0] * mults["hp"]))
                if hp_quantum > 1:
                    hp = int(round(hp / hp_quantum)) * hp_quantum
                struct.pack_into("<H", buf, pos, min(0xFFFF, max(10, hp)))

    return bytes(buf)


def build_index_multipliers(
    creatures: dict[str, Any], tier_map: dict[str, str], tier_multipliers: dict[str, float]
) -> dict[int, float]:
    """Map creature array index -> stat multiplier, keyed off unique names."""
    mapping: dict[int, float] = {}
    for index, entry in enumerate(creatures.get("vivosaurs", [])):
        if not entry or not entry.get("isEntry"):
            continue
        tier = tier_map.get(entry.get("_defaultName", ""))
        if tier:
            mapping[index] = tier_multipliers.get(tier, 1.0)
    return mapping
