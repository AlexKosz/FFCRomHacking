"""Fossil Fighters Elite Champions preset: the hack itself.

Champions has 204 vivosaurs and most are never worth using. A handful carry
every serious team and the rest sit in the museum. Enemy trainers barely
fight back, and digging turns up the same few species for hours. This
module holds the decisions that change that, plus the code that writes them
into the game.

Five areas:

  1. Roster rebalance. The community competitive tier list says which
     vivosaurs are too strong and too weak. A tier decides only how much a
     vivosaur moves, not which of its numbers change. Top tiers can only
     lose power, bottom tiers can only gain it, and the middle is skipped.
     Deciding where that change lands is `presets/meta.py`'s job.

  2. Enemy teams. Every swappable enemy vivosaur is replaced with a
     different one of the same element and similar strength. The
     Boneysaurs (the BareBones Brigade's skeletons) are never swapped,
     since they're a recognisable gimmick. They get buffed instead.

  3. Harder battles. Enemy ranks follow a curve rather than a flat bonus,
     so early fights barely move while late-game trainers reach the cap.
     Enemies also get a small across-the-board stat boost.

  4. AI. Every enemy is dealt one of the tactic sets the retail game saves
     for its hardest fights, plus the top AI skill level. See
     docs/AI_SYSTEM.md.

  5. Dig sites, and a pass of rewritten story dialogue.

Two data files drive the balance work, and neither needs this file edited:

  * scripts/tier_list.json          who is which tier
  * scripts/balance_overrides.json  hand-written corrections, each with a
                                    written reason

One constraint shapes most of the code here. Every edit changes a
decompressed file in place without changing its size, because a DS game
hardcodes where each file sits and a file that outgrows its slot has to be
relocated. Emulators usually cope with that; real DS hardware black-screens
on it. So the rule is same size, same place, verified afterwards. That's
why health values get rounded to multiples of 5: the repetition compresses
better, which keeps the file inside its original slot.
"""

from __future__ import annotations

import json
import random
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..formats.dps_format import BattleFile, parse_dps, write_battle
from ..formats.map_spawn import (
    build_kaseki_index,
    find_dig_records,
    find_isolated_records,
    write_record_kaseki,
)
from .tier_balance import _power_score

# The community competitive tier list lives in a data file, not in Python, so
# players can propose a placement change without touching the build (v3 kept
# it as hardcoded Python sets copied from the single-player wiki list, which
# is why it disagreed with the competitive list on 158 of 204 vivosaurs).
TIER_LIST_PATH = Path(__file__).resolve().parents[2] / "scripts" / "tier_list.json"
UNLISTED_TIER = "B"   # neutral: an unlisted vivosaur is left retail


OVERRIDES_PATH = Path(__file__).resolve().parents[2] / "scripts" / "balance_overrides.json"


@lru_cache(maxsize=1)
def load_overrides() -> dict[str, dict[str, Any]]:
    """Curated per-vivosaur corrections -- see scripts/balance_overrides.json.

    The systematic pass can only see a tier and a stat block. Where the
    community writeup names a cause it cannot see (a movelist, an FP cost, an
    ability), the correction is recorded by hand with its reason attached.
    """
    data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    overrides = data.get("overrides", {})
    for name, spec in overrides.items():
        if not spec.get("reason"):
            raise ValueError(f"balance override for {name} has no reason")
        if "hold" not in spec and "stats" not in spec:
            raise ValueError(f"balance override for {name} does nothing")
    return overrides


@lru_cache(maxsize=1)
def load_move_overrides() -> dict[int, dict[str, Any]]:
    """Curated per-skill corrections, keyed by move id."""
    data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    out: dict[int, dict[str, Any]] = {}
    for key, spec in data.get("moves", {}).items():
        if not spec.get("reason"):
            raise ValueError(f"move override {key} has no reason")
        if not any(f in spec for f in ("fp", "damage", "chance")):
            raise ValueError(f"move override {key} does nothing")
        out[int(key)] = spec
    return out


@lru_cache(maxsize=1)
def load_tier_list() -> dict[str, str]:
    """Vivosaur name -> community tier, from scripts/tier_list.json."""
    data = json.loads(TIER_LIST_PATH.read_text(encoding="utf-8"))
    tiers = data["tiers"]
    unknown = sorted(set(tiers.values()) - set(TIER_ADJUST))
    if unknown:
        raise ValueError(f"tier_list.json uses tiers with no TIER_ADJUST entry: {unknown}")
    return tiers

HACK_TITLE = "Fossil Fighters Elite Champions"
HACK_AUTHOR = "RuntimeAlex"
SEED = 0xB0BE3A4E  # "Bonewake" -- deterministic builds

# v4 balance: the community tier list is the ground truth for competitive
# power, and a stat block is only ONE of the levers that produce it (moves,
# FP cost, support effects and crit rate are the others, and this pass does
# not touch them). v3 treated tiers as absolute stat BUDGETS, which meant a
# vivosaur that is top-tier for reasons outside its stat block -- Sopteryx's
# +90 ally Speed, Compso's -90/-90 enemy debuff -- read as "underpowered for
# its tier" and got BUFFED. Every S/S+ vivosaur came out of v3 stronger and
# not one was nerfed, which widened exactly the gap the pass exists to close.
#
# v4 therefore never compares a stat block to an absolute anchor. A tier only
# says which DIRECTION that vivosaur should move and by how much, and the
# adjustment is one-sided by construction: top tiers can only lose power,
# bottom tiers can only gain it. Mid tiers fall inside the deadband and are
# left byte-identical to retail.
TIER_ADJUST = {          # intended change in effective stat power
    "Nigo": -0.14,       # its own tier: "the single best vivosaur in the game"
    "S+": -0.11,
    "S": -0.07,
    "A": -0.03,          # inside the deadband -> no change
    "B": 0.00,
    "C": +0.03,          # inside the deadband -> no change
    "D": +0.08,
    "E": +0.14,
    "F": +0.20,
    # "D*" = low-tier ONLY because its defining skill is banned by the
    # community Infection Clause (Krypto, E-Raptor). That clause is a
    # tournament rule, not a game rule -- inside the hack the skill is live,
    # so buffing these to their listed tier would strengthen two vivosaurs
    # that are already oppressive. Held at retail; the real fix is to nerf
    # the skill itself in etc/attack_defs.
    "D*": 0.00,
}

# Support effects are power the stat block cannot see. In v4 this only
# MODULATES the tier adjustment (a great supporter eats a slightly deeper
# nerf and earns a slightly shallower buff) -- it no longer sets an absolute
# stat budget, which is what let v3 hand Compso a +33% stat buff for owning
# one of the best support effects in the game.
SUPPORT_POWER_PER_POINT = 0.0008
SUPPORT_FACTOR_RANGE = (0.80, 1.20)

# A vivosaur whose intended adjustment is smaller than this is left FULLY
# retail rather than nudged by a point or two. Trivial edits are not balance
# -- they are noise in the change log, and every stat byte that stays retail
# is a byte creature_defs can still compress (see the relocation notes in
# build_elite_rom: an overflowing creature_defs black-screens real hardware).
ADJUST_DEADBAND = 0.05

# Minimum change, in stat points, for a stat to be worth touching at all.
# Anything smaller is dropped back to its retail value. Accuracy is 0 because
# the tier pass never nerfs it (see ACCURACY_FROZEN_ON_NERF).
MIN_STEP = {"attack": 3, "defense": 3, "accuracy": 0, "speed": 2, "hp": 20}

# Accuracy is frozen ON NERFS: it is a hit-rate stat with a non-linear effect
# on outcomes, and v3 used it as the dump stat, taking 8-10 points off Allo,
# Lambeo, Daspleto, T-Rex and Aeros -- which plays as whiffing rather than as
# the "small nerf" the table implied. Buffs may still raise it, because a
# catastrophic accuracy is the single most-cited reason a bottom-tier
# vivosaur is unusable: Zino and Centro both sit at 6, and the community
# writeup calls Zino "next to impossible to hit anything" with it.
ACCURACY_FROZEN_ON_NERF = True

# How a nerf is taken and how a buff is spent, as a "lean": the relative
# share of the proportional change each stat absorbs. Leans are normalised
# per vivosaur so the weighted power actually moves by TIER_ADJUST, which
# keeps a big lean from turning into a runaway point swing on a high-value
# stat (HP carries the lowest power weight but the largest raw numbers).
#
# Nerfs come out of bulk first: losing staying power does not change how a
# vivosaur plays, whereas gutting its signature stat erases the archetype.
# NERF_PROTECT_EXPONENT then pulls the nerf further away from whatever the
# vivosaur is already best at -- Ankylo stays the wall, it just stops
# out-lasting everything.
NERF_LEAN = {"hp": 1.40, "defense": 1.15, "attack": 0.70,
             "speed": 0.35, "accuracy": 0.00}
NERF_PROTECT_EXPONENT = 0.50

# Buffs fix the FLOOR, not the ceiling. Sharpening a weak vivosaur's best
# stat reads well in a table and does nothing in a battle: the community
# writeups name a single binding constraint for almost every bottom-tier
# vivosaur, and it is nearly always the worst stat rather than the best one
# ("its LP keeps it out of even D tier" for Z-Tricera; "why does this thing
# have the same LP stat as Dimorph?" for B-Brachio; an accuracy of 6 for Zino
# and Centro). So a buff leans toward whatever sits furthest below the roster
# norm, with LP weighted heavily because bulk is the most-cited blocker.
BUFF_DEFICIENCY_EXPONENT = 0.80
BUFF_HP_LEAN = 1.50

# No buff may push a stat past the highest value any retail vivosaur has.
# Those maxima are landmarks the competitive scene reasons about out loud --
# T-Rex's 99 Attack is quoted as "the highest natural attack stat in the
# game" -- and stepping over them silently rewrites the game's scale. Before
# this clamp the pass wanted to give Zongazonga 108 Attack and Dikelo 40
# Speed (retail ceilings: 99 and 30).
RESPECT_RETAIL_CEILINGS = True

# Six entries (the boss/story duplicates of Pachrino, Dilopho, Shoni, T-Rex,
# Dimorph and Zino) carry a sentinel HP curve that jumps to 913..920 at rank
# 13. That is scripted-fight data, not a stat line: counted as real it adds
# 368 power points each and skews every roster-relative figure in this file.
# They are excluded from roster statistics, mirror their base form's combat
# stats, and never have their HP touched.
SENTINEL_HP_FLOOR = 900

MAX_BUFF = 1.60          # per-stat sanity cap
MIN_NERF = 0.70          # per-stat sanity floor
HP_QUANTUM = 5           # keeps creature_defs compressible (hardware-safe)

# power-score weights (mirrors tier_balance._power_score)
HP_WEIGHT = 0.4
STAT_COMPONENTS = (
    ("attack", "stat1Attack", 3.2),
    ("defense", "stat2Defense", 2.8),
    ("accuracy", "stat3Accuracy", 1.8),
    ("speed", "stat4Speed", 3.5),
)

# Scripted battles that must stay retail. Two shapes:
#   * fights where the PLAYER side carries a preset team (non-empty player
#     slots in the DPS file): the starter picks vs the rampaging Allo (1-4)
#     and their replays (1906/1907), the playable Todd-vs-Rupert file (102),
#     and the postgame preset-team challenges (3004-3007). Modifying these
#     breaks the scripted sequences (102 blocked story progression when
#     changed).
#   * AI-vs-AI demo fights (2+ entries, none player-side; only four exist):
#     the attract-mode demos (10/11/12) and 101 -- the story's WATCHED
#     Todd-vs-Rupert demo, invoked by episode/0344 alongside 102. Retail 101
#     is Todd's Stego r1 vs Rupert's Raja r12: a designed one-hit KO the
#     scene script depends on. Hardening it (Stego->Parium swap, +2 ranks,
#     elite AI) broke the scripted outcome and froze the game after the
#     fight on real hardware (playtesting 2026-07-11/12).
#   * plus 100, Todd's scripted practice fight (his signature Stego/Goyle
#     team, trainer msg 4179 like his side of 101, invoked by the intro
#     scripts) -- swapping it put a Parium on Todd's team mid-story.
TUTORIAL_BATTLES = {1, 2, 3, 4, 10, 11, 12, 100, 101, 102, 1906, 1907,
                    3004, 3005, 3006, 3007}

# Hard-mode knobs. Enemy ranks scale on a progression curve keyed on the
# vanilla rank, so early cups barely move while late-game trainers spike
# toward the cap:  rank = min(20, round(vanilla * RANK_SCALE) + RANK_ADD).
# e.g. vanilla 3 -> 6, 5 -> 9, 10 -> 16 ("Todd around 16"), 13+ -> 20.
# Because late-story/postgame enemies already carry high vanilla ranks, this
# makes them much harder without needing a per-battle trainer map.
# Boneysaurs take one extra rank on top -- they're meant to punch above.
RANK_SCALE = 1.4
RANK_ADD = 2
BONEY_RANK_EXTRA = 1
ENEMY_MULT = 0x1180  # ~1.09x, applied where vanilla uses 0x1000
BONEY_MULT = 0x1333  # ~1.20x
SWAPPABLE_MAX_INDEX = 150  # 151+ are boss variants, zombies, boneys, legends


def scaled_rank(vanilla: int, boney: bool = False) -> int:
    """Progression rank curve (see the knobs above)."""
    rank = round(vanilla * RANK_SCALE) + RANK_ADD + (BONEY_RANK_EXTRA if boney else 0)
    return max(1, min(20, rank))

# --- AI overhaul (see docs/AI_SYSTEM.md) ---------------------------------
# Every enemy entry gets one of the AI-tactic quadruples that vanilla's
# hardest fights actually ship (postgame supers + the toughest cup
# trainers), dealt seeded per battle so fights play differently. This also
# replaces the dummy brains (ids 16/17) some story battles carry.
AI_PALETTE = [
    (11, 11, 11, 12),
    (12, 12, 12, 12),
    (11, 11, 12, 12),
    (13, 13, 12, 12),
    (14, 14, 12, 12),
    (14, 14, 13, 12),
]
# Lowest tactic id in the elite palette -- ids at or above this are the
# "late-game brain" set (used by the site docs to annotate AI changes).
SMART_AI_FLOOR = min(min(quad) for quad in AI_PALETTE)
# aiLevel: vanilla scales this 1..20 with progression; only the final story
# bosses get 20 (postgame supers sit at 9). Every elite battle gets 20.
AI_LEVEL = 20
# Per-vivosaur tactic classes, dealt with the postgame supers' observed
# distribution (they never use class 1).
TACTIC_CLASS_CHOICES = (3, 4, 2)
TACTIC_CLASS_WEIGHTS = (53, 40, 7)
# Weight sharpening for the AI scoring tables: multiply every signed weight
# so the score gap between the best action and a mediocre one triples.
# Ratios (and therefore every preference ordering) are preserved exactly;
# the retail range is +-9999 so x3 stays inside s16 with no clipping.
AI_WEIGHT_SCALE = 3
AI_TABLES_TO_SHARPEN = (
    # NOTE: ai_attack_defs ("which skill to use") is deliberately NOT
    # sharpened. Tripling its margins made the AI over-commit to whatever
    # move scored highest, including 0-damage utility moves it should skip
    # (Law of the Jungle healing at full HP, Power Scale when already set) --
    # playtesting 2026-07-13. Leaving move-choice at vanilla margins lets the
    # engine's decision randomness override those bad picks. Targeting,
    # rotation and pattern choice stay sharpened.
    "ai_target_defs",    # which enemy slot to attack
    "ai_who_defs",       # which own vivosaur acts / rotates
    "ai_relation_defs",  # element/type relation modifiers
    "ai_pattern_defs",   # per-archetype behaviour patterns
)
# ai_state/ai_kp/ai_distance hold 0-100 threshold-like values (not signed
# weights) or are empty in retail -- left untouched on purpose.


@dataclass
class CreatureInfo:
    index: int
    name: str
    element: str
    power: float          # effective power: stat power x support factor
    stat_power: float     # weighted stat total (stats + HP curve) alone
    support_factor: float
    boney: bool


def support_net(entry: dict[str, Any]) -> int:
    """Net support-effect value: ally buffs count up, enemy buffs count
    against (a negative enemy effect is a debuff, i.e. good for you)."""
    net = 0
    ally = entry.get("supportEffectsForAlly")
    if isinstance(ally, dict):
        net += sum(ally.values())
    enemy = entry.get("supportEffectsForEnemy")
    if isinstance(enemy, dict):
        net -= sum(enemy.values())
    return net


def support_factor(entry: dict[str, Any]) -> float:
    lo, hi = SUPPORT_FACTOR_RANGE
    return max(lo, min(hi, 1.0 + support_net(entry) * SUPPORT_POWER_PER_POINT))


def load_creature_info(creatures: dict[str, Any]) -> dict[int, CreatureInfo]:
    info: dict[int, CreatureInfo] = {}
    for index, entry in enumerate(creatures.get("vivosaurs", [])):
        if not entry or not entry.get("isEntry"):
            continue
        stat_power = _power_score(entry)
        factor = support_factor(entry)
        info[index] = CreatureInfo(
            index=index,
            name=entry.get("_defaultName", f"#{index}"),
            element=entry.get("element", "neutral"),
            power=stat_power * factor,
            stat_power=stat_power,
            support_factor=factor,
            boney=any("boney" in t for t in entry.get("teamGroups", [])),
        )
    return info


def compute_tier_map(creatures: dict[str, Any]) -> dict[str, str]:
    """Name -> tier, straight from the community tier list.

    Unlike v3 there is no percentile fallback: a fallback silently invents a
    tier from the very stat total the pass is about to rewrite, which is
    circular, and it hid real errors (v3 agreed with the community list on
    only 46 of 204 vivosaurs). A name missing from the list is reported.
    """
    info = load_creature_info(creatures)
    listed = load_tier_list()
    tiers: dict[str, str] = {}
    for c in info.values():
        tiers[c.name] = listed.get(c.name, UNLISTED_TIER)
    return tiers


def unlisted_names(creatures: dict[str, Any]) -> list[str]:
    """Roster names with no entry in the community tier list."""
    listed = load_tier_list()
    return sorted(
        c.name for c in load_creature_info(creatures).values() if c.name not in listed
    )


def has_sentinel_hp(entry: dict[str, Any]) -> bool:
    """True for the boss/story duplicates whose HP curve is a 913..920
    sentinel from rank 13 up (see SENTINEL_HP_FLOOR)."""
    hp = entry.get("healthAtEachRank") or []
    return len(hp) >= 20 and hp[12] >= SENTINEL_HP_FLOOR and hp[19] >= SENTINEL_HP_FLOOR


def retail_ceilings(creatures: dict[str, Any]) -> dict[str, int]:
    """Highest retail value per stat across the real roster."""
    vivos = creatures.get("vivosaurs", [])
    real = [
        e for e in vivos
        if e and e.get("isEntry") and not has_sentinel_hp(e)
    ]
    ceilings = {
        name: max(e[key]["rank20Value"] for e in real)
        for name, key, _ in STAT_COMPONENTS
    }
    ceilings["hp"] = max(e["healthAtEachRank"][19] for e in real if e.get("healthAtEachRank"))
    return ceilings


def _stat_shares(entry: dict[str, Any]) -> dict[str, float]:
    """Each combat stat's share of the weighted stat total (HP included in
    the denominator so shares are comparable across HP-heavy tanks)."""
    total = _power_score(entry)
    if total <= 0:
        return {name: 0.0 for name, _, _ in STAT_COMPONENTS}
    return {
        name: weight * entry[key]["rank20Value"] / total
        for name, key, weight in STAT_COMPONENTS
    }


def _quantize(before: int, after: float, stat: str) -> int:
    """Round a proposed stat value and drop it back to retail unless it
    clears MIN_STEP -- the "no pointless +/- 1 or 2" rule."""
    value = int(round(after))
    if stat == "hp":
        value = int(round(value / HP_QUANTUM)) * HP_QUANTUM
    value = max(1, value)
    return before if abs(value - before) < MIN_STEP[stat] else value


def compute_rebalance(
    creatures: dict[str, Any],
    tier_map: dict[str, str],
    adjust_override: dict[str, float] | None = None,
) -> dict[int, dict[str, Any]]:
    """Creature array index -> per-stat multipliers + balance metadata.

    1. The community tier sets a one-sided target change in effective stat
       power (TIER_ADJUST). Top tiers can only lose, bottom tiers can only
       gain; A/B/C land inside ADJUST_DEADBAND and are skipped outright.
    2. Support effects are priced in, so a vivosaur that already carries its
       team through support pays a little more of a nerf and earns a little
       less of a buff than its raw stat line suggests.
    3. The delta is dealt across stats by direction: nerfs come out of bulk
       (NERF_LEAN), buffs go to whatever sits furthest below the roster norm
       (BUFF_DEFICIENCY_EXPONENT), because a weak vivosaur is held back by
       its worst stat, not its best. Accuracy is never nerfed and crit rate
       is never touched -- both are curated levers, not byproducts.
    4. Curated corrections from scripts/balance_overrides.json are applied
       last, for the cases where the community writeup names a cause the
       model cannot see (a movelist, an FP cost, an ability).
    5. Every resulting stat is quantized and dropped back to retail unless it
       moves by at least MIN_STEP. A vivosaur where nothing clears the bar
       stays byte-identical to retail.
    """
    info = load_creature_info(creatures)
    vivos = creatures.get("vivosaurs", [])

    ceilings = retail_ceilings(creatures) if RESPECT_RETAIL_CEILINGS else {}
    # Roster norms are taken over the real roster only -- the six sentinel-HP
    # duplicates would each contribute a fake 368 power points.
    all_shares = [
        _stat_shares(vivos[c.index])
        for c in info.values()
        if not has_sentinel_hp(vivos[c.index])
    ]
    mean_share = {
        name: sum(s[name] for s in all_shares) / max(len(all_shares), 1)
        for name, _, _ in STAT_COMPONENTS
    }

    result: dict[int, dict[str, Any]] = {}
    for c in info.values():
        entry = vivos[c.index]
        if has_sentinel_hp(entry):
            continue  # handled after the loop, mirroring the base form
        tier = tier_map.get(c.name, UNLISTED_TIER)
        if adjust_override is not None:
            # The five-pillar pass (presets/meta.py) has already decided how
            # much of this vivosaur's change belongs to its stat block, having
            # priced its moves, crit and support effects first. Take that
            # figure as-is: re-applying the support modifier here would
            # double-count the pillar meta.py just accounted for.
            adjust = adjust_override.get(c.name, 0.0)
        else:
            adjust = TIER_ADJUST.get(tier, 0.0)
            # A strong supporter is already contributing power the stat block
            # cannot see, so it eats a deeper nerf / a shallower buff.
            adjust *= c.support_factor if adjust < 0 else 1.0 / c.support_factor

        override = load_overrides().get(c.name, {})
        if override.get("hold"):
            continue  # curated: stats are not this vivosaur's lever

        if abs(adjust) < ADJUST_DEADBAND or c.stat_power <= 0:
            if not override.get("stats"):
                continue

        hp20 = entry["healthAtEachRank"][19] if entry.get("healthAtEachRank") else 0
        shares = _stat_shares(entry)
        befores = {name: entry[key]["rank20Value"] for name, key, _ in STAT_COMPONENTS}
        befores["hp"] = hp20

        def relative(name: str) -> float:
            """This stat's share of the vivosaur's power vs the roster norm."""
            if mean_share[name] <= 0 or shares[name] <= 0:
                return 1.0
            return shares[name] / mean_share[name]

        lean: dict[str, float] = {}
        if adjust < 0:
            for name, _, _ in STAT_COMPONENTS:
                lean[name] = NERF_LEAN[name] * relative(name) ** -NERF_PROTECT_EXPONENT
            lean["hp"] = NERF_LEAN["hp"]
            if ACCURACY_FROZEN_ON_NERF:
                lean["accuracy"] = 0.0
        else:
            for name, _, _ in STAT_COMPONENTS:
                lean[name] = relative(name) ** -BUFF_DEFICIENCY_EXPONENT
            lean["hp"] = BUFF_HP_LEAN

        # Normalise the leans so the weighted power moves by exactly `adjust`.
        denom = HP_WEIGHT * hp20 * lean["hp"] + sum(
            weight * befores[name] * lean[name] for name, _, weight in STAT_COMPONENTS
        )
        if denom <= 0:
            continue
        scale = c.stat_power / denom

        targets: dict[str, int] = {}
        for name, key, _weight in STAT_COMPONENTS:
            before = befores[name]
            after = before * (1.0 + adjust * lean[name] * scale)
            after = min(before * MAX_BUFF, max(before * MIN_NERF, after))
            if name in ceilings:
                after = min(after, max(before, ceilings[name]))
            targets[name] = _quantize(before, after, name)

        hp_after = hp20 * (1.0 + adjust * lean["hp"] * scale)
        hp_after = min(hp20 * MAX_BUFF, max(hp20 * MIN_NERF, hp_after))
        if "hp" in ceilings:
            hp_after = min(hp_after, max(hp20, ceilings["hp"]))
        targets["hp"] = _quantize(hp20, hp_after, "hp")

        # Curated corrections win over the model. A value equal to the retail
        # stat pins it, which is how a single off-target change is cancelled
        # without discarding the rest of the vivosaur's adjustment.
        for stat, value in override.get("stats", {}).items():
            if stat in targets:
                targets[stat] = int(value)

        if all(targets[k] == befores[k] for k in targets):
            continue  # nothing cleared MIN_STEP -- leave this vivosaur retail

        mults = {
            k: (targets[k] / befores[k]) if befores[k] else 1.0 for k in targets
        }
        mults["power"] = 1.0  # crit rate is a curated lever, never a byproduct

        achieved = (
            sum(
                weight * (targets[name] - befores[name])
                for name, _, weight in STAT_COMPONENTS
            )
            + HP_WEIGHT * (targets["hp"] - befores["hp"])
        )
        result[c.index] = {
            "mults": mults,
            "tier": tier,
            "supportFactor": round(c.support_factor, 3),
            "supportNet": support_net(entry),
            "powerMult": round(1.0 + achieved / c.stat_power, 3),
            "intendedAdjust": round(adjust, 3),
            "changed": sorted(k for k in targets if targets[k] != befores[k]),
        }

    # The sentinel-HP duplicates share their base form's combat stats, so they
    # take the same combat multipliers -- a nerfed T-Rex must be nerfed
    # everywhere it appears -- but their HP curve is scripted-fight data and
    # is left exactly as retail.
    by_name = {info[i].name: r for i, r in result.items()}
    for c in info.values():
        if not has_sentinel_hp(vivos[c.index]):
            continue
        base = by_name.get(c.name)
        if base is None:
            continue
        mults = {k: v for k, v in base["mults"].items()}
        mults["hp"] = 1.0
        result[c.index] = {
            **base,
            "mults": mults,
            "changed": [k for k in base["changed"] if k != "hp"],
            "mirroredFrom": c.name,
        }
    return result



# enemy team swaps


def build_swap_map(info: dict[int, CreatureInfo], seed: int = SEED) -> dict[int, int]:
    """Element-preserving, power-adjacent permutation of swappable vivosaurs."""
    rng = random.Random(seed)
    swap: dict[int, int] = {}
    by_element: dict[str, list[CreatureInfo]] = {}
    for c in info.values():
        if c.index <= SWAPPABLE_MAX_INDEX and not c.boney:
            by_element.setdefault(c.element, []).append(c)
    for element, group in sorted(by_element.items()):
        group.sort(key=lambda c: c.power)
        if len(group) < 2:
            continue
        shift = rng.randint(1, max(1, len(group) // 2))
        for pos, creature in enumerate(group):
            swap[creature.index] = group[(pos + shift) % len(group)].index
    return swap


# Boss fights we want to multiply: battle id -> enemy team size. The lead
# enemy slot is replicated to N identical copies before hard-mode scaling,
# so e.g. the lone Tonzilla (601) becomes a 3-Tonzilla wall.
TEAM_EXPANSIONS = {601: 3}


def expand_enemy_team(data: bytes, count: int) -> bytes:
    """Rebuild a single-entry battle so its enemy side fields `count` copies
    of its lead vivosaur, preserving that slot's rank/mult/tactic/AI exactly.

    The DPS entry stores four (count, offset) arrays -- vivosaur slots (12B),
    stat multipliers (4B), tactic classes (2B), AI tactic bytes (1B) -- laid
    out back to back after the pair table, with the AI array padded up to a
    4-byte boundary (matches retail). Growing the slot count grows the file,
    so this is a full structural rebuild, not an in-place edit. Only the
    single-enemy-entry shape is supported (asserted); that covers the boss
    fights in TEAM_EXPANSIONS."""
    if count < 1:
        raise ValueError("count must be >= 1")
    battle = parse_dps(data)
    if battle is None or len(battle.entries) != 1:
        raise ValueError("expand_enemy_team only handles single-entry battles")
    entry = battle.entries[0]
    eo = entry.offset
    lead = entry.slots[0]

    slot_tmpl = bytes(data[lead.offset : lead.offset + 12])
    mult_tmpl = (
        bytes(data[lead.mult_offset : lead.mult_offset + 4]) if lead.mult_offset else b"\x00\x10\x00\x00"
    )
    tac_tmpl = bytes(data[lead.tac_offset : lead.tac_offset + 2]) if lead.tac_offset else b"\x02\x00"
    ai = entry.ai_bytes or b"\x01\x01\x01\x01"

    # array offsets relative to the entry start; AI padded to 4-byte align
    off_slots = 0x2C
    off_mult = off_slots + count * 12
    off_tac = off_mult + count * 4
    off_ai = (off_tac + count * 2 + 3) & ~3
    end = off_ai + len(ai)

    body = bytearray(end - 0x2C)
    body[off_slots - 0x2C : off_slots - 0x2C + count * 12] = slot_tmpl * count
    body[off_mult - 0x2C : off_mult - 0x2C + count * 4] = mult_tmpl * count
    body[off_tac - 0x2C : off_tac - 0x2C + count * 2] = tac_tmpl * count
    body[off_ai - 0x2C : off_ai - 0x2C + len(ai)] = ai

    head = bytes(data[eo : eo + 0x0C])  # 6-word entry header, unchanged
    pairs = struct.pack(
        "<8I", count, off_slots, count, off_mult, count, off_tac, len(ai), off_ai
    )
    new_entry = head + pairs + bytes(body)

    out = bytearray(data[:eo])
    struct.pack_into("<I", out, 0x40, eo + end)  # end-of-file offset
    out += new_entry
    return bytes(out)


def patch_battle_payload(
    data: bytes,
    info: dict[int, CreatureInfo],
    swap_map: dict[int, int],
) -> tuple[bytes, dict] | None:
    """Apply team swaps, boney buffs, hard mode and AI boosts to one DPS file."""
    battle = parse_dps(data)
    if battle is None or not battle.entries:
        return None
    if battle.battle_id in TUTORIAL_BATTLES:
        return None

    stats = {"swapped": 0, "boney_buffed": 0, "ranks_boosted": 0, "ai_raised": 0}
    changed = False

    for entry_index, entry in enumerate(battle.entries):
        if entry.is_player_side:
            continue

        # deterministic per battle+entry, independent of processing order
        ai_rng = random.Random(SEED ^ (battle.battle_id * 0x9E3779B9) ^ entry_index)

        # smarter AI: deal a proven elite quadruple (also replaces the dummy
        # brains 16/17), max out aiLevel, and re-deal tactic classes with the
        # postgame supers' distribution
        entry_ai_changed = False
        if entry.ai_bytes and any(entry.ai_bytes):
            quad = ai_rng.choice(AI_PALETTE)
            new_ai = bytes(quad[i % 4] for i in range(len(entry.ai_bytes)))
            if new_ai != entry.ai_bytes:
                entry.ai_bytes = new_ai
                entry_ai_changed = True
        if entry.ai_level < AI_LEVEL:
            entry.ai_level = AI_LEVEL
            entry_ai_changed = True
        for slot in entry.slots:
            if slot.tac_offset and slot.tactic:
                new_class = ai_rng.choices(TACTIC_CLASS_CHOICES, TACTIC_CLASS_WEIGHTS)[0]
                if new_class != slot.tactic:
                    slot.tactic = new_class
                    entry_ai_changed = True
        if entry_ai_changed:
            stats["ai_raised"] += 1
            changed = True

        for slot in entry.slots:
            if not slot.vivo_id:
                continue
            creature = info.get(slot.vivo_id)
            is_boney = bool(creature and creature.boney)

            if is_boney:
                # never swap a Boneysaur -- make it scarier instead
                slot.rank = scaled_rank(slot.rank, boney=True)
                if slot.mult_offset and slot.mult == 0x1000:
                    slot.mult = BONEY_MULT
                stats["boney_buffed"] += 1
                changed = True
            else:
                target = swap_map.get(slot.vivo_id)
                if target and target != slot.vivo_id:
                    slot.vivo_id = target
                    stats["swapped"] += 1
                    changed = True
                slot.rank = scaled_rank(slot.rank)
                if slot.mult_offset and slot.mult == 0x1000:
                    slot.mult = ENEMY_MULT
                stats["ranks_boosted"] += 1
                changed = True

    if not changed:
        return None
    buf = bytearray(data)
    write_battle(buf, battle)
    return bytes(buf), stats


# ---------------------------------------------------------------------------
# AI table sharpening

_AI_TABLE_MAGICS = (b"AIC\x00", b"AIP\x00")


def sharpen_ai_weights(payload: bytes, scale: int = AI_WEIGHT_SCALE) -> tuple[bytes, int]:
    """Multiply every signed weight in an AIC/AIP scoring table by `scale`.

    Rows are lists of (u16 conditionId, s16 weight) pairs the AI sums when
    scoring a candidate action. A uniform scale preserves every ratio and
    preference ordering exactly -- what it changes is the margin between the
    best-scoring action and the runners-up, so any randomness the engine
    mixes into the decision flips it far less often. Values are clamped to
    s16, but the retail range (+-9999) never clips at x3.

    Returns (patched payload, weights scaled). Size-preserving.
    """
    if payload[:4] not in _AI_TABLE_MAGICS:
        raise ValueError("not an AIC/AIP table")
    data = bytearray(payload)
    count, indices_off = struct.unpack_from("<II", data, 4)
    offsets = struct.unpack_from(f"<{count}I", data, indices_off)
    scaled = 0
    for off in offsets:
        pair_count, data_off = struct.unpack_from("<II", data, off)
        for j in range(pair_count):
            wo = off + data_off + j * 4 + 2
            weight = struct.unpack_from("<h", data, wo)[0]
            if weight:
                new = max(-32768, min(32767, weight * scale))
                struct.pack_into("<h", data, wo, new)
                scaled += 1
    return bytes(data), scaled


# ---------------------------------------------------------------------------
# dig pools: the kaseki-record tables the game rolls when you dig (map/m/*)


def diggable_pool(info: dict[int, CreatureInfo]) -> list[int]:
    """Vivosaurs safe to place in dig pools: normal (non-boney, non-boss)
    forms, the same set proven safe as enemy-team members."""
    return sorted(i for i, c in info.items() if i <= SWAPPABLE_MAX_INDEX and not c.boney)


# Early-game dig maps (Ribular Island 3xxx + the first zones of the other
# islands): surplus body/arm/leg records here become HEAD (skull) rocks so
# new players revive vivosaurs quickly.
def _is_early_map(map_id: str) -> bool:
    try:
        n = int(map_id)
    except ValueError:
        return False
    return 3000 <= n <= 3999 or 4000 <= n <= 4003 or 5000 <= n <= 5003


TARGET_SPECIES_PER_ZONE = 24  # distinct species spread across each big zone


# Species run lengths tried when a rewritten map outgrows its retail ROM
# slot: 1 = pure round-robin (maximum variety, maximum entropy); longer runs
# repeat each species for N consecutive records, which compresses far
# better while keeping the same species set and a near-even spread.
_RUN_LENGTHS = (1, 2, 3, 4, 6, 8, 12, 16)


def _assign_zone_records(
    buffer: bytearray,
    records: list,
    vanilla_ids: list[int],
    subset: list[int],
    early: bool,
    kaseki,
    species_parts: dict[int, set[int]],
    info: dict[int, CreatureInfo],
    run: int,
) -> dict:
    """Deal `subset` species across one zone's dig records (round-robin in
    runs of `run`), writing into `buffer`. Returns the zone's stats.

    `vanilla_ids` is the records' retail kaseki ids, snapshotted before any
    attempt: write_record_kaseki mutates record.kaseki_id, so on a fit retry
    the records themselves carry the previous attempt's ids."""
    before: set[str] = set()
    after: set[str] = set()
    assigned: set[int] = set()
    rewritten = heads_added = 0
    cursor = 0
    skull_flip = 0

    for r, vanilla_id in zip(records, vanilla_ids):
        vp = kaseki.vivo_part.get(vanilla_id)
        if vp is None:
            continue  # special rock -- leave alone
        old_vivo, part = vp
        before.add(info[old_vivo].name)

        target_part = part
        if early and part != 1:
            skull_flip += 1
            if skull_flip % 2 == 0:  # ~half the surplus parts -> skull
                target_part = 1
                heads_added += 1

        # next species in the run sequence that has this part and isn't
        # the vanilla species at this record
        new_vivo = None
        for _ in range(len(subset) * run):
            cand = subset[(cursor // run) % len(subset)]
            cursor += 1
            if target_part in species_parts.get(cand, ()) and cand != old_vivo:
                new_vivo = cand
                break
        if new_vivo is None:
            after.add(info[old_vivo].name)
            continue

        after.add(info[new_vivo].name)
        assigned.add(new_vivo)
        new_rock = kaseki.rock_of.get((new_vivo, target_part))
        if new_rock is not None and new_rock != vanilla_id:
            write_record_kaseki(buffer, r, new_rock)
            rewritten += 1

    return {
        "before": before,
        "after": after,
        "assigned": assigned,
        "rewritten": rewritten,
        "heads_added": heads_added,
    }


def build_dig_pool_shuffle(
    map_payloads: dict[str, bytes],
    kaseki_payload: bytes,
    info: dict[int, CreatureInfo],
    seed: int = SEED,
    fits=None,
) -> tuple[dict[str, bytes], dict]:
    """Rebuild every dig site's pool for maximum in-hand variety.

    Vanilla concentrates each site on a few high-frequency species (Treasure
    Lake is ~40% Raja/Thalasso), so you dig the same one or two creatures
    over and over. A global species swap keeps that concentration. Instead,
    each site is given its own subset of the roster and those species are
    spread *evenly* across the site's dig records -- so no single creature
    dominates and every zone is a fresh mix.

      * per-zone subset: distinct species chosen per site (>= the vanilla
        count, up to ~24), so zones differ from each other and from vanilla,
      * even spread: records are round-robin assigned, flattening dig odds,
      * freshness: no record keeps the vanilla species that was there,
      * coverage: every vanilla-diggable species is dealt to at least one
        zone first, so nothing becomes unobtainable,
      * skull priority: in early zones ~half the surplus body/arm/leg records
        are turned into head (skull) rocks for fast early revivals,
      * jewels / droppings / dark rocks are left untouched.

    `fits(map_id, payload) -> bool` probes whether a rewritten map still
    compresses into its retail ROM slot. When it doesn't, the zone is
    re-dealt with progressively longer species runs (_RUN_LENGTHS); a zone
    that never fits is left retail. Relocating an oversized map instead is
    NOT an option: files moved out of their retail FAT slot fail to load on
    real DS hardware (black-screen hang, found in playtesting 2026-07-12).
    """
    kaseki = build_kaseki_index(kaseki_payload, set(info))
    species_rocks = set(kaseki.vivo_part)

    # records per map + which parts each species has a rock for
    per_map_records: dict[str, list] = {}
    for map_id, payload in map_payloads.items():
        records = find_dig_records(payload, kaseki.valid_ids)
        records += find_isolated_records(payload, kaseki.valid_ids, species_rocks)
        if records:
            per_map_records[map_id] = records

    species_parts: dict[int, set[int]] = {}
    for (vivo, part) in kaseki.rock_of:
        species_parts.setdefault(vivo, set()).add(part)

    diggable = sorted(
        {kaseki.vivo_part[r.kaseki_id][0]
         for recs in per_map_records.values() for r in recs
         if r.kaseki_id in kaseki.vivo_part}
    )
    full_species = [v for v in diggable if species_parts.get(v) == {1, 2, 3, 4}]

    rng = random.Random(seed ^ 0x5A5A5A5A)
    map_ids = sorted(per_map_records)

    # 1. coverage pass: deal every diggable species to a zone (round-robin over
    #    zones large enough to host it), so nothing is lost.
    zone_subset: dict[str, list[int]] = {m: [] for m in map_ids}
    zone_capacity = {m: len(per_map_records[m]) for m in map_ids}
    deal = diggable[:]
    rng.shuffle(deal)
    hosts = [m for m in map_ids if zone_capacity[m] >= 1]
    for i, vivo in enumerate(deal):
        zone_subset[hosts[i % len(hosts)]].append(vivo)

    # 2. top each zone up to its target size with extra full-part species
    for m in map_ids:
        want = min(max(TARGET_SPECIES_PER_ZONE, len(zone_subset[m])), zone_capacity[m])
        have = set(zone_subset[m])
        extras = [v for v in full_species if v not in have]
        rng.shuffle(extras)
        for v in extras:
            if len(zone_subset[m]) >= want:
                break
            zone_subset[m].append(v)
            have.add(v)

    # 3. assign records: even round-robin, fresh, with early-zone skull
    #    priority -- re-dealt in longer species runs when the zone doesn't
    #    compress back into its ROM slot (see the docstring)
    buffers = {mm: bytearray(p) for mm, p in map_payloads.items()}
    per_map_pools: dict[str, dict] = {}
    rewritten = heads_added = 0
    assigned_species: set[int] = set()
    unfit_zones: list[str] = []

    for map_id in map_ids:
        records = per_map_records[map_id]
        vanilla_ids = [r.kaseki_id for r in records]  # before any attempt mutates them
        early = _is_early_map(map_id)
        subset = zone_subset[map_id]
        rng.shuffle(subset)  # once per zone, so retries only change the run

        result = None
        used_run = 1
        for run in _RUN_LENGTHS:
            buffer = bytearray(map_payloads[map_id])
            attempt = _assign_zone_records(
                buffer, records, vanilla_ids, subset, early, kaseki, species_parts, info, run
            )
            if not attempt["rewritten"] or fits is None or fits(map_id, bytes(buffer)):
                result = (buffer, attempt)
                used_run = run
                break
        if result is None:
            # never fit: keep the zone retail rather than relocate the file
            unfit_zones.append(map_id)
            vanilla = sorted(
                {info[kaseki.vivo_part[k][0]].name for k in vanilla_ids if k in kaseki.vivo_part}
            )
            per_map_pools[map_id] = {"before": vanilla, "after": vanilla}
            continue

        buffer, attempt = result
        buffers[map_id] = buffer
        rewritten += attempt["rewritten"]
        heads_added += attempt["heads_added"]
        assigned_species |= attempt["assigned"]
        per_map_pools[map_id] = {
            "before": sorted(attempt["before"]),
            "after": sorted(attempt["after"]),
        }
        if used_run > 1:
            per_map_pools[map_id]["run"] = used_run

    report = {
        "dig_records_rewritten": rewritten,
        "skull_records_added": heads_added,
        "species_relocated": len(diggable),
        "species_diggable": len(assigned_species),
        "avg_species_per_zone": round(
            sum(len(p["after"]) for p in per_map_pools.values()) / max(len(per_map_pools), 1), 1
        ),
        "maps_changed": sum(1 for p in per_map_pools.values() if p["before"] != p["after"]),
        "zones_kept_retail": unfit_zones,
        "pools": per_map_pools,
    }
    return {m: bytes(b) for m, b in buffers.items()}, report


# ---------------------------------------------------------------------------
# story text

# file (without .dmg.json) -> {message index: replacement}
# NOTE: msg_movie_jimaku (subtitles over the FMV cutscenes) is deliberately
# NOT edited -- replacing those timed strings caused in-game crashes.
TEXT_EDITS: dict[str, dict[int, str]] = {
    # Opening scene: meeting Joe, the rampaging Allosaurus.
    "msg_0012": {
        129: "Joe\nYep, that's me. Surprised you know\nmy handle, kid.\n$f\nMost folks know me by my full\nname... but we'll get to that.",
        141: "Todd\nIt must be that rotten banana I ate\nthis morning. ...Yeah. That's it.\nThat is DEFINITELY the whole story.\nOooooooh...",
        152: "Joe\nSo that's all she wrote. Now dive in\nand pick yerself a vivosaur!\n$f\nAnd remember, small fry: it ain't the\nsize of the medal that matters...\nit's how ya throw it.",
    },
    # After the tutorial battle: Joe introduces himself for real.
    "msg_0013": {
        163: "Joe\nNice job, small fry! You did real\ngood. That's what she said.",
        170: "Joe\nAw, shucks. Where are my manners?\nThe name's Joe...\n$f\nJoe Momma!\n$f\n...Ha! Just funnin' ya, small fry.\nIt's $c1Joe Wildwest$c0. Reckon ya\nknew that already.",
        172: "Todd\nI'm $c1Todd$c0, and $c1$p $c0is my best\nfriend. We always cheer for you\non TV, $c1Joe$c0!\n$f\nOh, and you're playing $c2Fossil\nFighters: Elite Champions$c0, by\n$c1RuntimeAlex$c0!\n$f\nFrom the twisted genius who brought\nyou $c2Bonewake$c0!",
        175: "Joe\nAw, shucks. You small fries are\ngonna make me blush.\n$f\nBut y'all oughta aim a mite higher\nthan me.\n$f\nAsk yer momma about aimin' high.\nShe's got... experience. Heh.",
    },
    # Joanie / Madame Pooch / Todd-the-hopeless-wingman scene.
    "msg_0081": {
        4110: "Joanie\nIt is a lovely bowl, no?\n$f\nIt is big and round and I cannot\nstop touching it.\n$f\nZis is normal, no? Do not answer.",
        4133: "Todd\nShe is SOOOO CUTE!\n$f\nOK. Play it cool. I am going to be\nSO normal about this.",
        4135: "Todd\nHey, are you having trouble?\n...Because I happen to be an expert\nin big round things. It's a gift.",
        4145: "Todd\nDude, come on! You're supposed to\nbe my wingman here!\n$f\nHelp me out and I swear I'll name\nmy firstborn after you.",
        4150: "Todd\nBig and round... Hey! That sounds\nlike the bowl $c1Joanie $c0found!\n$f\n...I was picturing something WAY\ndifferent. Don't look at me like that.",
        4171: "Todd\n...You want us to battle your dog?\n$f\nLady, I've been rejected plenty of\ntimes, but never pre-emptively\nby a poodle.",
        4172: "Joanie\nAh, no. I have not said zis\ncorrectly. You will make ze Fossil\nBattle with me, $c1Joanie$c0.\n$f\nZe dog, she is ze manager.\nZe union, it is very strict.",
        4184: "Joanie\nOui! Then let us make with ze\nbattling of fossils!\n$f\nLoser buys ze baguettes!",
        4192: "Todd\nShe's got to be thankful, right?\nMaybe she'll even like me!\n$f\nStatistically, SOMEBODY has to.\nHeh heh heh...",
    },
    # Ribular Island signboard.
    "msg_0350": {
        18223: "Welcome to Ribular Island!\nWhere everybody digs everybody!",
    },
    # BB Brigade kidnapping caper: sneaking into the hideout.
    "msg_0082": {
        4200: "Todd\nHey! Hey, cute girl! ...Hello?\n$f\n...That's weird. Where'd she go?\n$f\nGirls do that around me a lot.\nIt's called mystique.",
        4207: "Todd\nWah! It's the BareBones Brigade!\nWh-what do we do?!\n$f\nI'm too young and gorgeous\nto die!",
        4208: "Frankie Bones\nWhew! Fruit is a lot heavier than\nI thought. I'm covered in sweat.\n$f\nDon't make it weird.",
        4213: "Todd\nNice work, $c1$p$c0! Now let's go\nhelp that cutie!\n$f\nOperation Boyfriend Material\nis a go.",
    },
    # Inside the hideout: pampered hostages and Cole the hipster commander.
    "msg_0083": {
        4305: "Paulie Bones\nOf course, ma'am! Feast your eyes\non the BB Brigade Shuffle!\n$f\nAnd a-one, and a-two...\n$f\n(Please don't tell the Don\nabout this.)",
        4313: "Todd\nThey're being nice to girls so they\nlose interest in the Cup?\n$f\nThat's just diabolical!\n$f\n...And honestly? Kind of a\ngreat date.",
        4321: "Todd\nB-but I'm not scared! N-no sir!\nNot me!\n$f\n...Hold my hand anyway.\nFor YOUR sake, obviously.",
        4329: "Todd\nWhere are you going, $c1$p$c0?\n$f\nWe have to rescue the cute girl so\nshe falls head over heels for me!\n$f\nThat's just science.",
        4336: "Cole\n...Yep. Pretty slick, huh? Do you\nlike the glasses?\n$f\nThey're non-prescription.\nFunction is a prison, bro.",
        4337: "Todd\nUgh! He's a hipster!\n$f\nNow I understand why the other\nBB Brigade goons are scared\nof him.\n$f\nHe probably reviews juice bars.",
        4340: "Cole\nSo why don't you shake a leg and\nscram, yeah?\n$f\nOtherwise I'll feed you to my\nboneysaurs. They're free-range.\nVery artisanal.",
        4343: "Todd\nIs that like a skeleton vivosaur?\n...Like a dinosaur g-g-ghost?!\n$f\nI want my momma! And NOT\nJoe's! MY momma!",
        4344: "Todd\nOoooooooh! Ooooh, my stomaaaaach!\nWhy did I eat those oysters I\nfound in the swimming pool?\n$f\n...Urp! I regret my whole life!\nAvenge me, $c1$p$c0!",
        4348: "Cole\nWhat?! N-no! This isn't happening!\n$f\nHow could I be beaten by someone\nso terminally unhip?\n$f\nI was into losing before it was\ncool... wait. WAIT.",
        4361: "Pauleen\nPffft! The BareBones Brigade is no\nmatch for a beautiful teen idol\nlike me!\n$f\n(I hid in a barrel. A glamorous\nbarrel. Limited edition.)",
        4370: "Todd\nMan, $c1Pauleen $c0is so weird! It's like\nshe's a different person once that\nmask is on.\n$f\nAnyway. I'm still gonna\nmarry her.",
    },
    # Jungle Labyrinth fake-monster caper with Pauleen.
    "msg_0043": {
        2303: "Pauleen\nI'm actually excited to see what\nthis monster looks like.\n$f\n...And I KNOW it's excited to\nsee me. Everybody is.\nIt's exhausting.",
        2306: "Pauleen\nPrepare to meet your doom at the\nhands of $c1Pauleen$c0, the most\nbeautiful Fighter in the land!\n$f\nMy hands are also very soft.\nDoesn't matter! DOOM!",
        2333: "Todd\nWell if you don't want to be called\na monster, you shouldn't wear a\nmask! Why don't you take it off?\n$f\nUnless you're, like, forty under\nthere. Then keep it on.",
        2336: "Pauleen\nHow dare you! I'm beautiful!\nAnd young! And...and beautiful!\n$f\nI wear this mask for personal\nreasons! Sexy, mysterious,\npersonal reasons!",
        2337: "Todd\nWhat kind of weirdo wears a mask\nfor personal reasons?\n$f\n...Is it me? Am I the reason?\nBe honest.",
    },
}
