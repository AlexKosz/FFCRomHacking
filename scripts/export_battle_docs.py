"""Export per-battle change data for the Runtime Relics site docs.

Diffs every battle_param file between the base ROM and the Elite Champions
hack and writes RuntimeRelics/src/data/eliteChampionsBattles.json for the
/elite-champions/docs Battles tab. Re-run after every hack rebuild
(alongside export_site_docs.py).

Slot schema: {"n": name, "r": rank, "m": stat multiplier (1.0 = vanilla)}.
Only enemy-side teams are exported; player-side entries never change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import ndspy.rom

from ffc_hack_tool.compression.mar import decompress_mar
from ffc_hack_tool.formats.dps_format import parse_dps
from ffc_hack_tool.presets import elite

BASE = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced).nds"
HACK = REPO / "projects" / "elite-champions" / "Fossil Fighters Elite Champions.nds"
CREATURES = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced)" / "etc" / "creature_defs.dcl.json"
MANIFEST = REPO / "webpatcher" / "patches" / "manifest.json"
CURATION = REPO / "scripts" / "battle_curation.json"
OUT = REPO.parent / "RuntimeRelics" / "src" / "data" / "eliteChampionsBattles.json"

# Name for battles with no identified trainer (see battle_curation.json).
GENERIC_TRAINER = "Fossil Fighter"


def payload(rom: ndspy.rom.NintendoDSRom, path: str) -> bytes:
    raw = rom.getFileByName(path)
    return decompress_mar(raw)[0] if raw[:4] == b"MAR\x00" else raw


def slots_json(entry, names) -> list[dict]:
    return [
        {
            "n": names.get(s.vivo_id, f"#{s.vivo_id}"),
            "r": s.rank,
            "m": round(s.mult / 0x1000, 2),
        }
        for s in entry.slots
        if s.vivo_id
    ]


def main() -> None:
    creatures = json.loads(CREATURES.read_text(encoding="utf-8"))
    names = {
        i: e.get("_defaultName", f"#{i}")
        for i, e in enumerate(creatures["vivosaurs"])
        if e and e.get("isEntry")
    }
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    curation = json.loads(CURATION.read_text(encoding="utf-8")).get("battles", {})

    base = ndspy.rom.NintendoDSRom.fromFile(str(BASE))
    hack = ndspy.rom.NintendoDSRom.fromFile(str(HACK))

    battle_files = sorted(
        base.filenames.subfolder("battle_param").files,
        key=lambda f: int(f.rsplit("_", 1)[1]),
    )

    battles = []
    changed_count = 0
    for fname in battle_files:
        bid = int(fname.rsplit("_", 1)[1])
        path = f"battle_param/{fname}"
        try:
            b0 = parse_dps(payload(base, path))
            b1 = parse_dps(payload(hack, path))
        except Exception:
            continue
        if not b0 or not b1 or not b0.entries:
            continue

        teams = []
        changed = False
        for e0, e1 in zip(b0.entries, b1.entries):
            if e0.is_player_side:
                continue
            before = slots_json(e0, names)
            after = slots_json(e1, names)
            ai0 = list(e0.ai_bytes)
            ai1 = list(e1.ai_bytes)
            team = {"before": before, "after": after}
            if ai0 != ai1:
                team["aiBefore"] = ai0
                team["aiAfter"] = ai1
            if before != after or ai0 != ai1:
                changed = True
            teams.append(team)

        if not teams:
            continue
        cur = curation.get(str(bid), {})
        trainer = cur.get("trainer") or GENERIC_TRAINER
        battles.append(
            {
                "id": bid,
                "tutorial": bid in elite.TUTORIAL_BATTLES,
                "changed": changed,
                "trainer": trainer,
                "named": bool(cur.get("trainer")),
                "location": cur.get("location"),
                "teams": teams,
            }
        )
        changed_count += changed

    curated = sum(1 for b in battles if b["named"])
    located = sum(1 for b in battles if b["location"])
    out = {
        "version": manifest["version"],
        "smartAiFloor": elite.SMART_AI_FLOOR,
        "battles": battles,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(
        f"{len(battles)} battles ({changed_count} changed, "
        f"{curated} named trainers, {located} with location) -> {OUT}"
    )


if __name__ == "__main__":
    main()
