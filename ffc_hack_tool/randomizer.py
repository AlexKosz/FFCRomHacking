"""Randomizer for workspace (carbonizer-unpacked) projects.

Fossil locations are randomized through etc/kaseki_defs dig-site
assignments and battle teams through the battle_param DPS files. The old
implementation guessed at spawn structures inside map binaries, which
matched unrelated data and risked corrupting maps.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .formats.dps_format import parse_dps, write_battle
from .formats.map_spawn import build_kaseki_index, find_dig_records, write_record_kaseki
from .presets.elite import SWAPPABLE_MAX_INDEX, TUTORIAL_BATTLES, load_creature_info


@dataclass
class RandomizerOptions:
    enabled: bool = False
    seed: int = 0
    randomize_fossil_locations: bool = True
    randomize_battles: bool = True
    mono_spawn: bool = False
    preserve_starters: bool = True


def _randomize_fossil_sites(rom_dir: Path, creatures: dict, rng: random.Random, mono: bool) -> int:
    """Shuffle which species each dig site's rock records hand out.

    Standard mode deranges the diggable species (every species relocates,
    nothing becomes unobtainable). Mono mode collapses each site's pool to
    one random species per site.
    """
    map_dir = rom_dir / "map" / "m"
    kaseki_path = rom_dir / "etc" / "kaseki_defs"
    if not map_dir.exists() or not kaseki_path.exists():
        return 0
    info = load_creature_info(creatures)
    kaseki = build_kaseki_index(kaseki_path.read_bytes(), set(info))

    map_records = {}
    species = set()
    for path in sorted(map_dir.iterdir()):
        if path.suffix or path.name.endswith(".metadata"):
            continue
        data = path.read_bytes()
        records = find_dig_records(data, kaseki.valid_ids)
        if records:
            map_records[path] = (bytearray(data), records)
            for r in records:
                if r.kaseki_id in kaseki.vivo_part:
                    species.add(kaseki.vivo_part[r.kaseki_id][0])

    ordered = sorted(species)
    if not ordered:
        return 0
    shuffled = ordered[:]
    rng.shuffle(shuffled)
    mapping = dict(zip(ordered, shuffled))

    changed = 0
    for path, (data, records) in map_records.items():
        site_mono = rng.choice(ordered) if mono else None
        touched = False
        for r in records:
            vp = kaseki.vivo_part.get(r.kaseki_id)
            if not vp:
                continue
            vivo, part = vp
            new_vivo = site_mono if mono else mapping.get(vivo, vivo)
            new_rock = kaseki.rock_of.get((new_vivo, part))
            if new_rock is not None and new_rock != r.kaseki_id:
                write_record_kaseki(data, r, new_rock)
                touched = True
                changed += 1
        if touched:
            path.write_bytes(bytes(data))
    return changed


def _randomize_battles(rom_dir: Path, creatures: dict, rng: random.Random, preserve_starters: bool) -> int:
    battle_dir = rom_dir / "battle_param"
    if not battle_dir.exists():
        return 0
    info = load_creature_info(creatures)
    pool = [i for i, c in info.items() if i <= SWAPPABLE_MAX_INDEX and not c.boney]
    if not pool:
        return 0
    changed = 0
    for file in sorted(battle_dir.iterdir()):
        if file.name.endswith(".metadata") or file.suffix:
            continue
        data = file.read_bytes()
        battle = parse_dps(data)
        if battle is None:
            continue
        if preserve_starters and battle.battle_id in TUTORIAL_BATTLES:
            continue
        touched = False
        for entry in battle.entries:
            if entry.is_player_side:
                continue
            for slot in entry.slots:
                if slot.vivo_id in info and slot.vivo_id <= SWAPPABLE_MAX_INDEX and not info[slot.vivo_id].boney:
                    slot.vivo_id = rng.choice(pool)
                    touched = True
        if touched:
            buf = bytearray(data)
            write_battle(buf, battle)
            file.write_bytes(bytes(buf))
            changed += 1
    return changed


def apply_randomizer(rom_dir: Path, creatures: dict, options: RandomizerOptions) -> None:
    rng = random.Random(options.seed or random.randint(1, 999_999_999))

    fossil_changes = battle_changes = 0
    if options.randomize_fossil_locations:
        fossil_changes = _randomize_fossil_sites(rom_dir, creatures, rng, options.mono_spawn)
    if options.randomize_battles:
        battle_changes = _randomize_battles(rom_dir, creatures, rng, options.preserve_starters)

    log_path = rom_dir.parent / "randomizer_log.json"
    log_path.write_text(
        json.dumps(
            {
                "seed": options.seed,
                "fossil_site_changes": fossil_changes,
                "battle_files_changed": battle_changes,
                "mono_spawn": options.mono_spawn,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
