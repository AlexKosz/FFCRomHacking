# FFC Hack Studio — how every piece works

Making a Champions hack takes four steps, and this toolkit is one tool per
step.

1. **Unpack.** Open the retail cartridge and decode its files into something
   editable. Done once per project.
2. **Edit.** Change stats, skills, dig sites, enemy teams or dialogue, either
   in the studio or from code.
3. **Build.** Put the edited files back into a copy of the cartridge without
   moving anything. A DS game hardcodes where its files live, and real
   hardware won't boot if they've shifted.
4. **Share.** Work out the difference between the original cartridge and the
   hacked one, and save only that difference as a patch file. Other people
   apply it to their own legally owned copy, so no game data is distributed.

The diagram below is those four steps. Everything after it is which module
does what.

A map of the whole toolkit: what each module does, how data flows from a
retail ROM to a playable hack, and why the build pipelines are shaped the
way they are. Format details live in [FORMATS.md](FORMATS.md); the battle
AI deep-dive lives in [AI_SYSTEM.md](AI_SYSTEM.md).

```
retail ROM ──carbonizer──> workspace (decoded files)          [once, per project]
workspace ──editors (GUI/API)──> edited workspace files       [any time]
workspace + retail ROM ──in-place injector──> hack ROM        [build]
hack ROM + retail ROM ──BPS encoder──> shareable .bps patch   [share]
```

## Package layout (`ffc_hack_tool/`)

### Entry points

* **`__main__.py`** — CLI: `python -m ffc_hack_tool gui` starts the studio
  (Flask, port 8765); project commands wrap `ProjectManager`.
* **`web/app.py`** — the Flask app: thin JSON routes that delegate to
  `ProjectManager`. One route family per editor: creatures, moves, dig
  sites (`fossils`), battles, texts (list / entries / search), settings,
  build, patch.
* **`web/templates/index.html` + `web/static/app.js`** — the single-page
  GUI. Tabs: Home (projects/notes), Vivosaurs, **Moves**, Dig Sites,
  Battles, **Text**, Randomizer & Hard Mode, Build & Share. Vanilla JS;
  every save is one PUT that writes straight into the project workspace.

### Core

* **`project.py` — `ProjectManager`**, the hub every interface goes
  through:
  * *Projects*: `create()` unpacks a ROM with carbonizer into
    `projects/<name>/rom/` (or symlinks an existing unpack); `meta.json`
    stores settings.
  * *Creatures*: reads/writes `creature_defs.dcl.json` directly.
  * *Moves*: parses `etc/attack_defs` (DAL) and joins it with move names
    (`text_attack_name`), descriptions (`text_attack_info`) and owners
    (each vivosaur's `skillIDs`); `set_move()` writes FP/damage/status
    chance in place, keeping the displayed total in sync.
  * *Texts*: lists every `msg/*.dmg.json` and `text/*.dtx.json`,
    serves/saves entries, and does the cross-archive substring search.
    Message indices are immutable — only strings change.
  * *Dig sites*: decodes every map's 8-byte dig records via the kaseki
    index and rewrites only re-verified record offsets.
  * *Battles*: parses DPS files; edits are validated against the
    documented-safe ranges (rank 1–20, tactic 1–4, AI id 1–17, multiplier
    0.05–8.0).
  * *Builds*: see pipelines below.
* **`randomizer.py` / `hard_mode.py`** — optional build-time mods: seeded
  fossil-site shuffle, element-preserving enemy shuffle, and the rank/AI
  hard-mode pass.
* **`presets/elite.py`** — the whole Elite Champions design as data +
  pure functions: tier multipliers and viability floor, the
  element-preserving enemy swap permutation, Boneysaur buffs, smart-AI
  floor, the per-zone dig-pool rebuild, and all story TEXT_EDITS.
  `presets/tier_balance.py` holds the community tier list and the power
  score used to compare vivosaurs.
* **`banner.py`** — DS menu banner title writer (all language slots +
  CRC16s, DSi animated-banner aware).
* **`bps.py`** — structure-aware BPS encoder/decoder. It pairs regions
  (arm9/arm7/every FAT file) between base and hack, emits `SourceRead`
  for identical regions and for identical stretches of the gaps between
  them (header, tables, padding, the 0xFF card fill), and literals only
  for real changes — with the in-place build that's a ~0.6 MB patch for
  the whole hack. Every patch is decoded back and byte-compared before
  it's written.
* **`carbonizer.py`** — wrapper around the external carbonizer.exe used
  for *unpacking* (and as a legacy full-repack fallback). carbonizer
  exits 0 even on errors, so output is scraped for failure markers.

### Formats (`formats/`) — one parser per game structure

| module | file(s) | editor it powers |
|--------|---------|------------------|
| `dps_format.py` | `battle_param/*` | Battles tab, hard mode, elite battles |
| `dal_format.py` | `etc/attack_defs` | Moves tab |
| `dmg_format.py` | `msg/*` | Text tab (dialogue), elite story rewrite |
| `dtx_format.py` | `text/*` | Text tab (names/UI), move names |
| `dcl_encode.py` / `dcl_binary.py` | `etc/creature_defs` | Creatures tab / elite stat scaling |
| `map_spawn.py` | `map/m/*` + `etc/kaseki_defs` | Dig Sites tab, elite dig overhaul |

All of them parse into plain dataclasses and write **in place** (sizes
never change inside a payload), and each is round-trip tested against the
retail files byte-for-byte.

### Compression (`compression/`)

`mar.py` / `mcm.py` implement the game's two container layers; `lzss.py`,
`huffman.py`, `rle.py` implement the three chunk codecs including
encoders (optimal-parse LZSS, retail-shaped 4-bit Huffman). The key API
is `repack_mar_like(original, [payload], fit=slot)`: re-encode a payload
with the original file's own scheme, reuse stored bytes for unchanged
chunks, fall back to another retail scheme if the slot demands it, and
self-verify. See FORMATS.md for the details.

### ROM writing (`nds_inplace.py`)

`InPlaceRom` patches the ROM image bytes directly instead of repacking
the filesystem: files that fit stay at their original card address, and
only oversized ones are relocated using carbonizer's own placement rule
(0x200-aligned, past the end of the original data, FAT + header CRC fixed
up). Everything else — FNT, code, overlays, the DSi-enhanced region —
stays byte-identical.

**Why this exists:** the previous injector used ndspy's generic
`saveToFile`, which rebuilt the filesystem tightly. That moved ~9,800
files, wrapped every replaced file as uncompressed MCM (a layout retail
uses, but not for those files), trimmed the image and dropped DSi data.
DeSmuME shrugged; melonDS crashed the moment a movie displayed rewritten
subtitles. The in-place writer eliminates all of those deltas: in the
current Elite build 774 of 783 touched files sit at their retail
addresses in their retail compression schemes, and the other 9 follow
carbonizer's relocation rule.

## Build pipelines

### 1. Elite Champions (`scripts/build_elite_champions.py`)

`rom_patcher.build_elite_rom()`: load the decoded creature JSON, compute
the tier/swap tables, then for each target file *decompress → patch the
payload in place → repack with the retail scheme → stage into
`InPlaceRom`*. Steps: ① DCL stat rebalance, ② every battle file (swaps,
Boneysaur buffs, hard mode, AI floor), ③ dig-pool rebuild across all
maps, ④ story TEXT_EDITS into the DMG files, ⑤ banner. After writing, the
output ROM is re-opened and **every touched file is decompressed and
byte-compared** against the intended payload; the build report records
placement (`in_place` vs `relocated`) and all change counts.

### 2. GUI project build (`ProjectManager.build`)

Same machinery, driven by the workspace instead of a preset: creature
JSON re-encoded via `encode_dcl`, raw battle/map/kaseki/attack_defs
payloads, and every text archive re-encoded from its `.dmg.json` /
`.dtx.json` — each injected only if it differs from the base ROM, then
verified from the written image. Falls back to a full carbonizer repack
only when the project has no original `.nds` to inject into.

### 3. Sharing (`make_patch` / webpatcher)

`ProjectManager.make_patch()` or `scripts/make_patch.py` produce a
self-verified `.bps` + `manifest.json` (checksums, output name). The
static `webpatcher/` page applies the patch in the player's browser after
validating their dump (size, game code `VDEE`, CRC32) — the ROM never
leaves their machine.

## Scripts (`scripts/`)

* `build_elite_champions.py` — build the hack ROM + `build_report.json`.
* `make_patch.py` — refresh `webpatcher/patches/*` after a rebuild.
* `export_site_docs.py`, `export_battle_docs.py`, `export_dig_docs.py` —
  regenerate the RuntimeRelics site data (per-battle diffs, per-part dig
  percentages).
* `serve_patcher.py` — serve the web patcher locally.
* `compare_battles.py`, `compare_fossils.py`, `analyze_vivos.py` —
  analysis/diff helpers used while reverse-engineering.
* `battle_curation.json` — hand-written trainer/location names overlaid
  on battles (the battle files store neither).

## Verification ladder

Nothing ships on faith; each layer checks itself:

1. every format parser round-trips retail files byte-exactly (DMG, DTX,
   DPS, DAL, MAP records);
2. every compression repack is decompressed and compared before use;
3. every build decodes every touched file back out of the finished ROM;
4. every BPS patch is decoded against the base and byte-compared to the
   hack ROM before it is written.
