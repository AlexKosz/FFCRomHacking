"""Build the Fossil Fighters Elite Champions ROM hack (by RuntimeAlex)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ffc_hack_tool.presets import elite
from ffc_hack_tool.rom_patcher import build_elite_rom

SOURCE_ROM = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced).nds"
UNPACKED = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced)"
OUT_DIR = REPO / "projects" / "elite-champions"


def main() -> None:
    creatures_json = UNPACKED / "etc" / "creature_defs.dcl.json"
    if not SOURCE_ROM.exists():
        sys.exit(f"Base ROM not found: {SOURCE_ROM}")
    if not creatures_json.exists():
        sys.exit(f"Unpacked creature defs not found: {creatures_json}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUT_DIR / "Fossil Fighters Elite Champions.nds"

    print("Building Fossil Fighters Elite Champions...")
    report = build_elite_rom(SOURCE_ROM, output, creatures_json)

    report_path = OUT_DIR / "build_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    bc = report["battle_changes"]
    ds = report["dig_pools"]
    print(f"  creatures rebalanced : {report['creatures_rebalanced']} (max buff x{report['strongest_buff']})")
    ef = report.get("element_fix")
    if ef:
        print(f"  element fix          : resistance restored (adv x{ef['advantage']}, dis x{ef['resistance']}, abilities untouched)")
    print(f"  battles hardened     : {bc['battles']} (rank curve x{elite.RANK_SCALE}+{elite.RANK_ADD}, cap 20)")
    print(f"  boss teams expanded  : {bc.get('expanded', 0)} (e.g. Tonzilla x3)")
    print(f"  enemy vivos swapped  : {bc['swapped']}")
    print(f"  boneysaurs buffed    : {bc['boney_buffed']}")
    print(f"  AI loadouts upgraded : {bc['ai_raised']} (elite palette + aiLevel 20 + super classes)")
    sharp = report.get("ai_tables_sharpened", {})
    print(f"  AI weights sharpened : {sum(sharp.values())} across {len(sharp)} tables (x{report.get('ai_weight_scale')})")
    print(f"  dig pools rebuilt    : {ds['dig_records_rewritten']} rock records across {ds['maps_changed']} sites, {ds['species_diggable']} species diggable, avg {ds['avg_species_per_zone']} species/zone")
    print(f"  early-zone skulls    : {ds['skull_records_added']} records converted to head fossils")
    print(f"  text edits           : {report['text_edits']}")
    print(f"Output: {output}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
