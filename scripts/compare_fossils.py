"""Show each dig site's fossil pool, base ROM vs the Elite hack.

The pool is read from the verified dig table: 8-byte kaseki-rock records
inside map/m/* (map 3000 = Treasure Lake = Sucho/Goyle/Proto/Tricera/Shoni/
Raja/Menchi/Pacro/Thalasso in vanilla, matching in-game digs).

Usage:
    python scripts/compare_fossils.py            # all dig sites
    python scripts/compare_fossils.py 3000 5000  # specific maps
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import ndspy.rom

from ffc_hack_tool.compression.mar import decompress_mar
from ffc_hack_tool.formats.map_spawn import build_kaseki_index, find_dig_records, find_isolated_records

BASE = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced).nds"
HACK = REPO / "projects" / "elite-champions" / "Fossil Fighters Elite Champions.nds"
CREATURES = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced)" / "etc" / "creature_defs.dcl.json"


def payload(rom, path):
    raw = rom.getFileByName(path)
    return decompress_mar(raw)[0] if raw[:4] == b"MAR\x00" else raw


def pools_of(base, hack, map_id, kaseki, names):
    """Detect records on the BASE map (stable), read both ROMs' values there."""
    import struct

    try:
        b = payload(base, f"map/m/{map_id}")
        h = payload(hack, f"map/m/{map_id}")
    except Exception:
        return None, None
    records = find_dig_records(b, kaseki.valid_ids)
    records += find_isolated_records(b, kaseki.valid_ids, set(kaseki.vivo_part))
    before, after = defaultdict(set), defaultdict(set)
    for record in records:
        vb = kaseki.vivo_part.get(record.kaseki_id)
        va = kaseki.vivo_part.get(struct.unpack_from("<H", h, record.offset + 6)[0])
        if vb:
            before[names.get(vb[0], f"#{vb[0]}")].add(vb[1])
        if va:
            after[names.get(va[0], f"#{va[0]}")].add(va[1])
    return before, after


def fmt(species):
    return ", ".join(sorted(species)) if species else "(none)"


def main() -> None:
    creatures = json.loads(CREATURES.read_text(encoding="utf-8"))
    names = {i: e.get("_defaultName", f"#{i}") for i, e in enumerate(creatures["vivosaurs"]) if e and e.get("isEntry")}
    base = ndspy.rom.NintendoDSRom.fromFile(str(BASE))
    hack = ndspy.rom.NintendoDSRom.fromFile(str(HACK))
    kaseki = build_kaseki_index(payload(base, "etc/kaseki_defs"), set(names))

    if len(sys.argv) > 1:
        map_ids = sys.argv[1:]
    else:
        map_ids = sorted(base.filenames.subfolder("map").subfolder("m").files)

    moved = total = 0
    for map_id in map_ids:
        before, after = pools_of(base, hack, map_id, kaseki, names)
        if not before:
            continue
        total += len(before)
        moved += len(set(before) - set(after or {}))
        print(f"\n=== dig site {map_id} ({len(before)} species) ===")
        print(f"  vanilla : {fmt(before)}")
        print(f"  now     : {fmt(after or {})}")
    if total:
        print(f"\n{moved}/{total} pool species relocated across the shown sites.")


if __name__ == "__main__":
    main()
