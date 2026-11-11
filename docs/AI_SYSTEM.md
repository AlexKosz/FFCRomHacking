# How battle AI works in Fossil Fighters: Champions

Champions doesn't script each enemy trainer. It builds every trainer a brain
out of two parts: a small set of tactics chosen per battle, which is the
trainer's personality, and a large shared table of scoring numbers that every
trainer in the game reads from, which is how the brain thinks.

The split is useful for a hack. Most retail enemies are pointed at weak
tactics, but the strong tactics already exist because the postgame uses them.
So half of "smarter AI" is just changing which tactics each battle asks for.

The other half is the scoring table. The AI scores its options, takes the
highest, then mixes in randomness. The gap between a good option and a
mediocre one is often small enough that the randomness decides. Multiplying
the scoring numbers leaves every ratio intact, so it doesn't change what the
AI prefers. It only widens those gaps, which stops the randomness from
overriding good decisions.

The rest of this page is where that lives in the ROM and which bytes change.

This is the full picture of how enemy AI is stored, how the game assembles a
brain for each enemy team, and exactly which bytes the Elite Champions hack
(and the studio's Battles tab / Hard Mode) change. Everything here was
reverse-engineered from the retail USA ROM with the parsers in
`ffc_hack_tool/`; claims that are inference rather than verified fact are
marked as such.

## The two layers of AI data

FFC's AI is **data-driven**. There is no per-battle script; instead:

1. **Per-battle knobs** live in `battle_param/battle_param_defs_<id>` (DPS
   files). Each enemy entry carries **four AI tactic ids** and a
   **per-vivosaur tactic class**. These select *which* brain to use.
2. **The brains themselves** live in the nine `etc/ai_*` tables. These define
   *how* each brain scores its options. They are shared by every battle in
   the game.

A hack can therefore make every fight smarter *without touching the AI
tables at all* — by pointing battles at the better brains the postgame
already uses. That is what Elite Champions does (details at the bottom).

## Layer 1: the battle file's AI fields (DPS)

From `formats/dps_format.py` — each battle entry (one side of the fight) has:

```
+0x00 u16[6] header: [?, preBattleMsgId, aiLevel, reward, flag, ?]
+0x0C four (count, offset) pairs:
      pair 0: vivosaur slots (index, rank, ?, lpOverride, ?)
      pair 1: per-vivosaur stat multipliers (0x1000 = 1.0)
      pair 2: per-vivosaur tactic class  <- u16, observed 1-4
      pair 3: 4 bytes of AI tactic ids   <- u8, observed 1-17
```

* **AI tactic ids (4 bytes per entry).** Each byte is a 1-based index into
  the 17 entries of `etc/ai_tactics_defs`. Story-route trainers mostly carry
  low ids (1–10 and the throwaway 16/17); the postgame super battles carry
  11–13. Raising a battle's bytes to the 11+ set is the entire "smarter AI"
  mechanic.
* **Tactic class (per vivosaur, 1–4).** The entry has exactly four AI id
  slots and every vivosaur has a class in 1–4; the counts lining up this way
  strongly suggests the class picks *which of the four tactic ids drives
  that particular vivosaur* (inference — consistent with every file we
  parsed, not yet confirmed by disassembly). This is why the studio bumps
  tactic classes together with the ids.
* **aiLevel (header word 2).** Present in every entry; untouched by the hack.
  Plausibly a difficulty scalar applied on top of the tactic tables
  (inference).

## Layer 2: the AI tables (`etc/ai_*`)

The unpacked `etc/` folder contains **nine** `ai_*` files (if you counted 7:
two of them, `ai_distance_defs` and `ai_kp_defs`, are near-empty
placeholders, and it's easy to miss the tiny ones — the full list is below).
All of them share the same container shape: a magic, an entry count, an
offset table, then variable-size entries.

### The hub: `ai_tactics_defs` (magic `DAI`, 17 entries × 32 bytes)

This is the table the battle files index. Entry layout:

```
u32 tacticId (1-17)   u32 =17 (constant)   u32 =12 (constant)
16 bytes of packed table references
u32 footer (0, except tactics 5 and 15: 5)
```

The 16 data bytes are four 4-byte groups of small indices. Their observed
value ranges match the sizes of the other AI tables exactly, which is the
key structural clue:

| byte range observed | matching table (entry count) |
|---------------------|------------------------------|
| 1–13                | `ai_who_defs` (13)           |
| 1–17                | `ai_target_defs` (17)        |
| 0–14                | `ai_attack_defs` (15)        |
| 1–6                 | `ai_distance_defs` / `ai_kp_defs` (6) |
| 1–4                 | `ai_relation_defs` / `ai_state_defs` (4) |

So a *tactic* is best understood as a **loadout: one row from each of the
decision tables** (inference from the range alignment). Notable rows:

* Tactics **7 and 17 are byte-identical** — the "dummy" brain (all
  references point at row 1, the empty scoring rows). Tactic 16 is nearly as
  inert. These appear on tutorial/scripted fights.
* Tactics **11–13** (the postgame set) reference the dense scoring rows —
  row 6/7 of `ai_attack_defs`, the long rows of `ai_who_defs`.
* Tactics **5 and 15** are the only ones with a nonzero footer (5) — both
  are variants that reference `ai_who_defs` row 9/10 (the rows full of
  team-slot conditions), suggesting the footer flags a special targeting
  mode (unconfirmed).

### The decision tables (magic `AIC`): weighted condition scoring

`ai_attack_defs` (15), `ai_target_defs` (17), `ai_who_defs` (13),
`ai_relation_defs` (4), `ai_state_defs` (4), `ai_distance_defs` (6),
`ai_kp_defs` (6) all share one entry format:

```
u32 count
u32 dataOffset (8)
count × u32:  low u16 = condition id, high u16 = SIGNED weight
```

Examples straight from the retail data:

```
ai_attack_defs row 1:  (cond 0x01, +30) (cond 0x02, +20) (cond 0x03, +10)
                       (cond 0x1F, +30) (cond 0x20, +20) (cond 0x21, +10)
                       (cond 0x2E, -10) (cond 0x2F,  -5)
ai_attack_defs row 5:  (cond 0x43, +4500) (cond 0x44, +5000) ... (cond 0x5A, -1000)
ai_target_defs row 2:  (cond 0x1F, +30) ... (cond 0x36, -200) (cond 0x3B, -200) ...
```

This is a classic **utility-scoring AI**: when the enemy picks an action
(which move to use, which of your vivosaurs to hit, whether to rotate the
AZ/SZ formation), it evaluates each candidate, sums the weights of every
condition that currently holds, and takes the highest-scoring candidate.
Positive weights encourage ("target has low LP", "super-effective element"),
negative weights forbid ("would waste FP", "target immune") — the -200 and
-1000 entries act as vetoes. The precise meaning of each condition id would
need a disassembly; the id space (observed 0x01–0x7F) is shared across the
tables.

Row 0 of each table is `count 0` — the empty row the dummy tactics point at:
score nothing, i.e. behave randomly/passively. The difference between "dumb
early-game AI" and "sharp postgame AI" is literally *how many conditions the
brain is allowed to consider*.

### The nine files at a glance

| file | magic | entries | role |
|------|-------|---------|------|
| `ai_tactics_defs`  | DAI | 17  | the hub: one row per AI tactic id; bundles rows from the tables below |
| `ai_pattern_defs`  | AIP | 300 | behaviour patterns; same weighted-pair format with an extra header word. 300 entries ≈ per-vivosaur/per-archetype attack patterns (inference) |
| `ai_attack_defs`   | AIC | 15  | scoring rows for *which skill to use* |
| `ai_target_defs`   | AIC | 17  | scoring rows for *which enemy slot to attack* |
| `ai_who_defs`      | AIC | 13  | scoring rows for *which of the AI's own vivosaurs acts / rotates* |
| `ai_relation_defs` | AIC | 4   | small modifier rows (element/type relations; includes ±: (+30/-15) pairs) |
| `ai_state_defs`    | AIC | 4   | one condition each — reactions to status states |
| `ai_distance_defs` | AIC | 6   | all rows empty in retail — vestigial (likely an FF1 leftover; FF1 had field movement) |
| `ai_kp_defs`       | AIC | 6   | rows empty except row 6: (cond 1, +60) — near-vestigial |

## How vanilla scales its AI (survey of all 733 battles)

| band | AI ids used | aiLevel | tactic classes |
|------|-------------|---------|----------------|
| tutorial | 1, 16 (dummy) | 1–7 | mostly 4 |
| story cups | 1, 9–14, 17 | 1–16 | mixed 1–4 |
| story bosses | 1–5, 11–12, 16 | 1–9, **20** on the finale | mixed |
| postgame supers | 11, 12, 15 | **9** dominant | 3–4 only, never 1 |

Key facts this exposes: the strongest *loadout mixes* — `(13,13,12,12)`,
`(14,14,12,12)`, `(14,14,13,12)` — appear only on a handful of elite cup
trainers (the postgame supers stick to 11/12); the **aiLevel** header word
tracks difficulty and peaks at 20 only on the final story bosses; and ids
16/17 are dummy brains that a few story battles carry.

## What the Elite Champions hack actually changes

Per non-tutorial battle (`presets/elite.py`, seeded so builds are
deterministic):

1. **AI loadout:** every enemy entry's four tactic bytes are replaced with
   one of the six proven-elite quadruples above (`AI_PALETTE`) — dealt per
   battle so fights play differently. This also wipes the dummy brains
   16/17.
2. **aiLevel = 20** for every enemy entry — the value vanilla reserves for
   the final bosses (postgame supers only get 9).
3. **Tactic classes** are re-dealt with the postgame supers' distribution
   (~53% class 3, ~40% class 4, ~7% class 2 — class 1 never).
4. Tutorial battles (ids 1, 2, 3, 4, 1906, 1907) are skipped so the
   scripted opening still plays out.

### Beyond vanilla: weight sharpening (`sharpen_ai_weights`)

Four *scoring* tables (`ai_target`, `ai_who`, `ai_relation`, `ai_pattern`)
get every signed weight multiplied by **3** (`AI_WEIGHT_SCALE`).
`ai_attack` ("which skill to use") is deliberately **left at vanilla
margins** — sharpening it made the AI over-commit to its top-scored move
even when that was a wasteful 0-damage utility move (Law of the Jungle at
full HP, Power Scale when already buffed); leaving its margins alone lets
the engine's decision randomness override those bad picks (playtesting
2026-07-13). Because the transform is uniform, every ratio
and preference ordering the designers built is preserved exactly — what
changes is the *margin*: the score gap between the best action and the
runner-up triples, so whatever randomness the engine mixes into its
decisions flips the choice far less often. The combined effect (elite
loadouts + max aiLevel + super classes + sharpened tables) is a
configuration stronger than any single scenario retail ships, including
the postgame.

Retail weights span ±9999, so ×3 stays inside the s16 fields with zero
clipping; condition ids are untouched. `ai_state`/`ai_kp` (0–100
threshold-like values, not signed weights), the empty `ai_distance`, and
the `ai_tactics_defs` hub itself remain byte-identical to retail — the
build verifies all of this from the output ROM.

> **Why the *old* patcher broke combat:** it incremented nearly every byte
> in the `ai_*` files themselves, which destroyed the offset tables at the
> top of each file — the game dereferenced garbage as entry offsets when
> battle AI loaded. The current sharpening pass, by contrast, parses each
> table and rewrites only the s16 weight fields, leaving every offset,
> count and condition id intact — and the build re-verifies the tables
> from the output ROM.

## Editing AI in the studio

The Battles tab exposes, per battle: the four AI tactic ids (1–17), each
vivosaur's tactic class (1–4), rank, and stat multiplier — validated against
the documented-safe ranges above. Hard Mode applies the same
floor-to-the-smart-set transformation as Elite Champions to every
non-tutorial battle.
