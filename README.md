# Fossil Fighters Champions ROM Hack Studio

This repo holds two things: **Fossil Fighters Elite Champions**, a finished
overhaul of *Fossil Fighters: Champions* (Nintendo DS) by RuntimeAlex, and the
toolkit that built it.

If you only want to play the hack, the first two sections cover it.

## What Elite Champions changes

Champions has 204 vivosaurs, and a handful of them carry every serious team.
Most of the rest never leave the museum. Enemy trainers are easy, and digging
turns up the same few species for hours. Elite Champions changes all of that,
using the community competitive tier list to decide what counts as too strong
and too weak.

| | |
|---|---|
| **Roster rebalance** | 90 of the 204 vivosaurs change. The top of the tier list comes down, the bottom comes up, the middle is left alone. Biggest single change is a 23% buff. Each vivosaur is adjusted wherever its power actually comes from, so one that wins on a single cheap skill gets that skill repriced instead of its stats shaved. |
| **Skills repriced** | 153 skills had their FP cost, damage or status chance changed. Four of those are hand-written corrections to skills the community names directly: Cold Shout, Disorienting Kick, Berta Combo, Zanth Press. |
| **Enemy teams** | 1,613 enemy vivosaurs across 723 battles swapped for different picks of the same element and similar strength, so routes no longer play out the way they did in vanilla. |
| **Harder battles** | Enemy ranks follow a curve rather than a flat bonus. Rank 3 becomes 6, 5 becomes 9, 10 becomes 16, and anything from 13 up hits the cap of 20. Every non-tutorial enemy also gets a ×1.09 stat boost. Early cups barely change. Late-game trainers get a lot harder. |
| **Boneysaurs** | B-Rex, B-Brachio, B-Lambeo, B-Tricera, B-Ptera, B-Jara, B-Plesio and Salada are never swapped out. They get one extra rank on top of the curve and a ×1.20 stat boost instead. |
| **Smarter AI** | Every enemy runs a stronger setup than anything in vanilla, postgame included: one of the late-game tactic loadouts dealt per battle, the final-boss AI level, and wider decision margins so the AI stops losing turns to coin-flips. See [docs/AI_SYSTEM.md](docs/AI_SYSTEM.md). |
| **Dig site overhaul** | All 41 dig zones are rebuilt from their own slice of the roster and spread evenly across that zone's rocks. In vanilla one zone is 77% a single species; afterwards the worst case anywhere is 8%. Big zones mix around 23 species, no rock keeps its vanilla species, and all 130 diggable species stay obtainable. Jewels, droppings and dark rocks are untouched. |
| **Early skull priority** | In the Ribular sites and the opening zones of the other islands, about half the surplus body/arm/leg rocks become head (skull) rocks. Early-zone skull share goes from 27% to 64%, so your first digs revive new vivosaurs quickly while parts still drop. |
| **Elemental resistance fixed** | Retail Champions ignores elemental disadvantage; attacking into a bad matchup does full damage. Elite restores the first game's ×0.75, so matchups run advantage ×1.5, neutral ×1.0, disadvantage ×0.75 on every attack. Abilities are untouched. See [docs/ELEMENT_FIX.md](docs/ELEMENT_FIX.md). |
| **Story rewrite** | 38 rewritten lines across 7 dialogue files: Joe "Joe Momma" Wildwest's intro, Todd the hopeless wingman, Joanie and Madame Pooch, Cole the hipster commander, Pauleen's glamorous barrel, and the creator credits. |
| **DS menu title** | "Fossil Fighters / Elite Champions / by RuntimeAlex". |

Tutorial battles are untouched, so the opening still plays correctly.

Every change is published with its reasoning at
[runtimerelics.com/elite-champions/docs](https://runtimerelics.com/elite-champions/docs),
including why each vivosaur's numbers moved and where the automatic pass was
overruled by hand.

## How to play it

You need your own legally dumped copy of *Fossil Fighters: Champions (USA)*.
The hack ships as a patch file describing the differences, which gets applied
to your dump in the browser. Your ROM never leaves your machine, and no
Nintendo data is hosted anywhere.

```bash
python scripts/serve_patcher.py       # -> http://127.0.0.1:8080/
```

Drop in your `.nds`. The page checks it is the right game and an undamaged
dump, applies the patch, and hands back
`Fossil Fighters Elite Champions.nds`.

### If your dump is rejected

Champions is a DSi-enhanced cartridge, so a clean dump ends with a region of
DSi-only data. Dumpers that only understand original DS carts can't read that
region, and fill it with a repeated junk block instead. Those dumps (usually
tagged `[b]`) have perfect game data and a damaged tail, so they fail a
whole-file checksum even though nothing the hack touches is affected.

The patcher recognises this and offers a salvage build. It patches your dump,
clears the junk tail back to blank padding, and verifies the result. That
build plays anywhere an original DS game does, but the DSi region is gone: it
will not boot in DSi mode, and its checksum is not the official one.
Re-dumping with a DSi-capable dumper (GodMode9i) is still the better fix.

---

# For developers

Everything below is about the toolkit rather than the hack.

**Requirements:** Python 3.11+, `pip install -r requirements.txt` (ndspy,
flask), your own Champions `.nds` in the repo root, plus the
carbonizer-unpacked folder next to it.

## Building the hack

```bash
python scripts/build_elite_champions.py
```

Output: `projects/elite-champions/Fossil Fighters Elite Champions.nds`, with a
full change log in `build_report.json` next to it.

## The GUI studio

```bash
python -m ffc_hack_tool gui        # or run_studio.bat
```

Open http://127.0.0.1:8765. Tabs:

- **Vivosaurs.** Stats, element, range, LP and skill assignments.
- **Moves.** Every skill: FP cost and damage per hit (multi-hit combos
  supported, with the displayed total kept in sync) plus status chance. Shows
  which vivosaurs know each skill. A skill's element comes from its owner, so
  edit that on the Vivosaurs tab.
- **Dig Sites.** Every rock in every map, individually editable. Pick the
  vivosaur and the body part per rock, with per-species spawn percentages and
  per-zone grouping. Jewels and droppings are shown locked.
- **Battles.** Every enemy team slot by slot: vivosaur, rank, stat multiplier,
  tactic class and the four AI tactic ids, with a searchable index of every
  trainer. Edits are validated against documented-safe ranges.
- **Text.** Every string in the game, with live search across all 193 archives.
- **Randomizer.** Seeded fossil-site shuffle and element-preserving enemy team
  shuffle.
- **Hard Mode.** Rank and AI boosts for all non-tutorial battles.
- **Bug fixes.** The elemental-resistance fix as a toggle.

GUI builds and the Elite Champions script share the same pipeline, so both
take seconds and preserve the original ROM layout.

## How the balance pass works

The full reasoning is in the module docstrings. Start with
[`presets/meta.py`](ffc_hack_tool/presets/meta.py), then
[`presets/elite.py`](ffc_hack_tool/presets/elite.py).

A vivosaur's power comes from five things: stats, skills, crit rate, support
effects, and its ability. Earlier versions of this hack could only edit stats,
so the changes often missed the point. Nerfing Sopteryx's stat block does
nothing, because Sopteryx isn't strong on stats. It's strong because it lands
a guaranteed confuse every turn.

The current pass scores four of those five on one scale, works out how much of
a given vivosaur's power each one supplies, and makes the change there.
Abilities are still left alone.

Two data files drive it, and neither needs Python to edit:

- [`scripts/tier_list.json`](scripts/tier_list.json) is the community
  competitive tier list. It's the only thing that decides how much a vivosaur
  should move.
- [`scripts/balance_overrides.json`](scripts/balance_overrides.json) holds
  hand-written corrections for cases the automatic pass can't see, like a
  skill's real cost or an ability that switches a vivosaur off. Every entry
  needs a written reason; the loader raises if one is missing.

Guard rails: an intended change under 5% is skipped rather than moving a stat
by a point or two, accuracy is never reduced, no buff can push a stat past the
highest value in the retail game, and no single category moves more than 34%.

`presets/tier_balance.py` is the superseded v2 pass, kept for reference only.
Nothing reads its tier sets.

## How the ROM is patched

Nothing is repacked. Each file is pulled out of the ROM, decompressed, edited
without changing its size, re-encoded with the same compression the retail
file used, and written back to the slot it came from.

An earlier build did repack. About 9,800 files moved off their retail
addresses, every replaced file was re-wrapped uncompressed, and the DSi region
was dropped. DeSmuME ran it fine. melonDS, which emulates the cartridge
hardware much more strictly, crashed during the opening movie. A file that
outgrows its slot and gets relocated will also black-screen on real DS
hardware the first time the game reads it.

The current build patches 778 files and relocates none of them. Every one is
decoded back out of the finished image and byte-compared before the build
reports success. The shareable patch is 0.6 MB, down from about 20 MB.

That constraint shows up in the balance code twice. Scaled LP values snap to
multiples of 5, because the repetition is what lets the creature table
compress back into its original slot. And any dig zone whose rebuilt table
would overflow gets re-dealt with longer species runs, or kept retail. The
build fails rather than ship a relocation.

### Bugs this pipeline exists to prevent

Earlier patchers wrote bytes into structured binaries without parsing them
first. Each of these crashed the game, and between them they're why every
patch now goes through `ffc_hack_tool/formats/`:

1. The `etc/ai_*` files had nearly every byte incremented, which destroyed the
   offset tables the game reads when battle AI loads.
2. A battle "level boost" rewrote 32-bit words that are actually count and
   pointer fields in the DPS format.
3. A creature health patch treated a vivosaur-relative offset as
   file-absolute, corrupting neighbouring vivosaurs. It also misread the
   header, so most of the roster was never patched at all.
4. A "fossil spawn" editor matched false-positive structures inside map
   binaries. The real dig assignments live in `etc/kaseki_defs`.

## Shipping an update

```bash
python scripts/build_elite_champions.py   # rebuild the hack ROM
python scripts/make_patch.py              # regenerate webpatcher/patches/*
python scripts/export_site_docs.py        # refresh the site's docs data
python scripts/export_battle_docs.py      #   (per-battle diffs)
python scripts/export_dig_docs.py         #   (per-part dig %s)
# then copy webpatcher/patches/* to RuntimeRelics/public/patches/
```

`make_patch.py` writes a fresh self-verified `.bps` patch plus a
`manifest.json` holding the version, checksums and output name. The page reads
that manifest on every load, so replacing those two files is the update. The
`webpatcher/` folder is fully static and will host anywhere.

## Reference documentation

- [docs/TOOL_INTERNALS.md](docs/TOOL_INTERNALS.md) covers each module, build
  pipeline and verification step.
- [docs/AI_SYSTEM.md](docs/AI_SYSTEM.md) covers how battle AI is coded and what
  "smarter AI" actually changes.
- [docs/FORMATS.md](docs/FORMATS.md) is the reverse-engineered file formats.
- [docs/ELEMENT_FIX.md](docs/ELEMENT_FIX.md) is the elemental resistance bug
  and its fix.

### Champions-specific findings

- `battle_param/battle_param_defs_N` is a `DPS` file holding up to 3 fighter
  entries. Each has vivosaur slots (12 bytes: array index, rank, LP override),
  per-vivosaur stat multipliers (0x1000 = 1.0), per-vivosaur tactic classes
  (1–4), and 4 AI tactic IDs (1–17, indexing `etc/ai_tactics_defs`). An entry
  whose pre-battle message id is 0 is the player's side. See
  `formats/dps_format.py`.
- Battle files reference vivosaurs by 0-based position in the creature_defs
  array, not by the `_id` field, because 30 ids are duplicated between base
  forms and boss/super variants. Boneysaurs are indices 184–190, Salada 210,
  and Lord Tonzilla 192. Array index 0 is a dummy entry, which is what lets
  slot id 0 mean "empty". This was documented as 1-based for a while and it
  isn't; reading it that way shifts every enemy in the game by one creature.
- Six entries carry a sentinel LP curve that jumps to 913–920 at rank 13:
  indices 193–198, the boss/story duplicates of Pachrino, Dilopho, Shoni,
  T-Rex, Dimorph and Zino. That's scripted-fight data rather than a stat line,
  and the balance pass excludes it from every roster statistic.
- Dig pools live in the `map/m/*` `MAP` files as 8-byte records:
  `u16 paramA, u16 paramB, u16 zone, u16 kaseki id`. Each rock id resolves to
  a (vivosaur, part) pair via `etc/kaseki_defs`. Verified against gameplay:
  map 3000 decodes to the exact Treasure Lake pool. See
  `formats/map_spawn.py`. The FF1-style `ThingC` records also present in these
  maps do not drive digs in Champions.
- `etc/creature_defs` (`DCL`) has its vivosaur count at 0x20 and per-vivosaur
  health tables at vivosaur-relative offsets.
- `msg/*` are `DMG` string archives (`formats/dmg_format.py`, byte-exact
  round-trip).

## Credits

- Hack: **RuntimeAlex**, also the author of **Bonewake**
- [simonomi/carbonizer](https://github.com/simonomi/carbonizer) for ROM
  unpacking and format research
- [ff1-binary-formats](https://github.com/simonomi/ff1-binary-formats/wiki) and
  [jianmingyong/Fossil-Fighters-Tool](https://github.com/jianmingyong/Fossil-Fighters-Tool)
  for compression references

## Legal

Only use this tool with ROM dumps you own. Do not distribute copyrighted ROM
files.
