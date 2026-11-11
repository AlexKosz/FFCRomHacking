"""Five-pillar meta rebalance for Fossil Fighters Elite Champions.

Lowering a vivosaur's stats is the obvious way to make it weaker, and it
usually doesn't work.

Sopteryx is one of the best vivosaurs in the game and one of the most
fragile. Its stats are already terrible, so cutting them further changes
nothing, because Sopteryx doesn't win on stats. It wins by firing a
guaranteed confuse every turn. Cryo has the same problem for a different
reason: it's top tier because of one skill that costs almost nothing. Edit
either stat block and you've changed a number in a menu, not a battle.

So this module works out why a vivosaur is good before deciding what to
change. It measures four things that can each make one strong:

    stats    attack / defense / accuracy / speed / health
    kit      its four skills: cost, effect, and what they inflict
    crit     how often it lands a critical hit
    support  buffs it gives your team, debuffs it lands on theirs

It puts those on one comparable scale, works out how much of this
particular vivosaur's power comes from each, and makes the change there. A
vivosaur carried by one cheap skill gets that skill made expensive. One
that's a wall of big numbers gets the numbers cut. One that wins by making
its teammates better gets that trimmed.

The fifth thing, its ability, is left alone, because abilities are
hand-written game logic rather than numbers. Where an ability is the real
problem, the fix goes in scripts/balance_overrides.json by hand instead.
Hopter is the example.

Nothing here decides a vivosaur's tier. That comes from the community list
in scripts/tier_list.json. This only decides where a tier's change lands.

Longer version of the same reasoning:

The stat-only pass (see `elite.compute_rebalance`) could only ever move one
of the five things that decide whether a vivosaur is good, and usually not
the one that mattered. The community placement writeups say so directly:
Sopteryx is S+ while being "one of the most vile FRAIL vivosaurs ever
designed", Pacro's "damage may be pitiful", Cryo is S because of one skill
("Cold Shout. Click Cold Shout."), and Zanth's "150 cost press does about 25
more base damage than it should". Nerfing those stat blocks changes nothing
about why any of them is strong.

So this module prices all five pillars in one comparable currency --

    stats    the stat block (attack/defense/accuracy/speed/HP)
    kit      the four skills: damage per FP, and status chance x severity
    crit     critRate
    support  supportEffectsForAlly / ForEnemy

-- works out how much of a vivosaur's power each pillar actually supplies,
and then spends the tier adjustment WHERE THE POWER IS. A vivosaur that is
strong because of a 100%-chance gold status on a 50 FP skill gets that skill
made expensive; a vivosaur that is strong because it is a statstick gets its
stat block trimmed. Each pillar's change is computed with the others already
priced in, so the pillars cannot double-count each other.

Nothing here decides a vivosaur's TIER -- that stays the community list in
scripts/tier_list.json. This module only decides where a tier's adjustment
should land.
"""

from __future__ import annotations

from typing import Any

import re

from ..formats.dal_format import Move
from . import elite

# ---------------------------------------------------------------------------
# pillar pricing

# Status severity, keyed by the move's effectId. The pairs are silver/gold
# versions of the same status and the HIGHER id is the gold one, confirmed
# against the community writeups three ways: Cryo's Cold Shout is effect 14
# at 100% and is described as "100% Gold Excite"; Sopteryx's Disorienting
# Kick is effect 12 at 100% and is described as a "100% gold confuse skill";
# Berta's effect 5 @60% and effect 11 @70% match its "60% Sleep and 70%
# Confusion" exactly.
#
# Sleep and Confuse are weighted hardest because they deny a turn outright --
# the writeups treat them as the game's defining resource ("Berta can pretty
# much fulfil the entire status budget on your team").
STATUS_WEIGHTS = {
    1: 0.0,                 # no status
    2: 1.0, 3: 1.7, 4: 1.0,  # poison  (silver / gold)
    5: 2.2, 6: 3.4,          # sleep
    7: 1.5, 8: 2.4,          # scare
    9: 1.1, 10: 1.8,         # enrage
    11: 2.2, 12: 3.4,        # confuse
    13: 1.3, 14: 2.1,        # excite
}

FP_REFERENCE = 150.0   # a "normal" skill cost; sets the efficiency scale
FP_FLOOR = 40.0        # stops a 10 FP utility move dividing by almost nothing
STATUS_POINT_VALUE = 26.0   # damage-points one full-chance silver status buys

# A team skill is real power but it is conditional on bringing the right
# ally, so it is priced at less than a personal skill. It is SCORED but never
# EDITED: team skills are shared across whole compatibility groups, so
# editing one silently rewrites a dozen unrelated vivosaurs.
TEAM_SKILL_WEIGHT = 0.5

# support_net runs about -308..+308. Shifting by this makes the support
# pillar a positive quantity, so a vivosaur whose ally support is a liability
# (T-Rex at -120) correctly scores LOW on this pillar rather than negative.
SUPPORT_OFFSET = 320.0

# How much of a vivosaur's power each pillar is assumed to carry, before its
# own numbers are taken into account. Kit is weighted highest because the
# writeups keep resolving to a single skill or FP cost.
POWER_WEIGHTS = {"stats": 0.32, "kit": 0.40, "crit": 0.08, "support": 0.20}

# Concentration of the adjustment onto the pillars that actually carry the
# power. 0 would spread every change evenly across all four pillars (which is
# how a stat-only pass fails); 1 sends it where the power is.
PILLAR_CONCENTRATION = 1.0
PILLAR_MAX_CHANGE = 0.34   # no single pillar may move more than this

# Quantization. Retail values are already on these grids -- every FP cost is
# a multiple of 5 (789 of 799 are multiples of 10), every status chance is a
# multiple of 5, and crit and support are almost entirely multiples of 5 --
# so snapping to them keeps edited files looking like retail data and keeps
# creature_defs compressible.
# FP moves on a 10 grid because that is the game's own design language (789
# of 799 retail costs are multiples of 10), and because etc/attack_defs is a
# compressed table with only 276 bytes of slack in its ROM slot -- a finer
# grid invents values that break the LZ back-references the file depends on.
# A curated override in balance_overrides.json can still name any value.
FP_STEP, FP_MIN_CHANGE = 10, 10
DAMAGE_MIN_CHANGE = 4
CHANCE_STEP, CHANCE_MIN_CHANGE = 5, 10
CRIT_STEP, CRIT_MIN_CHANGE = 5, 5
SUPPORT_STEP, SUPPORT_MIN_CHANGE = 5, 5

# Hard bounds, so no edit leaves the range the game's own data occupies.
FP_BOUNDS = (10, 900)
CHANCE_BOUNDS = (5, 100)
CRIT_BOUNDS = (5, 100)
SUPPORT_BOUND = 99

# Within the kit pillar, how a change is split between making a skill cost
# more and making it do less. FP is the primary lever: the writeups
# overwhelmingly describe power in terms of cost ("the cheapest spread attack
# in the game", "for only 50 FP", "its skills go up by about 50%").
KIT_FP_SHARE = 0.55
KIT_DAMAGE_SHARE = 0.25
KIT_STATUS_SHARE = 0.20

# Within a vivosaur's kit, the change concentrates on its BEST skills rather
# than being spread evenly over all four. The writeups are explicit that a
# kit is usually one skill and three passengers -- "Cold Shout. Click Cold
# Shout", "so much of its power budget in Cold Shout" -- so an even spread
# leaves the actual problem skill barely touched (it left Cold Shout, the
# single best skill in the game, completely unedited).
KIT_CONCENTRATION = 1.5


def _quantize(before: int, after: float, step: int, min_change: int,
              bounds: tuple[int, int] | None = None) -> int:
    """Snap to the grid, then drop back to `before` unless the move clears
    `min_change` -- the same no-trivial-edits rule the stat pass uses."""
    value = int(round(after / step)) * step
    if bounds:
        value = max(bounds[0], min(bounds[1], value))
    return before if abs(value - before) < min_change else value


# ---------------------------------------------------------------------------
# scores


# Utility that a damage-and-status metric is blind to. Without these a
# healer scores almost nothing -- Pacro, "the Strongest Healer in the game,
# perfectly capable of making entire teams worth of damage obsolete in a
# single move", priced out at a 0.13 kit share because Mother's Heal deals no
# damage and inflicts no status. Every pattern below is matched against the
# game's own skill description in text/text_attack_info, so the classifier is
# the game's text rather than a hand-listed set of move ids.
#
# Values are in the same damage-point currency as `move_value`.
UTILITY_PATTERNS: list[tuple[str, float]] = [
    (r"Eliminate all effects \(team\)", 60.0),  # team Rallying Cry
    (r"Eliminate all effects", 45.0),            # "the all important Rallying Cry"
    (r"Restore .* LP \(team\)", 70.0),
    (r"Recover .* LP \(team\)", 70.0),
    (r"Restore .* LP", 40.0),
    (r"Recover .* LP", 40.0),
    (r"Recover using ally LP", 35.0),            # Law of the Jungle
    (r"Greatly raise Attack", 40.0),
    (r"Raise Attack", 22.0),
    (r"Raise Defense", 22.0),
    (r"Transform", 50.0),
    (r"Equalize FP", 20.0),
    (r"Steal LP equal to damage", 12.0),
    (r"Use LP to inflict heavy damage", 20.0),
    (r"Rotate", 18.0),                           # rotation control
    (r"Inflict effects randomly", 25.0),
]
# Patterns whose number is part of the value.
UTILITY_SCALED: list[tuple[str, float]] = [
    (r"Steal (\d+) FP", 1 / 8.0),
    (r"Counter: (\d+)%", 0.35),
    (r"Evasion rate: (\d+)%", 0.40),
    (r"Infection: (\d+)%", 0.30),
]
# A move that hits more than one zone is worth a multiple of its damage --
# "having the cheapest spread attack in the game" is the first thing the
# writeups say about T-Rex.
SPREAD_PATTERNS: list[tuple[str, float]] = [
    (r"Attack AZ and SZ", 1.6),
    (r"Attack team randomly", 1.8),
]
# A team-wide status is far stronger than a single-target one.
TEAM_STATUS_MULTIPLIER = 1.7
TEAM_STATUS_RE = re.compile(
    r"Special: (Poison|Sleep|Scare|Enrage|Confuse|Excite): (\d+)% \(team\)"
)
# Silver-tier weight per status name, for the team-status text (which names
# the status instead of using an effectId).
STATUS_BY_NAME = {
    "Poison": 1.0, "Sleep": 2.2, "Scare": 1.5,
    "Enrage": 1.1, "Confuse": 2.2, "Excite": 1.3,
}


def move_value(move: Move, description: str = "") -> float:
    """What one skill is worth: damage, status and utility, per FP spent."""
    if not move.total:
        return 0.0
    fp = max(float(move.total.fp), FP_FLOOR)

    damage = float(move.total.damage)
    for pattern, multiplier in SPREAD_PATTERNS:
        if re.search(pattern, description):
            damage *= multiplier
            break

    status = (move.effect_chance / 100.0) * STATUS_WEIGHTS.get(move.effect_id, 0.0)
    worth = damage + status * STATUS_POINT_VALUE

    for name, chance in TEAM_STATUS_RE.findall(description):
        worth += (int(chance) / 100.0) * STATUS_BY_NAME.get(name, 1.0)             * STATUS_POINT_VALUE * TEAM_STATUS_MULTIPLIER
    for pattern, value in UTILITY_PATTERNS:
        if re.search(pattern, description):
            worth += value
            break
    for pattern, factor in UTILITY_SCALED:
        found = re.search(pattern, description)
        if found:
            worth += int(found.group(1)) * factor

    return worth * (FP_REFERENCE / fp)


def move_value_table(moves: list[Move], descriptions: list[str]) -> dict[int, float]:
    """Precomputed worth of every move, so scoring never re-parses text."""
    return {
        m.id: move_value(m, descriptions[m.id] if m.id < len(descriptions) else "")
        for m in moves
        if m.total
    }


def kit_score(entry: dict[str, Any], values: dict[int, float]) -> float:
    total = sum(values.get(sid, 0.0) for sid in entry.get("skillIDs", []))
    team = entry.get("teamSkillID", 0)
    if team:
        total += TEAM_SKILL_WEIGHT * values.get(team, 0.0)
    return total


def pillar_scores(entry: dict[str, Any], values: dict[int, float]) -> dict[str, float]:
    return {
        "stats": elite._power_score(entry),
        "kit": kit_score(entry, values),
        "crit": float(entry.get("critRate", 0)),
        "support": max(1.0, SUPPORT_OFFSET + elite.support_net(entry)),
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 1.0


# ---------------------------------------------------------------------------
# the plan


def compute_meta_plan(
    creatures: dict[str, Any],
    moves: list[Move],
    tier_map: dict[str, str],
    descriptions: list[str] | None = None,
) -> dict[str, Any]:
    """Decide, for every vivosaur, how its tier adjustment splits across the
    four pillars -- and turn that into concrete move / crit / support edits.

    Returns {"vivosaurs": {...}, "moves": {...}, "statAdjust": {name: frac}}.
    """
    info = elite.load_creature_info(creatures)
    vivos = creatures["vivosaurs"]
    overrides = elite.load_overrides()
    values = move_value_table(moves, descriptions or [])

    real = [c for c in info.values() if not elite.has_sentinel_hp(vivos[c.index])]
    scores = {c.index: pillar_scores(vivos[c.index], values) for c in real}
    medians = {
        pillar: _median([s[pillar] for s in scores.values()]) or 1.0
        for pillar in POWER_WEIGHTS
    }

    plan_v: dict[int, dict[str, Any]] = {}
    stat_adjust: dict[str, float] = {}
    # move id -> list of (fractional change wanted, weight) from its users
    move_votes: dict[int, list[tuple[float, float]]] = {}

    for c in real:
        entry = vivos[c.index]
        tier = tier_map.get(c.name, elite.UNLISTED_TIER)
        adjust = elite.TIER_ADJUST.get(tier, 0.0)
        override = overrides.get(c.name, {})
        if override.get("hold") or abs(adjust) < elite.ADJUST_DEADBAND:
            continue

        raw = scores[c.index]
        norm = {p: raw[p] / medians[p] for p in POWER_WEIGHTS}
        weighted = {p: POWER_WEIGHTS[p] * norm[p] for p in POWER_WEIGHTS}
        total = sum(weighted.values()) or 1.0
        share = {p: weighted[p] / total for p in POWER_WEIGHTS}

        # Spend the adjustment where the power is: a pillar's fractional
        # change is proportional to its share, normalised so the vivosaur's
        # total power moves by `adjust` overall.
        gain = {p: share[p] ** PILLAR_CONCENTRATION for p in share}
        denom = sum(share[p] * gain[p] for p in share) or 1.0
        frac = {
            p: max(-PILLAR_MAX_CHANGE, min(PILLAR_MAX_CHANGE, adjust * gain[p] / denom))
            for p in share
        }

        stat_adjust[c.name] = frac["stats"]

        # --- crit
        crit_before = int(entry.get("critRate", 0))
        crit_after = _quantize(
            crit_before, crit_before * (1.0 + frac["crit"]),
            CRIT_STEP, CRIT_MIN_CHANGE, CRIT_BOUNDS,
        )

        # --- support: work on the NET, additively. Scaling the raw values
        # would move a negative net the wrong way (making a drawback smaller
        # reads as a nerf but is actually a buff).
        net_before = elite.support_net(entry)
        support_after = _redistribute_support(entry, frac["support"])

        # --- kit: the change lands on the skills actually carrying the kit,
        # weighted by each skill's share of it. The team skill is scored but
        # never edited (see TEAM_SKILL_WEIGHT).
        skills = [sid for sid in entry.get("skillIDs", [])
                  if 0 <= sid < len(moves) and moves[sid].total]
        sk_value = {sid: values.get(sid, 0.0) for sid in skills}
        kit_total = sum(sk_value.values())
        if skills and kit_total > 0:
            sk_share = {sid: sk_value[sid] / kit_total for sid in skills}
            sk_gain = {sid: sk_share[sid] ** KIT_CONCENTRATION for sid in skills}
            sk_denom = sum(sk_share[sid] * sk_gain[sid] for sid in skills) or 1.0
            for sid in skills:
                move_votes.setdefault(sid, []).append(
                    (frac["kit"] * sk_gain[sid] / sk_denom, sk_share[sid] or 0.01)
                )
        else:
            for sid in skills:
                move_votes.setdefault(sid, []).append((frac["kit"], 1.0))

        plan_v[c.index] = {
            "name": c.name,
            "tier": tier,
            "adjust": round(adjust, 4),
            "shares": {p: round(share[p], 3) for p in share},
            "fractions": {p: round(frac[p], 4) for p in frac},
            "crit": {"before": crit_before, "after": crit_after},
            "support": support_after,
            "supportNet": {"before": net_before, "after": support_after["net"]},
            "skills": list(entry.get("skillIDs", [])),
        }

    move_edits = _plan_move_edits(moves, move_votes)
    return {"vivosaurs": plan_v, "moves": move_edits, "statAdjust": stat_adjust}


def _redistribute_support(entry: dict[str, Any], frac: float) -> dict[str, Any]:
    """Scale a vivosaur's support effects by the support pillar's fraction.

    The direction depends on whether the support is an ASSET or a LIABILITY.
    T-Rex's -30 to every ally stat is a drawback, so nerfing T-Rex means
    making it worse, not smaller -- hence the sign(net) term. Working
    multiplicatively on the slots (rather than additively on the net) also
    keeps the change proportional to the support a vivosaur actually has: an
    earlier additive version demanded a 33-point swing from Pacro, which owns
    30 points of support in total, and deleted its support effect outright.
    """
    keys = ("attack", "defense", "accuracy", "speed")
    ally = dict(entry.get("supportEffectsForAlly") or {})
    enemy = dict(entry.get("supportEffectsForEnemy") or {})
    net = elite.support_net(entry)
    if (not ally and not enemy) or net == 0:
        return {"ally": ally or None, "enemy": enemy or None, "net": net, "changed": False}

    scale = 1.0 + frac * (1.0 if net > 0 else -1.0)
    out_ally, out_enemy = dict(ally), dict(enemy)
    for side, source in (("ally", out_ally), ("enemy", out_enemy)):
        for key in keys:
            value = source.get(key, 0)
            if not value:
                continue
            source[key] = _quantize(value, value * scale, SUPPORT_STEP,
                                    SUPPORT_MIN_CHANGE, (-SUPPORT_BOUND, SUPPORT_BOUND))

    return {
        "ally": out_ally or None,
        "enemy": out_enemy or None,
        "net": sum(out_ally.values()) - sum(out_enemy.values()),
        "changed": out_ally != ally or out_enemy != enemy,
    }


def _plan_move_edits(
    moves: list[Move], votes: dict[int, list[tuple[float, float]]]
) -> dict[int, dict[str, Any]]:
    """Turn each move's users' wishes into one concrete edit.

    A move can be shared -- Law of the Jungle is on 28 vivosaurs -- so the
    edit is the usage-weighted MEAN of what its users wanted, never one
    user's figure applied to everyone else's skill.
    """
    edits: dict[int, dict[str, Any]] = {}
    for sid, entries in votes.items():
        move = moves[sid]
        if not move.total:
            continue
        total_w = sum(w for _, w in entries) or 1.0
        frac = sum(f * w for f, w in entries) / total_w
        if abs(frac) < 0.01:
            continue

        fp_before, dmg_before = move.total.fp, move.total.damage
        chance_before = move.effect_chance

        # A nerf makes a skill cost MORE, so FP moves against the fraction.
        fp_after = _quantize(
            fp_before, fp_before * (1.0 - frac * KIT_FP_SHARE),
            FP_STEP, FP_MIN_CHANGE, FP_BOUNDS,
        )
        # Zero-damage utility skills stay at zero -- their cost is the lever.
        dmg_after = dmg_before
        if dmg_before > 1:
            dmg_after = _quantize(
                dmg_before, dmg_before * (1.0 + frac * KIT_DAMAGE_SHARE),
                1, DAMAGE_MIN_CHANGE, (1, 255),
            )
        chance_after = chance_before
        if move.effect_id > 1 and chance_before:
            chance_after = _quantize(
                chance_before, chance_before * (1.0 + frac * KIT_STATUS_SHARE),
                CHANCE_STEP, CHANCE_MIN_CHANGE, CHANCE_BOUNDS,
            )

        edits[sid] = {
            "fraction": round(frac, 4),
            "users": len(entries),
            "fp": [fp_before, fp_after],
            "damage": [dmg_before, dmg_after],
            "chance": [chance_before, chance_after],
            "effectId": move.effect_id,
        }

    # Curated skill corrections win over the model, and may name a move the
    # model left alone entirely.
    for sid, spec in elite.load_move_overrides().items():
        if sid >= len(moves) or not moves[sid].total:
            continue
        move = moves[sid]
        edit = edits.get(sid) or {
            "fraction": 0.0, "users": 0,
            "fp": [move.total.fp, move.total.fp],
            "damage": [move.total.damage, move.total.damage],
            "chance": [move.effect_chance, move.effect_chance],
            "effectId": move.effect_id,
        }
        for field in ("fp", "damage", "chance"):
            if field in spec:
                edit[field] = [edit[field][0], int(spec[field])]
        edit["curated"] = spec["reason"]
        edits[sid] = edit

    return {
        sid: e for sid, e in edits.items()
        if (e["fp"][0], e["damage"][0], e["chance"][0])
        != (e["fp"][1], e["damage"][1], e["chance"][1])
    }


def apply_move_edits(data: bytes, moves: list[Move], edits: dict[int, dict[str, Any]]) -> bytes:
    """Write the planned move edits back into attack_defs, in place.

    The per-hit (fp, damage) pairs are the tiers that sum to the displayed
    total, so they are rescaled to keep summing to the new total -- otherwise
    the skill's displayed cost and its charged cost drift apart.
    """
    from ..formats.dal_format import write_move

    buf = bytearray(data)
    for sid, edit in edits.items():
        move = moves[sid]
        fp_before, fp_after = edit["fp"]
        dmg_before, dmg_after = edit["damage"]
        move.effect_chance = edit["chance"][1]

        for field, before, after in (("fp", fp_before, fp_after),
                                     ("damage", dmg_before, dmg_after)):
            if before == after or not move.hits:
                continue
            running = 0
            for i, hit in enumerate(move.hits):
                if i == len(move.hits) - 1:      # last tier absorbs rounding
                    value = after - running
                else:
                    value = int(round(getattr(hit, field) * after / before))
                    running += value
                setattr(hit, field, max(0, value))
        move.total.fp, move.total.damage = fp_after, dmg_after
        write_move(buf, move)
    return bytes(buf)


def apply_creature_edits(
    data: bytes, plan: dict[int, dict[str, Any]]
) -> tuple[bytes, int, int]:
    """Write crit rate and support effects into creature_defs, in place.

    Offsets come from formats/dcl_encode._encode_vivosaur: critRate at +0x12,
    and the ally/enemy support offsets at +0xA4 / +0xA8 in the fixed header.
    """
    import struct

    buf = bytearray(data)
    count = struct.unpack_from("<I", buf, 0x20)[0]
    offsets_offset = struct.unpack_from("<I", buf, 0x24)[0]
    offsets = struct.unpack_from(f"<{count}I", buf, offsets_offset)
    keys = ("attack", "defense", "accuracy", "speed")
    crit_changed = support_changed = 0

    for index, base in enumerate(offsets):
        item = plan.get(index)
        if not item or base == 0 or buf[base] == 0:
            continue

        crit_after = item["crit"]["after"]
        if crit_after != item["crit"]["before"]:
            buf[base + 0x12] = max(1, min(255, crit_after))
            crit_changed += 1

        support = item["support"]
        if support.get("changed"):
            ally_off, enemy_off = struct.unpack_from("<II", buf, base + 0xA4)
            for off, values in ((ally_off, support["ally"]), (enemy_off, support["enemy"])):
                if off and values:
                    struct.pack_into(
                        "<4b", buf, base + off,
                        *(max(-128, min(127, int(values[k]))) for k in keys),
                    )
            support_changed += 1

    return bytes(buf), crit_changed, support_changed
