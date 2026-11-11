"""FFC battle_param DPS format (reverse-engineered).

Layout (all little-endian):
  0x00  "DPS\x00"
  0x0A  u16 battle id (matches file suffix)
  0x34  u32 offset of entry 1 (0 = none)
  0x38  u32 offset of entry 2
  0x3C  u32 offset of entry 3
  0x40  u32 end-of-file offset

Entry (offset relative to file start):
  +0x00 u16[6] header: [?, preBattleMsgId, aiLevel?, reward?, flag, ?]
        preBattleMsgId == 0 marks a player-controlled side.
  +0x0C four (count u32, offset u32) pairs; offsets relative to entry start:
        pair 0: vivosaur slots, 12 bytes each:
                u16 vivosaurIndex (0-based index into creature_defs array;
                    id 0 is the empty slot, which works because array
                    index 0 is a dummy entry -- see the note below),
                u16 rank (1-20), u16 ?, u16 lpOverride, u32 ?
        pair 1: per-vivosaur u32 stat multiplier, 0x1000 == 1.0
        pair 2: per-vivosaur u16 tactic class (observed 1-4)
        pair 3: 4 bytes, AI tactic ids (observed 1-17, matching the 17
                entries of etc/ai_tactics_defs)

All patching is done in place; nothing changes size, so surrounding
structures stay valid.

On vivosaurIndex being 0-based
------------------------------
This docstring said "1-based" until it was checked against the ROM, and it
is worth stating the evidence because getting it wrong shifts every enemy
in the game by one creature:

  * creature_defs index 0 is not a real entry, which is what lets slot id 0
    serve as "empty" without colliding with a vivosaur;
  * ids 184-190 appear in BareBones Brigade fights and map exactly onto
    B-Rex .. B-Plesio at those array indices;
  * id 210 appears in battles and is Salada. Read as 1-based it would be
    Squiro, and Salada could not be referenced at all.

`presets/elite.py` has always read these correctly (`info.get(slot.vivo_id)`
with no offset). It was the documentation that was wrong.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

DPS_MAGIC = b"DPS\x00"


@dataclass
class VivoSlot:
    offset: int  # absolute file offset of the 12-byte slot
    vivo_id: int
    rank: int
    mult_offset: int = 0  # absolute offset of this slot's u32 multiplier
    mult: int = 0x1000
    tac_offset: int = 0  # absolute offset of this slot's u16 tactic class
    tactic: int = 0


@dataclass
class BattleEntry:
    offset: int
    pre_battle_msg: int
    ai_level: int
    reward: int
    slots: list[VivoSlot] = field(default_factory=list)
    ai_offset: int = 0  # absolute offset of the 4 AI tactic bytes
    ai_bytes: bytes = b""

    @property
    def is_player_side(self) -> bool:
        return self.pre_battle_msg == 0


@dataclass
class BattleFile:
    battle_id: int
    entries: list[BattleEntry] = field(default_factory=list)


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def parse_dps(data: bytes) -> BattleFile | None:
    if data[:4] != DPS_MAGIC or len(data) < 0x44:
        return None
    size = len(data)
    battle = BattleFile(battle_id=_u16(data, 0x0A))

    for slot_off in (0x34, 0x38, 0x3C):
        eo = _u32(data, slot_off)
        # Some files reuse these header words for other data; validate hard.
        if not eo or eo % 4 or not (0x44 <= eo <= size - 0x2C):
            continue
        vivo_count = _u32(data, eo + 0xC)
        if not (1 <= vivo_count <= 3):
            continue
        pairs = [
            (_u32(data, eo + 0xC + i * 8), _u32(data, eo + 0x10 + i * 8))
            for i in range(4)
        ]
        (n_v, o_v), (n_m, o_m), (n_t, o_t), (n_a, o_a) = pairs
        if eo + o_v + n_v * 12 > size or eo + o_m + n_m * 4 > size:
            continue
        if eo + o_t + n_t * 2 > size or eo + o_a + n_a > size:
            continue

        entry = BattleEntry(
            offset=eo,
            pre_battle_msg=_u16(data, eo + 2),
            ai_level=_u16(data, eo + 4),
            reward=_u16(data, eo + 6),
            ai_offset=eo + o_a,
            ai_bytes=bytes(data[eo + o_a : eo + o_a + n_a]),
        )
        for i in range(n_v):
            so = eo + o_v + i * 12
            slot = VivoSlot(offset=so, vivo_id=_u16(data, so), rank=_u16(data, so + 2))
            if i < n_m:
                slot.mult_offset = eo + o_m + i * 4
                slot.mult = _u32(data, slot.mult_offset)
            if i < n_t:
                slot.tac_offset = eo + o_t + i * 2
                slot.tactic = _u16(data, slot.tac_offset)
            entry.slots.append(slot)
        battle.entries.append(entry)

    return battle


def write_battle(data: bytearray, battle: BattleFile) -> None:
    """Write slot/AI values from a (possibly modified) BattleFile back in place."""
    for entry in battle.entries:
        struct.pack_into("<H", data, entry.offset + 4, entry.ai_level)
        for slot in entry.slots:
            struct.pack_into("<HH", data, slot.offset, slot.vivo_id, slot.rank)
            if slot.mult_offset:
                struct.pack_into("<I", data, slot.mult_offset, slot.mult)
            if slot.tac_offset:
                struct.pack_into("<H", data, slot.tac_offset, slot.tactic)
        if entry.ai_offset and entry.ai_bytes:
            data[entry.ai_offset : entry.ai_offset + len(entry.ai_bytes)] = entry.ai_bytes
