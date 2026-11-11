"""Diff enemy teams / ranks / AI between the base ROM and the Elite hack.

Usage:
    python scripts/compare_battles.py            # first ~20 story battles
    python scripts/compare_battles.py 100 101    # specific battle ids
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import json
import ndspy.rom

from ffc_hack_tool.compression.mar import decompress_mar
from ffc_hack_tool.formats.dps_format import parse_dps
from ffc_hack_tool.presets import elite

BASE = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced).nds"
HACK = REPO / "projects" / "elite-champions" / "Fossil Fighters Elite Champions.nds"
CREATURES = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced)" / "etc" / "creature_defs.dcl.json"

# AI tactic ids the game's postgame/super battles lean on -- our "smart" floor.
SMART = elite.SMART_AI_FLOOR


def team(entry, names):
    return ", ".join(
        f"{names.get(s.vivo_id, '?')} r{s.rank}" for s in entry.slots if s.vivo_id
    )


def main() -> None:
    creatures = json.loads(CREATURES.read_text(encoding="utf-8"))
    names = {
        i: e.get("_defaultName", f"#{i}")
        for i, e in enumerate(creatures["vivosaurs"])
        if e and e.get("isEntry")
    }

    base = ndspy.rom.NintendoDSRom.fromFile(str(BASE))
    hack = ndspy.rom.NintendoDSRom.fromFile(str(HACK))

    if len(sys.argv) > 1:
        ids = [int(x) for x in sys.argv[1:]]
    else:
        ids = [1, 2, 3, 4, 10, 11, 12, 100, 101, 102, 103, 104, 105, 200, 201, 300, 301, 400, 500]

    for bid in ids:
        path = f"battle_param/battle_param_defs_{bid}"
        try:
            b0 = parse_dps(decompress_mar(base.getFileByName(path))[0])
            b1 = parse_dps(decompress_mar(hack.getFileByName(path))[0])
        except Exception:
            continue
        if not b0 or not b0.entries:
            continue

        tutorial = " (tutorial - intentionally unchanged)" if bid in elite.TUTORIAL_BATTLES else ""
        print(f"\n=== Battle {bid}{tutorial} ===")
        for e0, e1 in zip(b0.entries, b1.entries):
            side = "PLAYER" if e0.is_player_side else "ENEMY "
            print(f"  {side} team : {team(e0, names)}")
            if not e0.is_player_side:
                print(f"         now  : {team(e1, names)}")
                ai0, ai1 = list(e0.ai_bytes), list(e1.ai_bytes)
                smarter = sum(a1 > a0 for a0, a1 in zip(ai0, ai1))
                tag = f"  ({smarter} tactic slots raised toward smart floor {SMART})" if smarter else "  (already competent)"
                print(f"         AI   : {ai0} -> {ai1}{tag}")


if __name__ == "__main__":
    main()
