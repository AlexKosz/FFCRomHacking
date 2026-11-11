import json
import shutil
import subprocess
from pathlib import Path


DEFAULT_CARBONIZER_CONFIG = {
    "compression": False,
    "externalMetadata": True,
    "game": "ffc",
    "skipUnpacking": [
        "model/**",
        "motion/**",
        "image/**",
        "msg/**",
    ],
    "processors": {
        "exportModels": False,
        "exportVivosaurModels": False,
        "exportSprites": False,
        "exportImages": False,
        "ffcCreatureLabeller": True,
        "mapLabeller": True,
        "episodeBattleLabeller": True,
    },
}


class CarbonizerError(RuntimeError):
    pass


def find_carbonizer(explicit: Path | None = None) -> Path:
    if explicit and explicit.exists():
        return explicit

    candidates = [
        Path(__file__).resolve().parents[1] / "tools" / "carbonizer" / "carbonizer.exe",
        Path.cwd() / "tools" / "carbonizer" / "carbonizer.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "carbonizer.exe not found. Place it in tools/carbonizer/ or pass --carbonizer."
    )


def ensure_config(carbonizer_dir: Path) -> Path:
    config_path = carbonizer_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps(DEFAULT_CARBONIZER_CONFIG, indent=2), encoding="utf-8")

    # carbonizer actually reads config.json5. Its "game": "auto" guesses the
    # game FROM THE FILE/FOLDER NAME; anything without "Champions" in it gets
    # parsed as FF1 and fails. This tool is FFC-only, so pin it.
    # Full FFC repacks also need compression on, or the ROM is too big to boot.
    json5_path = carbonizer_dir / "config.json5"
    if json5_path.exists():
        text = json5_path.read_text(encoding="utf-8")
        patched = text.replace('"game": "auto"', '"game": "ffc"').replace(
            '"compression": false', '"compression": true'
        )
        if patched != text:
            json5_path.write_text(patched, encoding="utf-8")
    return config_path


def run_carbonizer(
    carbonizer: Path,
    mode: str,
    target: Path,
    *,
    timeout: int | None = None,
    log_path: Path | None = None,
) -> None:
    ensure_config(carbonizer.parent)
    flag = "--pack" if mode == "pack" else "--unpack"
    log_file = None
    try:
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "w", encoding="utf-8")
            stdout = log_file
            stderr = subprocess.STDOUT
        else:
            stdout = subprocess.DEVNULL
            stderr = subprocess.DEVNULL

        result = subprocess.run(
            [str(carbonizer), flag, str(target)],
            cwd=carbonizer.parent,
            stdin=subprocess.DEVNULL,  # it may prompt "Press Enter to continue..."
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
        )
    finally:
        if log_file:
            log_file.close()

    log_text = ""
    if log_path and log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")

    if result.returncode != 0:
        raise CarbonizerError(log_text[-4000:] or f"carbonizer {mode} failed (exit {result.returncode})")

    # carbonizer prints errors to stderr but still exits 0 -- surface them.
    # progress updates share a line with errors ("decompressing X...<ESC>[0Kerror: ..."),
    # so look for "error:" anywhere, not just at line start
    error_lines = []
    for line in log_text.splitlines():
        pos = line.lower().find("error:")
        if pos != -1:
            error_lines.append(line[pos:].strip())
    if error_lines:
        raise CarbonizerError("carbonizer reported errors:\n" + "\n".join(error_lines[-10:]))


def unpack_rom(rom_path: Path, carbonizer: Path, output_dir: Path | None = None) -> Path:
    """Unpack a ROM. Carbonizer always writes its output folder next to the
    ROM (rom name minus .nds); when output_dir points elsewhere the result is
    moved there — or copied, if that folder already existed before the run
    (it may be the user's own unpacked data, which we must not steal)."""
    rom_path = rom_path.resolve()
    default_out = rom_path.with_suffix("")
    output_dir = output_dir.resolve() if output_dir else default_out
    if output_dir.exists():
        shutil.rmtree(output_dir)

    preexisting = default_out.exists()
    log_path = output_dir.parent / "carbonizer_unpack.log"
    run_carbonizer(carbonizer, "unpack", rom_path, timeout=600, log_path=log_path)
    if not default_out.exists():
        raise CarbonizerError(f"Expected unpacked folder at {default_out}")

    if output_dir != default_out:
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if preexisting:
            shutil.copytree(default_out, output_dir)
        else:
            shutil.move(str(default_out), str(output_dir))
    return output_dir


def pack_rom(unpacked_dir: Path, carbonizer: Path, output_rom: Path | None = None) -> Path:
    unpacked_dir = unpacked_dir.resolve()
    log_path = unpacked_dir.parent / "carbonizer_pack.log"
    run_carbonizer(carbonizer, "pack", unpacked_dir, timeout=3600, log_path=log_path)
    built = unpacked_dir.with_suffix(".nds")
    if not built.exists():
        alt = unpacked_dir.parent / f"{unpacked_dir.name}.nds"
        if alt.exists():
            built = alt
        else:
            raise CarbonizerError(f"Expected packed ROM at {built}")
    if output_rom:
        output_rom.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, output_rom)
        return output_rom.resolve()
    return built.resolve()


def convert_file(carbonizer: Path, file_path: Path) -> None:
    run_carbonizer(carbonizer, "unpack", file_path, timeout=120)
