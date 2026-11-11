"""Export per-record dig-site data (species, parts, spawn %) for the site docs.

Reads the dig records of every map from both ROMs (vanilla + Elite
Champions) and writes RuntimeRelics/src/data/eliteChampionsDigSites.json
for the /elite-champions/docs Dig Sites tab. Spawn chance = record count /
total species records in the zone (records are equally weighted rolls).
Re-run after every hack rebuild, alongside the other export scripts.

Species schema: {"n": name, "c": total records, "p": [head, body, arms,
legs record counts]} — percentages are computed client-side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import ndspy.rom

from ffc_hack_tool.compression.mar import decompress_mar
from ffc_hack_tool.formats.map_spawn import (
    build_kaseki_index,
    find_dig_records,
    find_isolated_records,
)
from export_site_docs import ZONE_NAMES

BASE = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced).nds"
HACK = REPO / "projects" / "elite-champions" / "Fossil Fighters Elite Champions.nds"
CREATURES = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced)" / "etc" / "creature_defs.dcl.json"
MANIFEST = REPO / "webpatcher" / "patches" / "manifest.json"
OUT = REPO.parent / "RuntimeRelics" / "src" / "data" / "eliteChampionsDigSites.json"


def payload(rom: ndspy.rom.NintendoDSRom, path: str) -> bytes:
    raw = rom.getFileByName(path)
    return decompress_mar(raw)[0] if raw[:4] == b"MAR\x00" else raw


def pool_stats(data: bytes, kaseki, names) -> dict:
    """Species/part record counts for one map's dig table."""
    records = find_dig_records(data, kaseki.valid_ids)
    records += find_isolated_records(data, kaseki.valid_ids, set(kaseki.vivo_part))
    per_species: dict[str, list[int]] = {}
    total = 0
    for record in records:
        vp = kaseki.vivo_part.get(record.kaseki_id)
        if not vp:
            continue  # jewel / dropping / dark fossil
        vivo, part = vp
        name = names.get(vivo, f"#{vivo}")
        per_species.setdefault(name, [0, 0, 0, 0])[part - 1] += 1
        total += 1
    species = [
        {"n": name, "c": sum(parts), "p": parts}
        for name, parts in sorted(per_species.items(), key=lambda kv: (-sum(kv[1]), kv[0]))
    ]
    return {"total": total, "species": species}


def main() -> None:
    creatures = json.loads(CREATURES.read_text(encoding="utf-8"))
    names = {
        i: e.get("_defaultName", f"#{i}")
        for i, e in enumerate(creatures["vivosaurs"])
        if e and e.get("isEntry")
    }
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    base = ndspy.rom.NintendoDSRom.fromFile(str(BASE))
    hack = ndspy.rom.NintendoDSRom.fromFile(str(HACK))
    kaseki = build_kaseki_index(payload(base, "etc/kaseki_defs"), set(names))

    zones = []
    for fname in sorted(base.filenames.subfolder("map").subfolder("m").files, key=int):
        before = pool_stats(payload(base, f"map/m/{fname}"), kaseki, names)
        if not before["total"]:
            continue  # not a dig map
        after = pool_stats(payload(hack, f"map/m/{fname}"), kaseki, names)
        group, name = ZONE_NAMES.get(int(fname), ("Other", f"Zone {fname}"))
        zones.append(
            {
                "mapId": int(fname),
                "group": group,
                "name": name,
                "before": before,
                "after": after,
            }
        )

    out = {"version": manifest["version"], "zones": zones}
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    total_records = sum(z["after"]["total"] for z in zones)
    print(f"{len(zones)} dig zones, {total_records} species records -> {OUT}")


if __name__ == "__main__":
    main()
