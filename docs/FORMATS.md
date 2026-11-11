# FFC file formats — reference

A DS cartridge is a filesystem, but nothing on it opens in anything. Every
file uses a layout the developers invented, compressed with a scheme they also
invented, and none of it is documented. Changing a vivosaur's attack stat
means first working out which file holds it, how that file is compressed, and
where in the decompressed result the number sits.

This page is the result of that work. Each format here was tested by taking a
retail file apart, putting it back together, and checking the result matches
the original byte for byte. A format that fails that check is wrong, and
anything built on it would corrupt the game.

If you're not adding support for a new file type,
[TOOL_INTERNALS.md](TOOL_INTERNALS.md) is probably the page you want.

Every format the toolkit reads or writes, as implemented (and byte-exact
round-trip tested) in `ffc_hack_tool/`. All integers are little-endian.

## Container layers

Every game data file in the ROM is wrapped twice:

```
ROM file  =  MAR archive  ->  1+ MCM blobs  ->  compressed chunks  ->  payload
```

### MAR (`compression/mar.py`)

```
0x00 "MAR\0"
0x04 u32 entryCount
0x08 entryCount × (u32 offsetOfMcmBlob, u32 decompressedSize)
...  MCM blobs, back to back
```

Almost every file the toolkit touches is a single-entry MAR.

### MCM (`compression/mcm.py`)

```
0x00 "MCM\0"
0x04 u32 decompressedSize
0x08 u32 maxChunkSize        (0x2000 everywhere that matters)
0x0C u32 chunkCount
0x10 u8 compression1, u8 compression2, u16 pad
0x14 (chunkCount+1) × u32 chunk offsets (relative to MCM start)
...  chunk data
```

The payload is split into `maxChunkSize` pieces; each stored chunk is
decoded by applying **compression1 first, then compression2**
(so encoding applies 2 then 1). Types: 0 none, 1 RLE, 2 LZSS, 3 Huffman.
Retail scheme census (all 11,827 MAR files): `(0,0)` ×19,845, `(2,0)`
×7,922, `(3,2)` ×2,732, `(3,1)` ×1,225, `(3,0)` ×1,145, `(1,0)` ×156.
Folders we patch: `msg/` is mostly `(3,2)`, `battle_param/` is `(2,0)` and
`(3,0)`, `map/m/` mixes all three, `etc/creature_defs` & `etc/kaseki_defs`
are `(3,2)`.

### Chunk codecs (`compression/lzss.py`, `huffman.py`, `rle.py`)

All three use the GBA/NDS BIOS stream layout: `u32 header` where the high
24 bits are the decompressed size and the low byte is `type<<4 | flags`.

* **LZSS (0x10):** flag byte per 8 tokens; literal = 1 byte; match = u16
  with 4-bit length (3–18) and 12-bit displacement (1–0x1000), overlapping
  copies allowed. Our encoder does hash-chain matching plus an optimal
  parse (backwards DP over exact bit costs), so re-compressed files come
  out the same size or smaller than retail's greedy output.
* **Huffman (0x24 = 4-bit symbols):** payload = `u8 branchCount`, the tree
  (root at byte 1, child pairs packed after it; each branch byte = 6-bit
  offset to its child pair + "child is leaf" flags in bits 7/6), then the
  bitstream read as u32 words, bits consumed MSB-first. 4-bit mode emits
  the low nibble of each byte first. Every retail tree has an odd branch
  count (9–25), which keeps the bitstream 4-byte aligned — our encoder
  preserves that invariant by padding the leaf set to an even size.
* **RLE (0x30):** flag byte: bit 7 = run (length-3, then the byte),
  else literal run (length-1, then the bytes).

### Repacking rule (`repack_mar_like` / `repack_mcm_like`)

When the toolkit writes a file back it re-encodes with the **same scheme
the retail file used**, and any 0x2000 chunk whose decompressed bytes are
unchanged keeps its original stored bytes verbatim. If the result would
outgrow the file's ROM slot, the other retail schemes are tried and the
smallest wins. Every repack is self-verified (decompressed and
byte-compared) before it is accepted.

## ROM layout & in-place patching (`nds_inplace.py`)

FFC expects files to sit where the retail card put them: carbonizer's own
packer re-uses every file's original FAT slot and only relocates a file
that no longer fits (to fresh 0x200-aligned space past the end of the
original data). `fileTables.json` in a carbonizer unpack is its snapshot
of the retail FAT used for exactly this.

`InPlaceRom` reproduces those rules directly on the ROM bytes:

* a replaced file that fits its FAT extent **plus the 0x200-alignment
  padding after it** is written at its original address;
* only a file too big for that whole gap is relocated (FAT entry updated,
  header `totalUsedRomSize` + header CRC16 fixed up);
* nothing else changes — FNT, arm9/arm7, overlays, banner (except the
  title, patched in place with its CRCs), the DSi-enhanced region, and all
  untouched files stay byte-identical.

This is what fixed the melonDS crash: a generic repack (ndspy
`saveToFile`) moved ~9,800 files, re-wrapped everything as uncompressed
MCM, and dropped the DSi region — DeSmuME tolerated it, melonDS did not.
The in-place build keeps the Elite Champions image 99.93% byte-identical
to retail (a 0.6 MB BPS patch instead of 19.7 MB).

## Data formats

### DPS — battles (`formats/dps_format.py`)

`battle_param/battle_param_defs_<id>`; see the file header comment and
[AI_SYSTEM.md](AI_SYSTEM.md) for the AI fields. Vivosaur references are
**0-based indices into the creature_defs array**, not `_id` values (30 ids
are duplicated by boss/super variants; Boneysaurs are indices 184–190,
Salada 210, Lord Tonzilla 192). Array index 0 is a dummy entry, which is
what lets slot id 0 mean "empty slot". This was documented as 1-based for a
while; it isn't, and reading it that way shifts every enemy by one
creature. The evidence is in the `dps_format.py` header.

### DMG — dialogue text (`formats/dmg_format.py`)

`msg/*`: `"DMG\0", u32 count, u32 indicesOffset(0xC), u32[count] record
offsets`; each record is `u32 messageIndex, u32 stringOffset(8),
null-terminated UTF-8, padded to 4`. The game looks strings up by message
index, so indices must never change — only string contents. Carbonizer
decodes these to `msg/*.dmg.json` (`[{index, string}]`), which is what the
studio's Text tab edits.

Control codes seen in strings: `$p` player name, `$c1…$c0` color spans,
`$c2…$c0` keyword color, `$f` page break, literal `\n` line breaks.

### DTX — UI/name text (`formats/dtx_format.py`)

`text/*`: `"DTX\0", u32 count, u32 indicesOffset(0xC), u32[count] string
offsets`, strings null-terminated UTF-8, tightly packed, file padded to 4.
No per-string index — position is identity. Carbonizer decodes these to
`text/*.dtx.json` (a plain string array). Move names
(`text_attack_name`), vivosaur names (`text_dino_name`), skill
descriptions (`text_attack_info`) and all menus live here.

### DAL — moves (`formats/dal_format.py`)

`etc/attack_defs`: `"DAL\0", u32 ?, u32 count(801), u32 indicesOffset
(0x10), u32[count] record offsets`. Record:

```
+0x00 u8  effectId       status effect instance (2/3 poison, 7/8 scare,
                         0x15 evasion... ; 0/1 = plain attack)
+0x01 u8  effectChance   the % shown in game
+0x02 u16 ?
+0x04 u32 moveId         == record index
+0x08 u32 hitCount       1-3 (combos are multi-hit)
+0x0C u32 offHits        -> hitCount × (u16 fpCost, u16 damage)
+0x10 u32 offTotal       -> (u16 fpCost, u16 damage) summed over hits;
                         this is what the game displays and charges
+0x14 u32 offExtra       -> secondary-effect words
```

Verified against gameplay data: Alio Tusk (80 FP), Poison Needle (130 FP,
poison 50%), Poison Breath (200 FP, damage 0, poison 100%), and the
"total = sum of hits" invariant holds for all 799 editable retail moves.
`damage` is base power — the game scales it by the attacker's Attack stat
and rank. **Moves have no element**: element is a property of the
vivosaur that owns the move (`creature_defs`).

### DCL — vivosaurs (`etc/creature_defs`)

Carbonizer decodes this to `creature_defs.dcl.json` (the studio's
Creatures tab edits that JSON; `formats/dcl_encode.py` re-encodes it, and
`formats/dcl_binary.py` applies stat multipliers directly to the binary
for the Elite build). Count at 0x20; per-vivosaur health tables live at
vivosaur-relative offsets. Notable fields: element, range + 8 range
multipliers, 4 stats (rank-20 values + growth), `healthAtEachRank[20]`,
`skillIDs` (DAL move ids), `skillLearningLevels`, `linkMoveID`,
`teamSkillID`, status immunities, `teamGroups` (the `boney` group marks
BareBones Brigade skeletons).

### RLS — fossil rocks (`etc/kaseki_defs`)

Rock definitions ("kaseki" = fossil). FFC entries carry the vivosaur
array index at +0x10 and the body part at +0x08 (1 head, 2 body, 3 arms,
4 legs). Jewel rocks, droppings and dark fossils are ids with no
vivosaur mapping. `formats/map_spawn.py` builds the (vivosaur, part) <->
rock id index from this file.

### MAP dig records (`map/m/*`)

Dig-site fossil pools are streams of 8-byte records inside the `MAP`
files: `u16 paramA, u16 paramB, u16 zone (two packed bytes), u16
kasekiId`. Each record is one equally-weighted roll of the site's dig
table; rewriting its kaseki id changes what that spot can yield. (The
FF1-style `ThingC` vivosaur records also present in these maps do NOT
drive digs in FFC — verified against Treasure Lake's actual pool.)

### 3BA / DCSL / others

`etc/battle_attack_type` (`3BA`, 205 × 112B) and
`etc/creature_strength_defs` (`DCSL`) follow the same count+offset-table
container; not yet decoded field-by-field and not needed by any current
editor.
