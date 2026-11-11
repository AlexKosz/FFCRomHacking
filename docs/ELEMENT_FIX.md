# The elemental resistance fix

Champions has an element wheel: Water beats Fire beats Earth beats Air beats
Water. Attacking with the winning element does extra damage. Attacking into a
losing matchup is supposed to do less, and in Champions it doesn't. A Fire
attack on a Water vivosaur lands for full.

The cause turned out to be a single value. The game stores its four element
multipliers next to each other in one settings file, and the slot for
disadvantage shipped set to ×1.00, which means no effect. The other three are
filled in correctly. The fix writes the first game's value into that slot.

The rest of this page is the evidence for that, and how it was confirmed
in-game.

## The bug

In retail FFC, an elemental **disadvantage does nothing**. The damage
formula's element multiplier (community-verified on the
[Competitive Fossil Fighters wiki](https://competitivefossilfighters.fandom.com/wiki/Damage_(FFC))):

| matchup | retail multiplier |
|---------|-------------------|
| advantage | ×1.5 |
| neutral | ×1.0 |
| **disadvantage** | **×1.0** |
| boost advantage | ×2.0 |
| boost disadvantage | ×0.5 |

FF1 applied a ×0.75 resistance on disadvantage; FFC shipped without it.
(FFC chart: Water > Fire > Earth > Air > Water; Neutral/Legendary flat.)

## Root cause (reverse-engineered + verified in-game)

`etc/btl_adjust_defs` (magic `DBA`) is the battle-constants file. At
payload offset **0x44** sits the element multiplier vector — four u32s in
0x1000 fixed point, indexed by the matchup relation:

```
0x44: 0x2000  2.0   boost advantage
0x48: 0x1800  1.5   advantage
0x4C: 0x1000  1.0   DISADVANTAGE   <- the bug
0x50: 0x0800  0.5   boost disadvantage
```

**The developers shipped a dedicated disadvantage slot — set to ×1.0.**
True neutral matchups never consult the vector at all, which is why the
missing resistance looked like a code problem for a decade.

Verified with byte-probe ROMs (`scripts/element_diagnostic.py`) and
in-game A/B damage tests on 2026-07-08:

* probing five *other* ×1.0 constants in the file changed nothing
  (diagnostic 1: disadvantage damage 34 → 34);
* doubling `+0x48` doubled advantage damage (diagnostic 2: 34 → 67 with
  the random-variance pair `+0x38/+0x3C` pinned to 1.0);
* halving `+0x4C` slashed disadvantage damage (diagnostic 3: 54 → 17 —
  more than half because the element multiplier applies to the attack
  term *before* defense is subtracted).

Code-side (for future RE): the battle overlay is **overlay 03** (load
0x2145300; carbonizer overlay `.bin`s are BLZ-compressed — decompress
with `ndspy.codeCompression` before analysis). The battle context keeps
the constants pointer at +0xA8, wrapped by an accessor cluster at RAM
~0x2155B40–0x2155BF0; the element-vector getter is `0x2155BCC` with three
call sites (0x2161596/0x21616AC/0x2161F3A) inside the damage machinery at
0x2160B08. None of that needed patching in the end.

## The fix: one constant

`ffc_hack_tool/patches/element_fix.py` writes FF1's resistance value into
the disadvantage slot: `+0x4C: 0x1000 → 0x0C00`.

* **advantage → ×1.5** (untouched)
* **neutral → ×1.0** (untouched)
* **disadvantage → ×0.75** (resistance restored)

Every blue ability stays exactly as retail; Elemental Boost keeps its own
±slots (×2.0 / ×0.5) and remains meaningful. `patch_btl_adjust` refuses
to touch a file whose vector isn't byte-exact retail (or already fixed),
and `get_element_multiplier(attacker, defender)` in the same module is
the reference implementation of the fixed matchup.

## Using it

* **Studio:** Randomizer & Hard Mode tab → "Bug fix: elemental
  resistance". Applied at build time only — workspace files are never
  rewritten, so toggling off and rebuilding restores retail behavior.
* **Elite Champions:** on by default (`fix_element_resistance=True`);
  the build report logs the multipliers.
* Builds verify the patched file decodes back from the finished ROM, and
  the build refuses to run against an unrecognized `btl_adjust_defs`.

## In-game sanity check

On a fixed build: a disadvantage attack (e.g. Fire hitting Water) deals
noticeably less than before; a neutral attack (e.g. Fire hitting Air) is
unchanged from retail. The diagnostic ROMs in `projects/elite-champions/`
can be deleted once you're satisfied.
