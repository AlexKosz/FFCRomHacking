"""Build the web-patcher payload: a BPS patch (base ROM -> hack ROM) + manifest.

Run this after every `build_elite_champions.py` to refresh the web patcher:

    python scripts/make_patch.py

Outputs into webpatcher/patches/:
    fossil-fighters-elite-champions.bps
    manifest.json   (checksums + metadata the page uses for validation)

The BPS encoder/decoder lives in ffc_hack_tool.bps (structure-aware NDS
region diff, self-verified) and is shared with the studio's Build & Share
tab.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ffc_hack_tool.bps import decode_bps, encode_bps  # noqa: E402

BASE = REPO / "Fossil Fighters Champions (USA) (NDSi Enhanced).nds"
HACK = REPO / "projects" / "elite-champions" / "Fossil Fighters Elite Champions.nds"
OUT_DIR = REPO / "webpatcher" / "patches"
PATCH_NAME = "fossil-fighters-elite-champions.bps"


def main() -> None:
    if not BASE.exists():
        sys.exit(f"Base ROM not found: {BASE}")
    if not HACK.exists():
        sys.exit(f"Hack ROM not found (run build_elite_champions.py first): {HACK}")

    print("Reading ROMs...")
    source = BASE.read_bytes()
    target = HACK.read_bytes()

    print(f"Encoding BPS delta ({len(source)//2**20} MB -> {len(target)//2**20} MB)...")
    t0 = time.time()
    patch = encode_bps(source, target, metadata=b"Fossil Fighters Elite Champions by RuntimeAlex")
    print(f"  patch size: {len(patch)/2**20:.1f} MB in {time.time()-t0:.0f}s")

    print("Self-verifying (decode + byte compare)...")
    rebuilt = decode_bps(patch, source)
    if rebuilt != target:
        sys.exit("SELF-CHECK FAILED: decoded patch does not reproduce the hack ROM")
    print("  OK: patch reproduces the hack ROM byte-for-byte")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / PATCH_NAME).write_bytes(patch)

    # Where the DSi (TWL) region starts (ARM9i offset out of the extended
    # header) and the CRC32 of everything before it. The web patcher uses
    # these to explain a failed checksum: a DS-only dumper can't read the
    # TWL area of a DSi-enhanced card and fills the tail with one repeated
    # 4 KB block, which leaves the game data perfect but the file wrong.
    twl_start = (
        int.from_bytes(source[0x1C0:0x1C4], "little") if source[0x12] & 0x02 else 0
    )

    # A dump whose DSi region never got read still patches: the page applies
    # the patch, blanks the junk tail back to 0xFF padding and checks the
    # result against this checksum. That build plays as a DS game and will
    # not boot in DSi mode -- the last resort for a playtester who cannot
    # re-dump their cartridge.
    salvage_crc = (
        zlib.crc32(b"\xff" * (len(target) - twl_start), zlib.crc32(target[:twl_start]))
        if twl_start
        else 0
    )

    manifest = {
        "name": "Fossil Fighters Elite Champions",
        "author": "RuntimeAlex",
        "version": time.strftime("%Y.%m.%d"),
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "patchFile": PATCH_NAME,
        "patchSize": len(patch),
        "patchCrc32": f"{zlib.crc32(patch):08x}",
        "base": {
            "gamecode": source[0x0C:0x10].decode("ascii"),
            "internalTitle": source[0:12].decode("ascii").strip(),
            "size": len(source),
            "crc32": f"{zlib.crc32(source):08x}",
            "md5": hashlib.md5(source).hexdigest(),
            "label": "Fossil Fighters: Champions (USA) (NDSi Enhanced)",
            "twlStart": twl_start,
            "ntrCrc32": f"{zlib.crc32(source[:twl_start]):08x}",
        },
        "target": {
            "size": len(target),
            "crc32": f"{zlib.crc32(target):08x}",
            "outputName": "Fossil Fighters Elite Champions.nds",
            "salvageCrc32": f"{salvage_crc:08x}",
            "salvageOutputName": "Fossil Fighters Elite Champions (DS mode only).nds",
        },
    }
    if not twl_start:  # not a DSi-enhanced card: nothing for the tail checks
        del manifest["base"]["twlStart"], manifest["base"]["ntrCrc32"]
        del manifest["target"]["salvageCrc32"], manifest["target"]["salvageOutputName"]
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote {OUT_DIR / PATCH_NAME}")
    print(f"Wrote {OUT_DIR / 'manifest.json'}")
    print("Serve the page with:  python scripts/serve_patcher.py")


if __name__ == "__main__":
    main()
