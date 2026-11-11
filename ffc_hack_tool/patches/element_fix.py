"""Restore elemental resistance ("the resistance bug fix").

In retail FFC an elemental DISADVANTAGE does nothing: Fire hits Water for
full damage unless Elemental Boost is involved. FF1 applied a x0.75
resistance; FFC shipped without it.

Reverse-engineered root cause (full trail in docs/ELEMENT_FIX.md):

`etc/btl_adjust_defs` (magic "DBA") holds the element multiplier vector at
payload offset 0x44 -- four u32s in 0x1000 fixed point, indexed by the
matchup relation:

    +0x44  0x2000  x2.0   boost advantage
    +0x48  0x1800  x1.5   advantage
    +0x4C  0x1000  x1.0   DISADVANTAGE   <- the bug: a dedicated slot,
    +0x50  0x0800  x0.5   boost disadvantage        shipped as "no effect"

(True neutral matchups never consult the vector. The battle overlay reads
it through the accessor at RAM 0x2155BCC; verified in-game 2026-07-08 by
byte-probing each slot and observing damage: +0x48 x2 doubled advantage
damage, +0x4C x0.5 cut disadvantage damage. The multiplier applies to the
attack term before defense is subtracted.)

The fix writes FF1's resistance value into the disadvantage slot:

    advantage      -> x1.5   (untouched)
    neutral        -> x1.0   (untouched)
    disadvantage   -> x0.75  (was x1.0)

Every vivosaur keeps its original blue ability; Elemental Boost keeps its
own advantage/disadvantage slots untouched.
"""

from __future__ import annotations

import struct

DBA_MAGIC = b"DBA\x00"
ELEMENT_VECTOR_OFFSET = 0x44
# [boost advantage, advantage, disadvantage, boost disadvantage]
RETAIL_VECTOR = (0x2000, 0x1800, 0x1000, 0x0800)

ADVANTAGE_MULT = 0x1800   # x1.5 -- retail, unchanged
RESISTANCE_MULT = 0x0C00  # x0.75 -- FF1's resistance value
FIXED_VECTOR = (0x2000, ADVANTAGE_MULT, RESISTANCE_MULT, 0x0800)

# FFC chart (fandom "Elemental Type"): Water > Fire > Earth > Air > Water.
# Element enum: 0 none, 1 fire, 2 air, 3 earth, 4 water, 5 neutral, 6 legendary.
BEATS = {4: 1, 1: 3, 3: 2, 2: 4}


def get_element_multiplier(attacker_element: int, defender_element: int) -> float:
    """Reference implementation of the FIXED matchup: the single source of
    truth for what the patched game computes for any attack (without
    Elemental Boost)."""
    if BEATS.get(attacker_element) == defender_element:
        return ADVANTAGE_MULT / 0x1000   # advantage -> bonus damage
    if BEATS.get(defender_element) == attacker_element:
        return RESISTANCE_MULT / 0x1000  # disadvantage -> reduced damage
    return 1.0                           # neutral -> normal damage


def patch_btl_adjust(payload: bytes) -> bytes:
    """Write the resistance multiplier into the disadvantage slot of a
    btl_adjust_defs payload. Refuses to touch a file whose vector is
    neither retail nor already fixed (so it can never scribble on an
    unknown layout)."""
    if payload[:4] != DBA_MAGIC:
        raise ValueError("not a btl_adjust_defs (DBA) payload")
    current = struct.unpack_from("<4I", payload, ELEMENT_VECTOR_OFFSET)
    if current == FIXED_VECTOR:
        return payload
    if current != RETAIL_VECTOR:
        raise ValueError(
            f"unexpected element vector {tuple(hex(v) for v in current)} -- "
            "refusing to patch an unknown btl_adjust_defs layout"
        )
    buf = bytearray(payload)
    struct.pack_into("<4I", buf, ELEMENT_VECTOR_OFFSET, *FIXED_VECTOR)
    return bytes(buf)
