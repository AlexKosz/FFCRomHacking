"""Export Elite Champions change data for the Runtime Relics site docs.

Reads the build report + creature defs and computes the exact per-vivosaur
stat multipliers with the same code the ROM builder uses, then writes
RuntimeRelics/src/data/eliteChampionsDocs.json for the /elite-champions/docs
page. Re-run after every hack rebuild:

    python scripts/build_elite_champions.py
    python scripts/export_site_docs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ffc_hack_tool.patches import element_fix
from ffc_hack_tool.presets import elite, meta

UNPACKED = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced)"
REPORT = REPO / "projects" / "elite-champions" / "build_report.json"
MANIFEST = REPO / "webpatcher" / "patches" / "manifest.json"
OUT = REPO.parent / "RuntimeRelics" / "src" / "data" / "eliteChampionsDocs.json"

# map/m/<id> -> zone label. 3000 = Treasure Lake is gameplay-verified
# (see formats/map_spawn.py); the rest are inferred by matching each id
# group's zone count against the game's text_map_name table (e.g. five
# Jungle Labyrinth entries <-> 3100-3104). 6xxx labels are the least
# certain; the docs page notes that labels are inferred.
ZONE_NAMES = {
    3000: ("Ribular Island", "Treasure Lake — Zone 1"),
    3001: ("Ribular Island", "Treasure Lake — Zone 2"),
    3002: ("Ribular Island", "Treasure Lake — Zone 3"),
    3003: ("Ribular Island", "Bonehead Hollow"),
    3100: ("Ribular Island", "Jungle Labyrinth — Zone 1"),
    3101: ("Ribular Island", "Jungle Labyrinth — Zone 2"),
    3102: ("Ribular Island", "Jungle Labyrinth — Zone 3"),
    3103: ("Ribular Island", "Jungle Labyrinth — Zone 4"),
    3104: ("Ribular Island", "Jungle Labyrinth — Zone 5"),
    3200: ("Ribular Island", "Petrified Woods — Zone 1"),
    3201: ("Ribular Island", "Petrified Woods — Zone 2"),
    3202: ("Ribular Island", "Petrified Woods — Zone 3"),
    3400: ("Ribular Island", "Stone Pyramid — Zone 1"),
    3401: ("Ribular Island", "Stone Pyramid — Zone 2"),
    4000: ("Cranial Isle", "Mt. Krakanak — Zone 1"),
    4001: ("Cranial Isle", "Mt. Krakanak — Zone 2"),
    4002: ("Cranial Isle", "Mt. Krakanak — Zone 3"),
    4003: ("Cranial Isle", "Crater"),
    4100: ("Cranial Isle", "Rainbow Canyon — Zone 1"),
    4101: ("Cranial Isle", "Rainbow Canyon — Zone 2"),
    4102: ("Cranial Isle", "Rainbow Canyon — Zone 3"),
    4103: ("Cranial Isle", "BareBones Grotto"),
    4104: ("Cranial Isle", "Red Canyon"),
    4105: ("Cranial Isle", "Blue Canyon"),
    4106: ("Cranial Isle", "Green Canyon"),
    4107: ("Cranial Isle", "Yellow Canyon"),
    4108: ("Cranial Isle", "White Canyon"),
    4300: ("Cranial Isle", "Dusty Dunes — Zone 1"),
    4301: ("Cranial Isle", "Dusty Dunes — Zone 2"),
    5000: ("Ilium Island", "Hot Spring Heights — Zone 1"),
    5001: ("Ilium Island", "Hot Spring Heights — Zone 2"),
    5002: ("Ilium Island", "Hot Spring Heights — Zone 3"),
    5003: ("Ilium Island", "Hot Spring"),
    5100: ("Ilium Island", "Icegrip Plateau — Zone 1"),
    5101: ("Ilium Island", "Icegrip Plateau — Zone 2"),
    6000: ("Late-game & special", "BB Brigade Base"),
    6100: ("Late-game & special", "Zongazonga's Castle"),
    6200: ("Late-game & special", "Inside the Bonehemoth — Zone 1"),
    6201: ("Late-game & special", "Inside the Bonehemoth — Zone 2"),
    6202: ("Late-game & special", "Bonehemoth Mouth"),
    6400: ("Late-game & special", "Seabed Cavern"),
}


# staticBlueAbility enum -> how the docs page describes it.
#
# NOTE: this hack does not modify abilities at all. staticBlueAbility and
# abilityArgument are read straight from retail and only DISPLAYED here. The
# previous version of this file invented the argument's meaning -- rendering
# autoCounter as "100% damage", fpPlus as "120 FP each turn" and partingBlow
# as "15% on KO" -- and because the docs table prints the ability beside the
# before/after stat columns, readers reasonably concluded the hack had
# rewritten them. Every string below is now either quoted from the game's own
# text or explicitly marked unverified.
#
# `effect` is the in-game description. `tier` maps abilityArgument onto the
# 1-3 ability tier the game and community use. Both mappings are confirmed
# three ways against the community placement writeups:
#   fpPlus       arg 11/12/13 -> tiers 1/2/3   (Sopteryx arg 13 = "FP plus 3")
#   partingBlow  arg 15/20/30 -> tiers 1/2/3   (Tricera arg 30 = "tier 3
#                                               parting blow"; Centro arg 20
#                                               = "Parting Blow 2")
FP_PLUS_TIERS = {11: 1, 12: 2, 13: 3}
PARTING_BLOW_TIERS = {15: 1, 20: 2, 30: 3}

ABILITY_INFO = {
    "fpPlus": {
        "name": "FP Plus",
        # msg_0800: "FP Plus, which boosts the FP-recharge amount at the
        # start of a turn."
        "effect": "Boosts the FP recharged at the start of each turn.",
        "tiers": FP_PLUS_TIERS,
        "verified": True,
    },
    "partingBlow": {
        "name": "Parting Blow",
        # A status that switches on when the vivosaur is close to death, not
        # an on-KO effect: text_action_info has "Parting Blow is no longer
        # active!", msg_1244 has "Parting Blow has gone active", and the
        # dino-info entries read "triggered when it feels threatened" (Aeros)
        # and "gives it a boost when it's faced with defeat" (Elasmoth).
        "effect": "A status that switches on when LP runs low.",
        "tiers": PARTING_BLOW_TIERS,
        "verified": True,
    },
    "autoCounter": {
        "name": "Auto Counter",
        # msg_0800: "Auto Counter, which lets a vivosaur hit back for a
        # little damage when attacked." Every one of the 15 users carries
        # argument 100, so the argument cannot be a per-vivosaur damage
        # figure -- it reads as a 100% activation rate.
        "effect": "Hits back for a little damage when attacked.",
        "verified": True,
    },
    "autoLPRecovery": {
        "name": "Auto LP Recovery",
        # msg_0800: "Auto LP Recovery, which restores LP by a small amount
        # every turn."
        "effect": "Restores a small amount of LP every turn.",
        "verified": True,
    },
    "fpAbsorb": {"name": "FP Absorb", "effect": "Absorbs FP from attackers.", "verified": False},
    "elementalBoost": {"name": "Elemental Boost", "effect": None, "verified": True},
    "positionLock": {
        "name": "Position Lock",
        # Chelon's dino-info: "the rare Position Lock ability, which prevents
        # its team from being rotated."
        "effect": "Prevents its team from being rotated.",
        "verified": True,
    },
    "soloPower": {
        "name": "Solo Power",
        # Tophis's dino-info: "Solo Power, which sharply raises its Attack
        # when fighting without allies."
        "effect": "Sharply raises Attack when it has no allies left.",
        "verified": True,
    },
    "berserker": {"name": "Berserker", "effect": None, "verified": False},
    "startWithAStatus": {
        "name": "Status Starter",
        "effect": None,
        "verified": False,
    },
    "resurrect": {"name": "Resurrect", "effect": None, "verified": False},
}


def ability_display(entry: dict) -> dict | None:
    """Structured, retail-sourced ability description for the docs table."""
    key = entry.get("staticBlueAbility", "nothing")
    spec = ABILITY_INFO.get(key)
    if not spec:
        return None
    arg = entry.get("abilityArgument", 0)
    name = spec["name"]
    tier = (spec.get("tiers") or {}).get(arg)
    if tier:
        name = f"{name} {tier}"
    effect = spec["effect"]
    if key == "startWithAStatus":
        # arg 21 = Quicken, confirmed by Anomalo/Dikelo's dino-info text; the
        # other status ids are not verifiable from parseable data.
        effect = (
            "Starts the battle with Quicken."
            if arg == 21
            else "Starts the battle with a status boost."
        )
    return {
        "name": name,
        "effect": effect,
        "tier": tier,
        "argument": arg,
        "verified": bool(spec["verified"]),
        "retail": True,   # this hack never edits abilities
    }


PILLAR_LABEL = {"stats": "stat block", "kit": "skills", "crit": "crit rate",
                "support": "support effects"}
# ("carries" vs "carry" -- the labels are a mix of singular and plural)
PILLAR_VERB = {"stats": "carries", "kit": "carry", "crit": "carries",
               "support": "carry"}


def _pct(value: float) -> str:
    return f"{abs(value) * 100:.0f}%"


def rationale(
    name: str,
    tier: str,
    stats: dict[str, list[int]],
    meta_item: dict | None,
    move_rows: list[dict],
    override: dict | None,
) -> str:
    """A first-person account of how this vivosaur's change was decided.

    Written from the actual numbers the pass used, not a canned template: the
    pillar shares, the skills that moved and the curated corrections are all
    read back out of the build report.
    """
    if override and override.get("hold"):
        return f"I left {name} exactly as retail. {override['reason']}"

    changed = [k for k, (before, after) in stats.items() if before != after]
    if not meta_item and not changed and not move_rows:
        return (
            f"I did not change {name}. It sits in {tier}, which is close enough to "
            "the middle of the roster that any adjustment would have been a point "
            "or two -- noise in a changelog rather than balance -- so I left it "
            "byte-identical to the retail game."
        )

    parts: list[str] = []
    if not meta_item and move_rows:
        # A skill is one object shared by every vivosaur that learns it, so
        # repricing it for one user necessarily reaches the others.
        shared = ", ".join(row["name"] for row in move_rows)
        parts.append(
            f"I did not target {name} — {tier} tier sits inside the band I leave "
            f"alone, and its stat block is untouched. It shares {shared} with a "
            "vivosaur that did need rebalancing, and a skill is a single object in "
            "the game data, so the new cost reaches every vivosaur that learns it. "
            "Where a skill is shared I use the average of what its users needed "
            "rather than applying one user's figure to everybody."
        )
    if meta_item:
        adjust = meta_item["adjust"]
        verb = "take about" if adjust < 0 else "add about"
        direction = "off" if adjust < 0 else "to"
        parts.append(
            f"{name} is {tier} tier on the community list, so I set out to {verb} "
            f"{_pct(adjust)} {direction} it."
        )
        shares = meta_item["shares"]
        top = max(shares, key=lambda k: shares[k])
        # Only claim a pillar absorbed the change if it actually moved -- a
        # vivosaur can top out on a pillar that has nowhere left to go (Zino
        # already sits at the game's maximum 100% crit).
        moved = {
            "stats": any(before != after for before, after in stats.values()),
            "kit": bool(move_rows),
            "crit": meta_item["crit"]["before"] != meta_item["crit"]["after"],
            "support": meta_item["supportNet"]["before"] != meta_item["supportNet"]["after"],
        }
        landed = max(
            (k for k in shares if moved[k]), key=lambda k: shares[k], default=None
        )
        opening = (
            f"Before deciding where that lands I priced all four pillars against "
            f"each other: its {PILLAR_LABEL[top]} {PILLAR_VERB[top]} "
            f"{_pct(shares[top])} of its power, more than anything else"
        )
        if landed == top:
            parts.append(opening + ", so that is where most of the change went "
                         "rather than spreading it evenly.")
        elif landed:
            parts.append(
                opening + f", but it is already at the game's limit there, so the "
                f"change went to its {PILLAR_LABEL[landed]} instead."
            )
        else:
            parts.append(opening + ".")

    if move_rows:
        bits = []
        for row in move_rows[:3]:
            fp_before, fp_after = row["fp"]
            if fp_before != fp_after:
                bits.append(f"{row['name']} now costs {fp_after} FP instead of {fp_before}")
            elif row["damage"][0] != row["damage"][1]:
                bits.append(f"{row['name']} hits for {row['damage'][1]} instead of {row['damage'][0]}")
            elif row["chance"][0] != row["chance"][1]:
                bits.append(f"{row['name']} lands {row['chance'][1]}% of the time instead of {row['chance'][0]}%")
        if bits:
            parts.append("On its skills: " + "; ".join(bits) + ".")
        for row in move_rows:
            if row.get("curated"):
                parts.append(f"On {row['name']} I overrode the model. {row['curated']}")

    if meta_item:
        crit = meta_item["crit"]
        if crit["before"] != crit["after"]:
            parts.append(
                f"Its crit rate goes {crit['before']}% to {crit['after']}%."
            )
        net = meta_item["supportNet"]
        if net["before"] != net["after"]:
            worse = abs(net["after"]) > abs(net["before"]) and net["before"] < 0
            parts.append(
                f"Its support effects move from a net {net['before']} to {net['after']}"
                + (" -- the drawback gets heavier, which is the nerf." if worse else ".")
            )

    if changed:
        hp = stats.get("hp", [0, 0])
        if hp[1] < hp[0]:
            parts.append(
                f"On the stat side I took it out of bulk ({hp[0]} to {hp[1]} LP) rather "
                "than its signature stat, so the archetype survives the nerf."
            )
        elif hp[1] > hp[0]:
            parts.append(
                f"On the stat side the buff went to what it is worst at first "
                f"({hp[0]} to {hp[1]} LP), because a weak vivosaur is held back by its "
                "floor rather than its ceiling."
            )
        else:
            moved = ", ".join(f"{k} {stats[k][0]} to {stats[k][1]}" for k in changed)
            parts.append(f"On the stat side: {moved}.")

    if override and override.get("stats"):
        parts.append(f"I also overrode the model here. {override['reason']}")

    return " ".join(parts)


def scaled_stat(value: int, mult: float) -> int:
    """Mirror dcl_binary._scale_stat's rounding exactly."""
    return min(255, max(1, int(round(value * mult))))


def scaled_hp(value: int, mult: float) -> int:
    return min(0xFFFF, max(10, int(round(value * mult))))


def technical(report: dict) -> dict:
    """The engine-level changes the docs page's "Under the hood" section
    describes: everything that isn't a stat, a dig record or a battle team."""
    sharpened = report.get("ai_tables_sharpened", {})
    ef = report.get("element_fix")
    return {
        "elementFix": ef
        and {
            "file": "etc/btl_adjust_defs",
            "offset": f"+0x{element_fix.ELEMENT_VECTOR_OFFSET + 8:02X}",
            "before": f"0x{element_fix.RETAIL_VECTOR[2]:04X}",
            "after": f"0x{element_fix.RESISTANCE_MULT:04X}",
            "advantage": ef["advantage"],
            "resistance": ef["resistance"],
            "boostAdvantage": element_fix.FIXED_VECTOR[0] / 0x1000,
            "boostDisadvantage": element_fix.FIXED_VECTOR[3] / 0x1000,
        },
        "ai": {
            "weightScale": report.get("ai_weight_scale"),
            "weightsScaled": sum(sharpened.values()),
            "tables": sharpened,
            "excludedTable": "ai_attack_defs",
            "aiLevel": elite.AI_LEVEL,
            "smartAiFloor": elite.SMART_AI_FLOOR,
            "paletteSize": len(elite.AI_PALETTE),
        },
        "text": {
            "files": len(elite.TEXT_EDITS),
            "strings": sum(len(v) for v in elite.TEXT_EDITS.values()),
        },
        "build": {
            "filesPatchedInPlace": report["placement"]["files_patched_in_place"],
            "filesRelocated": len(report["placement"]["files_relocated"]),
            "verifiedFiles": report["verified_files"],
            "protectedBattles": len(elite.TUTORIAL_BATTLES),
        },
    }


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    creatures = json.loads(
        (UNPACKED / "etc" / "creature_defs.dcl.json").read_text(encoding="utf-8")
    )

    tier_map: dict[str, str] = report["tier_map"]
    meta_plan: dict = report.get("meta_plan", {})
    move_edits: dict = report.get("move_edits", {})
    attack_names = json.loads(
        (UNPACKED / "text" / "text_attack_name.dtx.json").read_text(encoding="utf-8")
    )
    overrides = elite.load_overrides()
    info = elite.load_creature_info(creatures)
    rebalance = elite.compute_rebalance(creatures, tier_map)

    # A few names appear twice (base form + super-revival variant sharing
    # the display name); keep the base form, which is what players browse.
    vivosaurs = []
    seen: set[str] = set()
    for c in sorted(info.values(), key=lambda c: c.index):
        if c.name in seen:
            continue
        seen.add(c.name)
        entry = creatures["vivosaurs"][c.index]
        reb = rebalance.get(c.index)
        mults = reb["mults"] if reb else {}

        stats: dict[str, list[int]] = {}
        for stat_name, key, _weight in elite.STAT_COMPONENTS:
            before = entry[key]["rank20Value"]
            stats[stat_name] = [before, scaled_stat(before, mults.get(stat_name, 1.0))]
        hp_before = entry["healthAtEachRank"][19] if entry.get("healthAtEachRank") else 0
        stats["hp"] = [hp_before, scaled_hp(hp_before, mults.get("hp", 1.0))]

        support = None
        ally = entry.get("supportEffectsForAlly")
        enemy = entry.get("supportEffectsForEnemy")
        if ally or enemy:
            support = {}
            if ally:
                support["ally"] = ally
            if enemy:
                support["enemy"] = enemy

        meta_item = meta_plan.get(c.name)
        override = overrides.get(c.name)
        move_rows = []
        for sid in entry.get("skillIDs", []):
            edit = move_edits.get(str(sid))
            if not edit:
                continue
            move_rows.append({
                "id": sid,
                "name": attack_names[sid] if sid < len(attack_names) else f"#{sid}",
                "fp": edit["fp"],
                "damage": edit["damage"],
                "chance": edit["chance"],
                "curated": edit.get("curated"),
            })

        vivosaurs.append(
            {
                "name": c.name,
                "element": c.element,
                "tier": tier_map.get(c.name, "B"),
                "powerMult": reb["powerMult"] if reb else 1.0,
                "supportFactor": round(c.support_factor, 3),
                "stats": stats,
                "ability": ability_display(entry),
                # Support effects are retail too -- this pass reads them to
                # price a vivosaur's power, it never rewrites them.
                "support": support,
                # Support effects and crit ARE edited now (see presets/meta.py),
                # so this ships the retail vector AND the patched one.
                "support": support,
                "supportAfter": ((meta_item or {}).get("support") or {}).get("changed")
                and {
                    "ally": meta_item["support"]["ally"],
                    "enemy": meta_item["support"]["enemy"],
                }
                or None,
                "supportNet": (meta_item or {}).get("supportNet"),
                "crit": (meta_item or {}).get("crit"),
                "pillars": (meta_item or {}).get("shares"),
                "pillarChange": (meta_item or {}).get("fractions"),
                "skillChanges": move_rows,
                "changed": (reb or {}).get("changed", []),
                "held": bool(override and override.get("hold")),
                "rationale": rationale(
                    c.name, tier_map.get(c.name, "B"), stats, meta_item, move_rows, override
                ),
                "boney": c.boney,
            }
        )

    out = {
        "version": manifest["version"],
        "summary": {
            "creaturesRebalanced": report["creatures_rebalanced"],
            "strongestBuff": report["strongest_buff"],
            **{
                "battles": report["battle_changes"]["battles"],
                "enemiesSwapped": report["battle_changes"]["swapped"],
                "boneysBuffed": report["battle_changes"]["boney_buffed"],
                "aiRaised": report["battle_changes"]["ai_raised"],
                "bossTeamsExpanded": report["battle_changes"].get("expanded", 0),
            },
            "digRecordsRewritten": report["dig_pools"]["dig_records_rewritten"],
            "skullRecordsAdded": report["dig_pools"]["skull_records_added"],
            "zonesChanged": report["dig_pools"]["maps_changed"],
            "avgSpeciesPerZone": report["dig_pools"]["avg_species_per_zone"],
        },
        "rules": {
            "tierAdjust": elite.TIER_ADJUST,
            "deadband": elite.ADJUST_DEADBAND,
            "minStep": elite.MIN_STEP,
            "maxBuff": elite.MAX_BUFF,
            "minNerf": elite.MIN_NERF,
            "accuracyFrozenOnNerf": elite.ACCURACY_FROZEN_ON_NERF,
            "retailCeilings": elite.retail_ceilings(creatures),
            "supportFactorRange": list(elite.SUPPORT_FACTOR_RANGE),
            "tierListSource": json.loads(
                elite.TIER_LIST_PATH.read_text(encoding="utf-8")
            )["source"],
            "overrides": [
                {"name": name, **spec}
                for name, spec in sorted(elite.load_overrides().items())
            ],
            "moveOverrides": [
                {"id": mid, **spec}
                for mid, spec in sorted(elite.load_move_overrides().items())
            ],
            "pillarWeights": meta.POWER_WEIGHTS,
            "pillarMaxChange": meta.PILLAR_MAX_CHANGE,
            "rankCurve": {
                "scale": elite.RANK_SCALE,
                "add": elite.RANK_ADD,
                "boneyExtra": elite.BONEY_RANK_EXTRA,
                "examples": {str(v): elite.scaled_rank(v) for v in (3, 5, 10, 13)},
            },
            "enemyStatMult": round(elite.ENEMY_MULT / 0x1000, 3),
            "boneyStatMult": round(elite.BONEY_MULT / 0x1000, 3),
        },
        "technical": technical(report),
        "vivosaurs": vivosaurs,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(vivosaurs)} vivosaurs -> {OUT}")
    print("(dig-site detail lives in export_dig_docs.py's output)")


if __name__ == "__main__":
    main()
