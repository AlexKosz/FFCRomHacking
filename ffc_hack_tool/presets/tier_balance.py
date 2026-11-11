"""Legacy (v2) tier assignments and stat rebalance.

SUPERSEDED -- DO NOT EDIT THE TIER SETS BELOW. Nothing reads them.

The live tier list is the data file `scripts/tier_list.json`, loaded by
`elite.load_tier_list()`. Everything in this module except `_power_score` is
kept only for reference.

The tier sets here were transcribed from the single-player WIKI tier list and
were never the competitive list they claimed to be: checked against the
community placement writeups they agreed on 46 of 204 vivosaurs. Because v3
used a tier as an absolute power budget, those 158 disagreements became stat
edits in the wrong direction -- Krypto sat in S+ (community: D*), Zongazonga
in S+ (community: D), Salada in F (community: S). Editing them now would do
nothing; edit scripts/tier_list.json instead.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

# Wiki tier 1 -> S+
TIER_S_PLUS = {
    "Saichan", "Zanth", "Krypto", "Nigo", "Heracles",
    "Z-Rex", "Zongazonga", "Shoni", "T-Rex Lord", "Pachrino", "Dilopho",
}

# Wiki tier 2 + core support
TIER_S = {
    "Ankylo", "Parapu", "Megath", "Berta", "Sopteryx", "Dacerus", "Parium",
    "Guan", "Dimetro", "Compso", "Mapo King", "Giga Allo", "Giga Spinax",
    "T-Rex", "Dynal", "Raptin", "Frigi", "Igno",
}

# Wiki tiers 3-4
TIER_A = {
    "Nodo", "Raja", "Barbaros", "O-Raptor Fiend", "Pelto", "Mihu", "Tricera",
    "Metri", "Ourano", "Igua", "Aeros", "Seidon", "Sucho", "Mapo", "Giganto",
    "Geneos", "Allo", "Carchar", "Acro", "Spino", "Daspleto", "Tarbo",
    "Gorgo", "Venator", "Brachio", "Lambeo", "Argento", "Seidon", "Teffla",
    "Raja", "Equinas", "Seismo", "Perso", "Machai", "Tophis", "Dinomaton",
}

# Wiki tiers 5-7
TIER_B = {
    "Nycto", "Thalasso", "Ceros", "Dimorph", "V-Raptor", "Breme", "Brontoth",
    "Pendem", "Tonzilla", "B-Lambeo", "Z-Tricera", "Z-Elasmo",
    "Ryden", "Edapho", "Lugmos", "Shenliu", "Tanstro", "Buldor", "Krona",
    "Stygi", "Pachy", "Elasmoth", "Hypsi", "Peloro", "Kaishin", "Blitzigon",
    "Titanis", "Hoplo", "Gaudry", "Shuno", "Stego", "Metria", "Hibigon",
    "V-Ripper", "Despino", "Megalo", "Papygon", "Apato", "Menchi", "Oloro",
    "Nippono", "Paraloph", "Anato", "Omias", "Dydomio", "Galgaron", "S-Raptor",
    "F-Raptor", "Spinax", "Cryo", "Delta", "Neo", "Salto", "Amargo", "Cerato",
    "Carno", "Camara", "Kentro", "Arsith", "Cheirus", "U-Raptor", "Andrarch",
    "Smilo", "Aopteryx", "Alectro", "Alio", "Yango",
    "Jiango", "Styraco", "Dunkle", "Gomp", "Lagia", "Desmo",
    "Paki", "B-Rex", "Duna", "Momo", "Bulgon",
}

# Wiki tiers 8-10
TIER_C = {
    "Tsintao", "Chasmo", "Goyle", "Anan", "Lexo", "Einio", "Futabi", "Proto",
    "Nycto Ace", "Siamo", "Elasmo", "Angato", "Onyx",
    "Toba", "Penta", "Coatlus", "Sungari", "Terata", "Dikelo",
    "Radox", "Anomalo", "Archaeo", "Coelo", "Chelon", "B-Tricera",
    "Nychus", "Tro", "Synthos", "Tryma",
    "E-Raptor",
}

# Wiki tiers 11-12
TIER_D = {
    "Jara", "Guera", "Ptera", "Epidex", "M-Raptor", "O-Raptor", "Nasaur",
    "Mammoth", "Plesio", "Hopter", "Pacro", "Maia",
    "Orno", "Centro", "Zino", "Coelanth",
}

# Wiki tiers 13-14 + obvious joke tiers
TIER_F = {
    "Squik", "Squirk", "Squirth", "Squilk", "Squiro", "Salada",
    "B-Jara", "Z-Ptera", "B-Ptera", "B-Plesio", "B-Brachio", "Marple",
}

TIER_MULTIPLIERS = {
    "S+": 0.86,
    "S": 0.90,
    "A": 0.95,
    "B": 1.00,
    "C": 1.08,
    "D": 1.16,
    "F": 1.24,
}

# Hard mode: enemies hit harder without undoing balance
ENEMY_STAT_MULT = 1.12
ENEMY_LEVEL_BONUS = 3


def _power_score(entry: dict[str, Any]) -> float:
    hp = entry["healthAtEachRank"][19] if entry.get("healthAtEachRank") else 0
    atk = entry["stat1Attack"]["rank20Value"]
    defn = entry["stat2Defense"]["rank20Value"]
    acc = entry["stat3Accuracy"]["rank20Value"]
    spd = entry["stat4Speed"]["rank20Value"]
    return hp * 0.4 + atk * 3.2 + defn * 2.8 + acc * 1.8 + spd * 3.5


def tier_for_name(name: str, power: float, percentile: float) -> str:
    if name in TIER_S_PLUS:
        return "S+"
    if name in TIER_S:
        return "S"
    if name in TIER_A:
        return "A"
    if name in TIER_B:
        return "B"
    if name in TIER_C:
        return "C"
    if name in TIER_D:
        return "D"
    if name in TIER_F:
        return "F"

    if percentile >= 0.94:
        return "S+"
    if percentile >= 0.82:
        return "S"
    if percentile >= 0.62:
        return "A"
    if percentile >= 0.40:
        return "B"
    if percentile >= 0.22:
        return "C"
    if percentile >= 0.10:
        return "D"
    return "F"


def _scale_stat_block(block: dict[str, Any], mult: float) -> None:
    for key in ("rank01Value", "rank10Value", "rank20Value"):
        if key in block:
            block[key] = max(1, int(round(block[key] * mult)))
    if "growthRate" in block:
        block["growthRate"] = max(1, min(5, int(round(block["growthRate"] * (0.85 + mult * 0.15)))))


def apply_tier_balance(creatures: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    entries = [
        (i, e, _power_score(e))
        for i, e in enumerate(creatures.get("vivosaurs", []))
        if e and e.get("isEntry")
    ]
    scores = sorted(p for _, _, p in entries)
    tier_map: dict[str, str] = {}

    for _, entry, power in entries:
        name = entry.get("_defaultName", "?")
        if not scores:
            pct = 0.5
        else:
            rank = sum(1 for s in scores if s <= power)
            pct = rank / len(scores)
        tier = tier_for_name(name, power, pct)
        tier_map[name] = tier
        mult = TIER_MULTIPLIERS[tier]

        for stat_key in ("stat1Attack", "stat2Defense", "stat3Accuracy", "stat4Speed"):
            if stat_key in entry:
                _scale_stat_block(entry[stat_key], mult)

        if entry.get("healthAtEachRank"):
            entry["healthAtEachRank"] = [
                max(10, int(round(hp * mult))) for hp in entry["healthAtEachRank"]
            ]

        entry["critRate"] = max(5, min(30, int(round(entry.get("critRate", 15) * (0.9 + mult * 0.1)))))

    return creatures, tier_map


def apply_hard_mode_creatures(creatures: dict[str, Any]) -> dict[str, Any]:
    """Slight enemy-oriented buff via support effect tuning on top tiers only."""
    for entry in creatures.get("vivosaurs", []):
        if not entry or not entry.get("isEntry"):
            continue
        name = entry.get("_defaultName", "")
        if name in TIER_S_PLUS | TIER_S:
            for key in ("supportEffectsForEnemy",):
                effects = entry.get(key)
                if isinstance(effects, dict):
                    for k, v in list(effects.items()):
                        if isinstance(v, (int, float)) and v < 0:
                            effects[k] = int(v * 0.75)
    return creatures
