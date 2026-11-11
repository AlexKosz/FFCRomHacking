"""Patch a base FFC ROM directly (no full repack, no file moves).

Files are pulled out of the ROM as MAR archives, decompressed, patched in
place (every edit is size-preserving inside the payload), then re-encoded
with the SAME per-file compression scheme the retail file used (huffman/
lzss/rle chunks; unchanged chunks keep their original bytes). The rebuilt
file is written back into its original FAT slot, so the ROM layout -- which
the game and accurate emulators (melonDS) depend on -- never changes. Only
a file that outgrows its slot is relocated, using the same rule carbonizer
applies (fresh 0x200-aligned space past the end of the original data).

Every replaced file is verified from the output image before the build
reports success.
"""

from __future__ import annotations

import json
from pathlib import Path

from .compression.mar import decompress_mar, repack_mar_like
from .formats.dal_format import parse_dal
from .formats.dcl_binary import patch_dcl_binary
from .formats.dtx_format import parse_dtx
from .formats.dmg_format import patch_dmg
from .formats.dps_format import parse_dps
from .nds_inplace import InPlaceRom
from .patches import element_fix
from .presets import elite, meta

DCL_PATH = "etc/creature_defs"
DAL_PATH = "etc/attack_defs"
ATTACK_INFO_PATH = "text/text_attack_info"


def build_elite_rom(
    source_rom: Path,
    output_rom: Path,
    creatures_json: Path,
    *,
    banner_title: str = f"Fossil Fighters\nElite Champions\nby {elite.HACK_AUTHOR}",
    fix_element_resistance: bool = True,
) -> dict:
    creatures = json.loads(creatures_json.read_text(encoding="utf-8"))
    info = elite.load_creature_info(creatures)
    tier_map = elite.compute_tier_map(creatures)
    swap_map = elite.build_swap_map(info)

    rom = InPlaceRom(source_rom.read_bytes())
    report: dict = {"tier_map": tier_map}
    expected: dict[str, bytes] = {}  # path -> payload the output must decode to

    def get_payload(path: str) -> bytes:
        return decompress_mar(rom.read_file(path))[0]

    def set_payload(path: str, payload: bytes) -> None:
        original = rom.read_file(path)
        rom.replace_file(path, repack_mar_like(original, [payload], fit=rom.slot_size(path)))
        expected[path] = payload

    # 1. five-pillar meta rebalance. A tier decides how much a vivosaur
    # should move; presets/meta.py prices its stats, kit, crit and support
    # effects against each other and decides WHERE that change lands, so a
    # vivosaur that is strong because of one cheap skill has the skill
    # repriced rather than its stat block shaved (see presets/meta.py).
    moves = parse_dal(get_payload(DAL_PATH))
    descriptions = parse_dtx(get_payload(ATTACK_INFO_PATH))
    plan = meta.compute_meta_plan(creatures, moves, tier_map, descriptions)

    # 1a. stats -- the stat pillar's share of each adjustment. hp_quantum=5
    # snaps scaled HP to 5s so the patched file compresses back into its
    # retail slot; relocation is fatal on real hardware.
    rebalance = elite.compute_rebalance(creatures, tier_map, plan["statAdjust"])
    index_mults = {i: r["mults"] for i, r in rebalance.items()}
    dcl = patch_dcl_binary(get_payload(DCL_PATH), index_mults, hp_quantum=5)

    # 1b. crit rate and support effects, into the same buffer.
    dcl, crit_changed, support_changed = meta.apply_creature_edits(dcl, plan["vivosaurs"])
    set_payload(DCL_PATH, dcl)

    # 1c. skills: FP cost, damage and status chance.
    set_payload(DAL_PATH, meta.apply_move_edits(get_payload(DAL_PATH), moves, plan["moves"]))

    report["creatures_rebalanced"] = len(rebalance)
    report["strongest_buff"] = round(
        max((r["powerMult"] for r in rebalance.values()), default=1.0), 3
    )
    report["meta"] = {
        "movesEdited": len(plan["moves"]),
        "critChanged": crit_changed,
        "supportChanged": support_changed,
        "curatedMoves": sum(1 for e in plan["moves"].values() if "curated" in e),
    }
    report["meta_plan"] = {
        item["name"]: {
            "tier": item["tier"],
            "adjust": item["adjust"],
            "shares": item["shares"],
            "fractions": item["fractions"],
            "crit": item["crit"],
            "supportNet": item["supportNet"],
            # the post-change support vectors, so the docs can show a
            # before/after per stat rather than just a net
            "support": {
                "ally": item["support"]["ally"],
                "enemy": item["support"]["enemy"],
                "changed": item["support"]["changed"],
            },
            "skills": item["skills"],
        }
        for item in plan["vivosaurs"].values()
    }
    report["move_edits"] = {str(k): v for k, v in plan["moves"].items()}

    # 1b. elemental resistance fix: one constant in btl_adjust_defs -- the
    # game's dedicated disadvantage multiplier slot ships as x1.0; set it to
    # FF1's x0.75 (see patches/element_fix.py / docs/ELEMENT_FIX.md)
    if fix_element_resistance:
        set_payload("etc/btl_adjust_defs", element_fix.patch_btl_adjust(get_payload("etc/btl_adjust_defs")))
        report["element_fix"] = {
            "advantage": element_fix.ADVANTAGE_MULT / 0x1000,
            "resistance": element_fix.RESISTANCE_MULT / 0x1000,
        }

    # 2. battles: swaps, boney buffs, hard mode, smarter AI
    totals = {"battles": 0, "swapped": 0, "boney_buffed": 0, "ai_raised": 0, "expanded": 0}
    for name in rom.list_folder("battle_param"):
        path = f"battle_param/{name}"
        try:
            payload = get_payload(path)
        except Exception:
            continue
        # boss-team multiplication (e.g. 1 Tonzilla -> 3) runs before hard
        # mode so the added copies get the same rank/AI scaling
        expanded = False
        parsed = parse_dps(payload)
        if parsed is not None and parsed.battle_id in elite.TEAM_EXPANSIONS:
            payload = elite.expand_enemy_team(payload, elite.TEAM_EXPANSIONS[parsed.battle_id])
            expanded = True
        result = elite.patch_battle_payload(payload, info, swap_map)
        if result is None:
            if not expanded:
                continue
            patched, stats = payload, {"swapped": 0, "boney_buffed": 0, "ai_raised": 0}
        else:
            patched, stats = result
        set_payload(path, patched)
        totals["battles"] += 1
        totals["expanded"] += int(expanded)
        for key in ("swapped", "boney_buffed", "ai_raised"):
            totals[key] += stats[key]
    report["battle_changes"] = totals

    # 2b. AI table sharpening: triple every signed weight in the scoring
    # tables so the AI's preferred action wins by a wider margin (see
    # docs/AI_SYSTEM.md, "Beyond vanilla")
    sharpened = {}
    for table in elite.AI_TABLES_TO_SHARPEN:
        path = f"etc/{table}"
        patched, weights = elite.sharpen_ai_weights(get_payload(path))
        set_payload(path, patched)
        sharpened[table] = weights
    report["ai_tables_sharpened"] = sharpened
    report["ai_weight_scale"] = elite.AI_WEIGHT_SCALE

    # 3. dig pools -- the kaseki-record tables the game rolls when you dig
    map_payloads: dict[str, bytes] = {}
    for name in rom.list_folder("map/m"):
        try:
            payload = get_payload(f"map/m/{name}")
        except Exception:
            continue
        if payload[:4] == b"MAP\x00":
            map_payloads[name] = payload
    kaseki_payload = get_payload("etc/kaseki_defs")

    def map_fits(name: str, payload: bytes) -> bool:
        path = f"map/m/{name}"
        cap = rom.slot_size(path)
        return len(repack_mar_like(rom.read_file(path), [payload], fit=cap)) <= cap

    shuffled_maps, dig_report = elite.build_dig_pool_shuffle(
        map_payloads, kaseki_payload, info, fits=map_fits
    )
    for name, payload in shuffled_maps.items():
        if payload != map_payloads[name]:
            set_payload(f"map/m/{name}", payload)
    report["dig_pools"] = {
        k: dig_report[k]
        for k in (
            "dig_records_rewritten",
            "skull_records_added",
            "species_relocated",
            "species_diggable",
            "avg_species_per_zone",
            "maps_changed",
        )
    }
    report["dig_pool_detail"] = dig_report["pools"]

    # 4. story text
    text_log = {}
    for msg_name, edits in elite.TEXT_EDITS.items():
        path = f"msg/{msg_name}"
        patched, hits = patch_dmg(get_payload(path), edits)
        set_payload(path, patched)
        text_log[msg_name] = f"{hits}/{len(edits)} strings replaced"
    report["text_edits"] = text_log

    # 5. banner title
    rom.set_banner_title(banner_title)

    placement = rom.save()
    if placement["relocated"]:
        # A file that moves out of its retail FAT slot fails to load on real
        # DS hardware (black-screen hang at its first read). Every patched
        # payload must fit its slot; fail the build rather than ship that.
        raise RuntimeError(
            "build would relocate files out of their retail FAT slots "
            f"(fatal on real hardware): {placement['relocated']}"
        )
    output_rom.write_bytes(rom.data)
    report["placement"] = {
        "files_patched_in_place": len(placement["in_place"]),
        "files_relocated": placement["relocated"],
    }

    # 6. verify: every touched file in the written ROM must decode to exactly
    # the payload we intended
    check = InPlaceRom(output_rom.read_bytes())
    for path, payload in expected.items():
        actual = decompress_mar(check.read_file(path))[0]
        if actual != payload:
            raise RuntimeError(f"verification failed: {path} does not decode to the patched payload")
    report["verified_files"] = len(expected)

    report["output"] = str(output_rom)
    return report
