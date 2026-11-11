/* Client-side ROM validator + BPS patcher.
 * Everything runs locally; the ROM never leaves the user's machine.
 * The active patch is defined by patches/manifest.json — to ship an
 * update, just regenerate the .bps + manifest (scripts/make_patch.py). */

"use strict";

/* ---------------------------------------------------------------- crc32 */

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32Chunk(crc, bytes, start, end) {
  let c = crc ^ 0xffffffff;
  for (let i = start; i < end; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

async function crc32Async(bytes, onProgress) {
  const CHUNK = 8 << 20;
  let crc = 0;
  for (let pos = 0; pos < bytes.length; pos += CHUNK) {
    crc = crc32Chunk(crc, bytes, pos, Math.min(pos + CHUNK, bytes.length));
    if (onProgress) onProgress(Math.min(pos + CHUNK, bytes.length) / bytes.length);
    await new Promise((r) => setTimeout(r, 0));
  }
  return crc >>> 0;
}

const hex32 = (n) => (n >>> 0).toString(16).padStart(8, "0");

/* ------------------------------------------------------------ BPS apply */

function applyBps(patch, source) {
  if (patch.length < 19 || patch[0] !== 0x42 || patch[1] !== 0x50 || patch[2] !== 0x53 || patch[3] !== 0x31)
    throw new Error("Not a BPS patch");

  let ptr = 4;
  const num = () => {
    let value = 0n, shift = 1n;
    for (;;) {
      const x = patch[ptr++];
      value += BigInt(x & 0x7f) * shift;
      if (x & 0x80) return Number(value);
      shift <<= 7n;
      value += shift;
    }
  };

  const srcSize = num();
  const tgtSize = num();
  const metaSize = num();
  ptr += metaSize;
  if (srcSize !== source.length)
    throw new Error(`Source size mismatch: patch expects ${srcSize} bytes, got ${source.length}`);

  const view = new DataView(patch.buffer, patch.byteOffset + patch.length - 12);
  const expectSrcCrc = view.getUint32(0, true);
  const expectTgtCrc = view.getUint32(4, true);

  const target = new Uint8Array(tgtSize);
  let outPos = 0, srcRel = 0, tgtRel = 0;
  const endOfActions = patch.length - 12;

  while (ptr < endOfActions) {
    const data = num();
    const cmd = data & 3;
    let length = (data >> 2) + 1;
    if (cmd === 0) { // SourceRead
      target.set(source.subarray(outPos, outPos + length), outPos);
      outPos += length;
    } else if (cmd === 1) { // TargetRead
      target.set(patch.subarray(ptr, ptr + length), outPos);
      ptr += length;
      outPos += length;
    } else if (cmd === 2) { // SourceCopy
      const rel = num();
      srcRel += (rel & 1 ? -1 : 1) * (rel >> 1);
      target.set(source.subarray(srcRel, srcRel + length), outPos);
      srcRel += length;
      outPos += length;
    } else { // TargetCopy (may self-overlap: byte-by-byte)
      const rel = num();
      tgtRel += (rel & 1 ? -1 : 1) * (rel >> 1);
      while (length--) target[outPos++] = target[tgtRel++];
    }
  }
  return { target, expectSrcCrc, expectTgtCrc };
}

/* ------------------------------------------------------------------- UI */

function initUi() {
  const $ = (id) => document.getElementById(id);
  let manifest = null;
  let baseline = "Loading patch info…";

  const setReport = (el, html, cls) => {
    el.innerHTML = html;
    el.className = "report " + (cls || "");
  };
  const setBar = (el, frac) => (el.style.width = `${Math.round(frac * 100)}%`);
  const activate = (step) => {
    for (const id of ["step-pick", "step-validate", "step-patch"])
      $(id).classList.toggle("active", id === step);
  };

  async function loadManifest() {
    const res = await fetch(`patches/manifest.json?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`manifest.json: HTTP ${res.status}`);
    manifest = await res.json();
    $("hack-name").textContent = manifest.name;
    $("hack-author").textContent = manifest.author;
    $("hack-version").textContent = manifest.version;
    $("base-label").textContent = manifest.base.label;
    $("base-hint").textContent =
      `Expected: ${manifest.base.label} — ${(manifest.base.size / 2 ** 20) | 0} MB, ` +
      `CRC32 ${manifest.base.crc32.toUpperCase()}`;
  }

  async function handleFile(file) {
    if (!manifest) return;
    const vRep = $("validate-report"), pRep = $("patch-report");
    $("download").classList.add("hidden");
    setReport(pRep, "");
    setBar($("patch-bar"), 0);
    activate("step-validate");
    setReport(vRep, `Reading <strong>${file.name}</strong> (${(file.size / 2 ** 20).toFixed(0)} MB)…`);

    const rom = new Uint8Array(await file.arrayBuffer());
    const problems = [];

    // 1. size
    if (rom.length !== manifest.base.size)
      problems.push(`File size is ${rom.length.toLocaleString()} bytes; a clean dump is ${manifest.base.size.toLocaleString()}.`);

    // 2. game code
    const gamecode = String.fromCharCode(...rom.slice(0x0c, 0x10));
    if (gamecode !== manifest.base.gamecode)
      problems.push(`Game code is "${gamecode}"; expected "${manifest.base.gamecode}" (${manifest.base.label}).`);

    if (problems.length) {
      setReport(vRep, `<strong>✗ This is not the right ROM.</strong><br>${problems.join("<br>")}`, "bad");
      activate("step-pick");
      return;
    }

    // 3. checksum
    setReport(vRep, "Game code OK. Verifying checksum…");
    const crc = await crc32Async(rom, (f) => setBar($("validate-bar"), f));
    const crcHex = hex32(crc);

    if (crcHex === manifest.target.crc32) {
      setReport(vRep, "<strong>✓ This ROM is already patched</strong> with the current version — nothing to do!", "good");
      return;
    }
    if (crcHex !== manifest.base.crc32) {
      setReport(
        vRep,
        `<strong>✗ Checksum mismatch.</strong><br>Your file: CRC32 <code>${crcHex.toUpperCase()}</code> — ` +
        `expected <code>${manifest.base.crc32.toUpperCase()}</code>.<br>` +
        `This usually means a bad dump, a trimmed ROM, or a different region. ` +
        `Re-dump your cartridge and try again.`,
        "bad"
      );
      activate("step-pick");
      return;
    }
    setReport(vRep, `<strong>✓ Clean ROM verified</strong> (CRC32 <code>${crcHex.toUpperCase()}</code>).`, "good");

    // 4. fetch + apply patch
    activate("step-patch");
    setReport(pRep, `Downloading patch v${manifest.version} (${(manifest.patchSize / 2 ** 20).toFixed(1)} MB)…`);
    const res = await fetch(`patches/${manifest.patchFile}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) {
      setReport(pRep, `<strong>✗ Could not download the patch</strong> (HTTP ${res.status}).`, "bad");
      return;
    }
    const patch = new Uint8Array(await res.arrayBuffer());
    setBar($("patch-bar"), 0.3);

    if (hex32(crc32Chunk(0, patch, 0, patch.length)) !== manifest.patchCrc32) {
      setReport(pRep, "<strong>✗ Patch file is corrupted</strong> (checksum mismatch). Try reloading the page.", "bad");
      return;
    }

    setReport(pRep, "Applying patch…");
    await new Promise((r) => setTimeout(r, 30));
    let result;
    try {
      result = applyBps(patch, rom);
    } catch (err) {
      setReport(pRep, `<strong>✗ Patching failed:</strong> ${err.message}`, "bad");
      return;
    }
    setBar($("patch-bar"), 0.6);

    setReport(pRep, "Verifying patched ROM…");
    const outCrc = await crc32Async(result.target, (f) => setBar($("patch-bar"), 0.6 + f * 0.4));
    if (hex32(outCrc) !== manifest.target.crc32) {
      setReport(pRep, "<strong>✗ Output verification failed.</strong> The patched ROM did not match the expected checksum.", "bad");
      return;
    }

    const blob = new Blob([result.target], { type: "application/octet-stream" });
    const link = $("download");
    if (link.href) URL.revokeObjectURL(link.href);
    link.href = URL.createObjectURL(blob);
    link.download = manifest.target.outputName;
    link.classList.remove("hidden");
    setReport(
      pRep,
      `<strong>✓ Patched and verified!</strong> ${manifest.name} v${manifest.version} ` +
      `(CRC32 <code>${hex32(outCrc).toUpperCase()}</code>).`,
      "good"
    );
  }

  const dz = $("dropzone");
  const input = $("file-input");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  input.addEventListener("change", () => input.files[0] && handleFile(input.files[0]));
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("drag");
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });

  loadManifest().catch((err) => {
    document.getElementById("base-hint").textContent = baseline;
    setReport($("validate-report"), `<strong>✗ Could not load patch info:</strong> ${err.message}`, "bad");
  });
}

/* Run in the browser; export internals for the Node test harness. */
if (typeof document !== "undefined") {
  initUi();
} else if (typeof module !== "undefined") {
  module.exports = { applyBps, crc32Chunk, hex32 };
}
