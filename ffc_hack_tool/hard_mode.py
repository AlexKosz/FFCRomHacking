"""Hard mode for workspace (carbonizer-unpacked) projects.

Operates on the decompressed battle_param DPS files in the project's rom
directory using the structure-aware parser -- the old version blind-patched
bytes in the etc/ai_* binaries and battle files, which corrupted offsets
and crashed the game at the start of combat.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .formats.dps_format import parse_dps, write_battle
from .presets.elite import (
    AI_LEVEL,
    AI_PALETTE,
    SEED,
    TACTIC_CLASS_CHOICES,
    TACTIC_CLASS_WEIGHTS,
    TUTORIAL_BATTLES,
)


def apply_hard_mode(rom_dir: Path, rank_bonus: int = 2) -> dict:
    battle_dir = rom_dir / "battle_param"
    boosted = ai_raised = 0
    if battle_dir.exists():
        for file in sorted(battle_dir.iterdir()):
            if file.name.endswith(".metadata") or file.suffix:
                continue
            data = file.read_bytes()
            battle = parse_dps(data)
            if battle is None or battle.battle_id in TUTORIAL_BATTLES:
                continue
            changed = False
            for entry_index, entry in enumerate(battle.entries):
                if entry.is_player_side:
                    continue
                rng = random.Random(SEED ^ (battle.battle_id * 0x9E3779B9) ^ entry_index)
                if entry.ai_bytes and any(entry.ai_bytes):
                    quad = rng.choice(AI_PALETTE)
                    new_ai = bytes(quad[i % 4] for i in range(len(entry.ai_bytes)))
                    if new_ai != entry.ai_bytes:
                        entry.ai_bytes = new_ai
                        ai_raised += 1
                        changed = True
                if entry.ai_level < AI_LEVEL:
                    entry.ai_level = AI_LEVEL
                    changed = True
                for slot in entry.slots:
                    if slot.vivo_id and slot.rank < 20:
                        slot.rank = min(20, slot.rank + rank_bonus)
                        changed = True
                    if slot.tac_offset and slot.tactic:
                        new_class = rng.choices(TACTIC_CLASS_CHOICES, TACTIC_CLASS_WEIGHTS)[0]
                        if new_class != slot.tactic:
                            slot.tactic = new_class
                            changed = True
            if changed:
                buf = bytearray(data)
                write_battle(buf, battle)
                file.write_bytes(bytes(buf))
                boosted += 1

    log = {"battles_boosted": boosted, "ai_entries_raised": ai_raised}
    (rom_dir.parent / "hard_mode_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    return log
