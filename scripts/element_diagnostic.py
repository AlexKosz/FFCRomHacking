"""Build the elemental-resistance DIAGNOSTIC ROM.

Retail FFC ignores elemental disadvantage (x1.0). We know the element
multiplier ladder sits in etc/btl_adjust_defs at +0x40, but SIX different
fields in that file hold x1.0 (0x1000) and static analysis cannot prove
which one - if any - the plain-disadvantage case reads (it may share the
true-neutral slot at +0x4C, in which case only a code patch can fix it).

This script builds a probe ROM from the clean base game with each candidate
set to a distinct, recognizable value:

    +0x58 -> x0.90     +0x5C -> x0.70     +0x6C -> x0.50
    +0x74 -> x0.30     +0x80 -> x0.15
    (+0x4C, true neutral, is deliberately left at x1.0)

TEST PROTOCOL (A/B on the same attack, so Defense cancels out):
  1. Use the regular battery save (.sav works on both ROMs; do NOT carry
     savestates between ROMs).
  2. On the CLEAN retail ROM: pick a battle, attack a DISADVANTAGE target
     (e.g. your Fire vivosaur hits a Water enemy) with one move. Note the
     damage. Repeating 2-3x helps average out the random variance.
  3. On THIS diagnostic ROM: same battle, same attacker, same move, same
     target. Note the damage.

  diagnostic / retail =
     ~1.0   -> plain disadvantage shares the neutral slot; a code patch
               is required (report this!)
     ~0.90 / 0.70 / 0.50 / 0.30 / 0.15
            -> that ratio names the dedicated slot; the real fix is one
               constant and every blue ability stays untouched.

Optional control: the same A/B against a NEUTRAL target should show ~1.0
(the neutral slot is untouched). If anything ELSE differs - crit damage,
support effects - the ratio identifies what that slot really controls.

Output: projects/elite-champions/FFC element diagnostic.nds
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ffc_hack_tool.compression.mar import decompress_mar, repack_mar_like
from ffc_hack_tool.nds_inplace import InPlaceRom

SOURCE_ROM = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced).nds"
OUTPUT = REPO / "projects" / "elite-champions" / "FFC element diagnostic.nds"

# candidate slot -> probe multiplier (0x1000 fixed point).
# Spaced ~25%+ apart so a single attack identifies the slot even through
# FFC's random damage variance (~+-7%).
PROBES = {
    0x58: 0x0E66,  # x0.90
    0x5C: 0x0B33,  # x0.70
    0x6C: 0x0800,  # x0.50
    0x74: 0x04CC,  # x0.30
    0x80: 0x0266,  # x0.15
}


# Phase 2 (after phase 1 showed no change on any 1.0-slot probe): does the
# game read the DBA ladder AT ALL? Probe the ADVANTAGE slot -- if an
# advantage attack roughly doubles, the ladder is live and the fix is a
# code patch to the relation index; if nothing changes, the multipliers are
# baked into code and the hunt moves there. The variance pair (+0x38/+0x3C,
# retail 0.95/1.05) is pinned to 1.0/1.0 in the same ROM so damage numbers
# become exact and repeatable.
PROBES2 = {
    0x38: (0x0F33, 0x1000),  # random variance low:  x0.95 -> x1.0
    0x3C: (0x10CD, 0x1000),  # random variance high: x1.05 -> x1.0
    0x48: (0x1800, 0x3000),  # advantage:            x1.5  -> x3.0
}


def build(output: Path, probes: dict, banner: str) -> None:
    rom = InPlaceRom(SOURCE_ROM.read_bytes())
    original = rom.read_file("etc/btl_adjust_defs")
    payload = bytearray(decompress_mar(original)[0])
    print(f"probing etc/btl_adjust_defs -> {output.name}:")
    for off, spec in sorted(probes.items()):
        expected, value = spec if isinstance(spec, tuple) else (0x1000, spec)
        old = struct.unpack_from("<I", payload, off)[0]
        if old != expected:
            sys.exit(f"  +{off:#x}: expected {expected:#x}, found {old:#x} -- aborting")
        struct.pack_into("<I", payload, off, value)
        print(f"  +{off:#x}: x{expected / 0x1000:.2f} -> x{value / 0x1000:.2f}")

    rom.replace_file(
        "etc/btl_adjust_defs",
        repack_mar_like(original, [bytes(payload)], fit=rom.slot_size("etc/btl_adjust_defs")),
    )
    rom.set_banner_title(banner)
    rom.save()
    output.write_bytes(rom.data)

    check = InPlaceRom(output.read_bytes())
    assert decompress_mar(check.read_file("etc/btl_adjust_defs"))[0] == bytes(payload), "verification failed"
    print(f"  OK: {output}")


# Phase 3 (after phase 2 proved the vector at +0x44..+0x50 is live): does
# TRUE NEUTRAL read the +0x4C slot, or is that slot consulted only for
# plain disadvantage (i.e. neutral skips the multiplier entirely)? Halve
# +0x4C and compare both a neutral attack and a disadvantage attack.
PROBES3 = {
    0x38: (0x0F33, 0x1000),  # variance pinned -> exact numbers
    0x3C: (0x10CD, 0x1000),
    0x4C: (0x1000, 0x0800),  # neutral/dis slot: x1.0 -> x0.5
}


def main() -> None:
    if not SOURCE_ROM.exists():
        sys.exit(f"Base ROM not found: {SOURCE_ROM}")
    build(OUTPUT, PROBES, "FFC element\ndiagnostic\n(see docs)")
    build(
        OUTPUT.with_name("FFC element diagnostic 2.nds"),
        PROBES2,
        "FFC element\ndiagnostic 2\n(see docs)",
    )
    build(
        OUTPUT.with_name("FFC element diagnostic 3.nds"),
        PROBES3,
        "FFC element\ndiagnostic 3\n(see docs)",
    )
    print()
    print("Diagnostic 3 test (same .sav, retail vs diagnostic 3):")
    print("  A. NEUTRAL attack (e.g. Fire hitting Air or another Fire).")
    print("  B. DISADVANTAGE attack (e.g. Fire hitting Water).")
    print("  B halved, A unchanged -> +0x4C is a dedicated dis slot: pure data fix!")
    print("  A and B both halved   -> slot shared: code patch to the selection.")


if __name__ == "__main__":
    main()
