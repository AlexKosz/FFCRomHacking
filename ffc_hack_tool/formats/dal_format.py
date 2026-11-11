"""FFC etc/attack_defs (DAL): every move/skill in the game.

  0x00 "DAL\x00"
  0x04 u32 ? (constant)
  0x08 u32 moveCount (801 in retail; move id 0 is a dummy)
  0x0C u32 indicesOffset (0x10)
  0x10 u32[moveCount] offsets to move records

Move record (variable size, offsets relative to record start):
  +0x00 u8  effectId      (0/1 = none; indexes the game's status-effect
                           handlers: 2/3 poison, 7/8 scare, 0x15 evasion...)
  +0x01 u8  effectChance  (percent shown in the in-game skill description)
  +0x02 u16 ?
  +0x04 u32 moveId        (== this record's index)
  +0x08 u32 hitCount
  +0x0C u32 offHits       (-> hitCount pairs of u16 (fpCost, damage))
  +0x10 u32 offTotal      (-> one u16 pair: summed FP cost / damage, the
                           values the game displays and charges)
  +0x14 u32 offExtra      (-> trailing words: secondary effect block)

Damage values are base power -- the game scales them by the attacker's
Attack stat and rank. FP is charged as-is. Names/descriptions live in
text/text_attack_name and text/text_attack_info (DTX), same index.

All edits are size-preserving in-place writes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

DAL_MAGIC = b"DAL\x00"


@dataclass
class MoveHit:
    offset: int  # absolute offset of the (fp, damage) u16 pair
    fp: int
    damage: int


@dataclass
class Move:
    id: int
    offset: int
    effect_offset: int  # absolute offset of the effectId/effectChance bytes
    effect_id: int
    effect_chance: int
    hits: list[MoveHit] = field(default_factory=list)
    total: MoveHit | None = None


def parse_dal(data: bytes) -> list[Move]:
    if data[:4] != DAL_MAGIC:
        raise ValueError("Not a DAL file")
    count, indices_off = struct.unpack_from("<II", data, 8)
    offsets = struct.unpack_from(f"<{count}I", data, indices_off)

    moves: list[Move] = []
    for i, off in enumerate(offsets):
        effect_id, effect_chance = struct.unpack_from("<BB", data, off)
        move_id, hit_count, off_hits, off_total = struct.unpack_from("<IIII", data, off + 4)
        move = Move(
            id=move_id,
            offset=off,
            effect_offset=off,
            effect_id=effect_id,
            effect_chance=effect_chance,
        )
        if move_id == i and 1 <= hit_count <= 8 and off_hits and off_total:
            for h in range(hit_count):
                po = off + off_hits + h * 4
                fp, dmg = struct.unpack_from("<HH", data, po)
                move.hits.append(MoveHit(offset=po, fp=fp, damage=dmg))
            to = off + off_total
            fp, dmg = struct.unpack_from("<HH", data, to)
            move.total = MoveHit(offset=to, fp=fp, damage=dmg)
        moves.append(move)
    return moves


def write_move(data: bytearray, move: Move) -> None:
    """Write an edited move's values back in place (structure unchanged)."""
    struct.pack_into("<BB", data, move.effect_offset, move.effect_id, move.effect_chance)
    for hit in move.hits:
        struct.pack_into("<HH", data, hit.offset, hit.fp, hit.damage)
    if move.total:
        struct.pack_into("<HH", data, move.total.offset, move.total.fp, move.total.damage)
