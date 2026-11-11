import hashlib
import json
import shutil
import struct
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .bps import decode_bps, encode_bps
from .carbonizer import find_carbonizer, pack_rom, unpack_rom
from .formats.dal_format import parse_dal, write_move
from .formats.dcl_encode import encode_dcl
from .formats.dps_format import parse_dps, write_battle
from .formats.map_spawn import (
    build_kaseki_index,
    find_dig_records,
    find_isolated_records,
    write_record_kaseki,
)
from .randomizer import RandomizerOptions, apply_randomizer
from .hard_mode import apply_hard_mode

# Documented-safe ranges for battle edits (see formats/dps_format.py).
BATTLE_RANK_RANGE = (1, 20)
BATTLE_TACTIC_RANGE = (1, 4)
BATTLE_AI_RANGE = (1, 17)
BATTLE_MULT_RANGE = (0.05, 8.0)

# Documented-safe ranges for move edits (see formats/dal_format.py).
MOVE_FP_RANGE = (0, 999)
MOVE_DAMAGE_RANGE = (0, 999)
MOVE_CHANCE_RANGE = (0, 100)

# Hand-curated trainer/location overlay (battle files store neither).
GENERIC_TRAINER = "Fossil Fighter"
_CURATION_PATH = Path(__file__).resolve().parents[1] / "scripts" / "battle_curation.json"


def _load_curation() -> dict:
    try:
        return json.loads(_CURATION_PATH.read_text(encoding="utf-8")).get("battles", {})
    except (OSError, ValueError):
        return {}


@dataclass
class HackProject:
    name: str
    source_rom: str
    workspace: str
    carbonizer: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    randomizer: dict = field(default_factory=dict)
    hard_mode: bool = False
    element_fix: bool = False
    notes: str = ""
    author: str = ""
    hack_title: str = ""


class ProjectManager:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def project_path(self, name: str) -> Path:
        return self.root / name

    def create(self, name: str, rom_path: Path, carbonizer: Path | None = None) -> HackProject:
        carbonizer = find_carbonizer(carbonizer)
        workspace = self.project_path(name)
        if workspace.exists():
            raise FileExistsError(f"Project '{name}' already exists")

        if not rom_path.exists():
            raise FileNotFoundError(
                f"ROM not found at: {rom_path}. Check the path (tip: shift-right-click "
                "the file in Explorer and choose 'Copy as path')."
            )

        rom_path = rom_path.resolve()
        rom_dir = workspace / "rom"
        if rom_path.is_dir():
            # Link existing carbonizer output instead of copying gigabytes of assets.
            if rom_dir.exists():
                if rom_dir.is_symlink():
                    rom_dir.unlink()
                else:
                    shutil.rmtree(rom_dir)
            try:
                rom_dir.symlink_to(rom_path.resolve(), target_is_directory=True)
            except OSError:
                shutil.copytree(rom_path, rom_dir)
            source = str(rom_path)
        else:
            # Carbonizer unpacks next to its input, which could clobber a
            # folder sitting beside the user's ROM. Unpack a temp copy of the
            # ROM inside the workspace so nothing outside it is touched:
            # workspace/rom.nds unpacks straight into workspace/rom.
            try:
                workspace.mkdir(parents=True, exist_ok=True)
                # carbonizer auto-detects the game FROM THE FILE NAME -- it
                # must contain "Champions" or it parses the ROM as FF1 and fails
                tmp_rom = workspace / "Fossil Fighters Champions (extract).nds"
                shutil.copy2(rom_path, tmp_rom)
                unpack_rom(tmp_rom, carbonizer, rom_dir)
                tmp_rom.unlink()
            except Exception:
                # leave no half-made workspace behind, so the name can be reused
                shutil.rmtree(workspace, ignore_errors=True)
                raise
            source = str(rom_path)

        project = HackProject(name=name, source_rom=source, workspace=str(workspace), carbonizer=str(carbonizer))
        self._save_meta(project)
        return project

    def load(self, name: str) -> HackProject:
        meta = self.project_path(name) / "meta.json"
        if not meta.exists():
            raise FileNotFoundError(f"Project '{name}' not found")
        data = json.loads(meta.read_text(encoding="utf-8"))
        return HackProject(**data)

    def rom_dir(self, project: HackProject) -> Path:
        return Path(project.workspace) / "rom"

    def creature_defs_path(self, project: HackProject) -> Path:
        return self.rom_dir(project) / "etc" / "creature_defs.dcl.json"

    def load_creatures(self, project: HackProject) -> dict:
        path = self.creature_defs_path(project)
        if not path.exists():
            raise FileNotFoundError("creature_defs.dcl.json not found. Re-extract the ROM.")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_creatures(self, project: HackProject, data: dict) -> None:
        path = self.creature_defs_path(project)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _map_dir(self, project: HackProject) -> Path:
        return self.rom_dir(project) / "map" / "m"

    def _vivo_names(self, project: HackProject) -> dict[int, str]:
        names: dict[int, str] = {}
        for index, entry in enumerate(self.load_creatures(project).get("vivosaurs", [])):
            if entry and entry.get("isEntry"):
                names[index] = entry.get("_defaultName", f"Vivosaur {index}")
        return names

    def _kaseki_index(self, project: HackProject):
        payload = (self.rom_dir(project) / "etc" / "kaseki_defs").read_bytes()
        return build_kaseki_index(payload, set(self._vivo_names(project)))

    def list_dig_sites(self, project: HackProject) -> list[dict]:
        """Fossil pool per dig site: which species' rocks each map hands out."""
        map_dir = self._map_dir(project)
        if not map_dir.exists():
            return []
        names = self._vivo_names(project)
        kaseki = self._kaseki_index(project)
        sites = []
        for path in sorted(map_dir.iterdir()):
            if path.suffix or path.name.endswith(".metadata"):
                continue
            data = path.read_bytes()
            records = find_dig_records(data, kaseki.valid_ids)
            pool: dict[int, dict] = {}
            for record in records:
                vp = kaseki.vivo_part.get(record.kaseki_id)
                if not vp:
                    continue  # jewel / dropping / dark rock
                vivo, part = vp
                slot = pool.setdefault(
                    vivo, {"vivo_id": vivo, "name": names.get(vivo, f"#{vivo}"), "parts": set(), "records": 0}
                )
                slot["parts"].add(part)
                slot["records"] += 1
            if pool:
                for slot in pool.values():
                    slot["parts"] = sorted(slot["parts"])
                sites.append({"map_id": path.name, "pool": sorted(pool.values(), key=lambda s: s["vivo_id"])})
        return sites

    def set_dig_site(self, project: HackProject, map_id: str, replace: dict[int, int]) -> int:
        """Swap species in one site's pool: {old vivo index: new vivo index}.
        Rewrites every matching rock record part-for-part."""
        path = self._map_dir(project) / map_id
        data = bytearray(path.read_bytes())
        kaseki = self._kaseki_index(project)
        changed = 0
        for record in find_dig_records(bytes(data), kaseki.valid_ids):
            vp = kaseki.vivo_part.get(record.kaseki_id)
            if not vp:
                continue
            vivo, part = vp
            new_vivo = int(replace.get(vivo, vivo))
            if new_vivo == vivo:
                continue
            new_rock = kaseki.rock_of.get((new_vivo, part))
            if new_rock is not None:
                write_record_kaseki(data, record, new_rock)
                changed += 1
        if changed:
            path.write_bytes(bytes(data))
        return changed

    def _all_dig_records(self, data: bytes, kaseki) -> list:
        records = find_dig_records(data, kaseki.valid_ids)
        records += find_isolated_records(data, kaseki.valid_ids, set(kaseki.vivo_part))
        return sorted(records, key=lambda r: r.offset)

    def dig_site_records(self, project: HackProject, map_id: str) -> dict:
        """Every dig record in one map, fully decoded: offset, spawn params,
        zone code, and the (vivosaur, part) its rock resolves to. Records
        whose rock is a jewel / dropping / dark fossil are included read-only
        so the whole table is visible."""
        path = self._map_dir(project) / map_id
        if not path.exists():
            raise FileNotFoundError(f"map/m/{map_id} not found")
        data = path.read_bytes()
        names = self._vivo_names(project)
        kaseki = self._kaseki_index(project)

        records = []
        species_total = 0
        for rec in self._all_dig_records(data, kaseki):
            a, b, zone = struct.unpack_from("<3H", data, rec.offset)
            vp = kaseki.vivo_part.get(rec.kaseki_id)
            entry = {
                "offset": rec.offset,
                "paramA": a,
                "paramB": b,
                "zone": [zone & 0xFF, zone >> 8],
                "kasekiId": rec.kaseki_id,
                "special": vp is None,
            }
            if vp:
                entry["vivo"], entry["part"] = vp
                entry["name"] = names.get(vp[0], f"#{vp[0]}")
                species_total += 1
            records.append(entry)
        return {"mapId": map_id, "records": records, "speciesRecords": species_total}

    def set_dig_records(
        self, project: HackProject, map_id: str, changes: list[dict]
    ) -> tuple[int, list[str]]:
        """Rewrite individual dig records: [{offset, vivo, part}, ...].
        Only the kaseki-id field is written, and only at offsets re-verified
        as dig records, so map geometry can't be corrupted. Returns
        (records changed, per-change errors); valid changes still apply when
        others fail."""
        path = self._map_dir(project) / map_id
        data = bytearray(path.read_bytes())
        kaseki = self._kaseki_index(project)
        names = self._vivo_names(project)
        by_offset = {r.offset: r for r in self._all_dig_records(bytes(data), kaseki)}

        changed = 0
        errors: list[str] = []
        for change in changes:
            offset = int(change["offset"])
            record = by_offset.get(offset)
            if record is None:
                errors.append(f"offset {offset}: not a dig record in this map")
                continue
            if kaseki.vivo_part.get(record.kaseki_id) is None:
                errors.append(f"offset {offset}: special rock (jewel/dropping) — not editable")
                continue
            vivo, part = int(change["vivo"]), int(change["part"])
            if vivo not in names:
                errors.append(f"offset {offset}: unknown vivosaur index {vivo}")
                continue
            rock = kaseki.rock_of.get((vivo, part))
            if rock is None:
                errors.append(
                    f"offset {offset}: {names[vivo]} has no part-{part} fossil rock in this game"
                )
                continue
            if record.kaseki_id != rock:
                write_record_kaseki(data, record, rock)
                changed += 1
        if changed:
            path.write_bytes(bytes(data))
        return changed, errors

    # ------------------------------------------------------------- text

    def list_texts(self, project: HackProject) -> list[dict]:
        """Every editable text archive in the workspace: story dialogue
        (msg/*.dmg.json) and UI/name tables (text/*.dtx.json)."""
        rom_dir = self.rom_dir(project)
        out = []
        for folder, suffix, kind in (("msg", ".dmg.json", "dmg"), ("text", ".dtx.json", "dtx")):
            root = rom_dir / folder
            if not root.exists():
                continue
            for path in sorted(root.glob(f"*{suffix}")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                out.append(
                    {
                        "file": f"{folder}/{path.name[: -len(suffix)]}",
                        "kind": kind,
                        "count": len(data),
                    }
                )
        return out

    def _text_path(self, project: HackProject, rel: str) -> tuple[Path, str]:
        folder, _, name = rel.partition("/")
        if folder not in ("msg", "text") or not name or "/" in name or "\\" in name or ".." in name:
            raise FileNotFoundError(f"not a text archive: {rel}")
        suffix, kind = (".dmg.json", "dmg") if folder == "msg" else (".dtx.json", "dtx")
        path = self.rom_dir(project) / folder / f"{name}{suffix}"
        if not path.exists():
            raise FileNotFoundError(f"text archive not found: {rel}")
        return path, kind

    def text_entries(self, project: HackProject, rel: str) -> dict:
        path, kind = self._text_path(project, rel)
        data = json.loads(path.read_text(encoding="utf-8"))
        if kind == "dmg":
            entries = [{"index": e["index"], "string": e["string"]} for e in data]
        else:
            entries = [{"index": i, "string": s} for i, s in enumerate(data)]
        return {"file": rel, "kind": kind, "entries": entries}

    def set_text_entries(self, project: HackProject, rel: str, entries: list[dict]) -> int:
        """Replace strings in one archive. Entries must cover the exact same
        indices the archive already has -- strings can change, the message
        list cannot (the game looks messages up by id)."""
        path, kind = self._text_path(project, rel)
        data = json.loads(path.read_text(encoding="utf-8"))
        new_by_index = {}
        for e in entries:
            new_by_index[int(e["index"])] = str(e["string"])
        if kind == "dmg":
            have = [e["index"] for e in data]
            if sorted(new_by_index) != sorted(have):
                raise ValueError("message indices must match the existing archive")
            changed = sum(1 for e in data if new_by_index[e["index"]] != e["string"])
            payload = [{"index": e["index"], "string": new_by_index[e["index"]]} for e in data]
        else:
            if sorted(new_by_index) != list(range(len(data))):
                raise ValueError("entry count must match the existing archive")
            changed = sum(1 for i, s in enumerate(data) if new_by_index[i] != s)
            payload = [new_by_index[i] for i in range(len(data))]
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return changed

    def search_texts(self, project: HackProject, query: str, limit: int = 300) -> list[dict]:
        """Case-insensitive substring search across every text archive."""
        needle = query.lower()
        hits: list[dict] = []
        for info in self.list_texts(project):
            entries = self.text_entries(project, info["file"])["entries"]
            for e in entries:
                if needle in e["string"].lower():
                    hits.append({"file": info["file"], **e})
                    if len(hits) >= limit:
                        return hits
        return hits

    # ------------------------------------------------------------- moves

    def _attack_defs_path(self, project: HackProject) -> Path:
        path = self.rom_dir(project) / "etc" / "attack_defs"
        if not path.exists():
            raise FileNotFoundError("etc/attack_defs not found. Re-extract the ROM.")
        return path

    def _text_strings(self, project: HackProject, rel: str) -> list[str]:
        try:
            data = json.loads(self._text_path(project, rel)[0].read_text(encoding="utf-8"))
            return [s if isinstance(s, str) else "" for s in data]
        except (FileNotFoundError, ValueError):
            return []

    def list_moves(self, project: HackProject) -> list[dict]:
        """Every move in etc/attack_defs with its name, in-game description,
        FP cost / damage per hit, and the vivosaurs that learn it. A move's
        element is its owner's element (FFC has no per-move element)."""
        payload = self._attack_defs_path(project).read_bytes()
        moves = parse_dal(payload)
        names = self._text_strings(project, "text/text_attack_name")
        infos = self._text_strings(project, "text/text_attack_info")

        owners: dict[int, list[dict]] = {}
        for index, entry in enumerate(self.load_creatures(project).get("vivosaurs", [])):
            if not entry or not entry.get("isEntry"):
                continue
            for sid in entry.get("skillIDs", []) or []:
                if sid:
                    owners.setdefault(int(sid), []).append(
                        {
                            "index": index,
                            "name": entry.get("_defaultName", f"#{index}"),
                            "element": entry.get("element", "none"),
                        }
                    )

        out = []
        for move in moves:
            if not move.hits:
                continue  # dummy / non-editable record
            out.append(
                {
                    "id": move.id,
                    "name": names[move.id] if move.id < len(names) else f"#{move.id}",
                    "info": infos[move.id] if move.id < len(infos) else "",
                    "effectId": move.effect_id,
                    "effectChance": move.effect_chance,
                    "hits": [{"fp": h.fp, "damage": h.damage} for h in move.hits],
                    "total": {"fp": move.total.fp, "damage": move.total.damage} if move.total else None,
                    "owners": owners.get(move.id, []),
                }
            )
        return out

    def set_move(self, project: HackProject, move_id: int, payload: dict) -> None:
        """Write edited FP/damage/status-chance values for one move (in
        place; the move's hit structure cannot change)."""
        path = self._attack_defs_path(project)
        data = bytearray(path.read_bytes())
        moves = {m.id: m for m in parse_dal(bytes(data))}
        move = moves.get(move_id)
        if move is None or not move.hits:
            raise ValueError(f"move {move_id} not found or not editable")

        def _check(label: str, value: int, lo: int, hi: int) -> int:
            value = int(value)
            if not (lo <= value <= hi):
                raise ValueError(f"{label} {value} out of range {lo}-{hi}")
            return value

        new_hits = payload.get("hits", [])
        if len(new_hits) != len(move.hits):
            raise ValueError("hit count mismatch (hits cannot be added or removed)")
        for hit, nh in zip(move.hits, new_hits):
            hit.fp = _check("FP cost", nh["fp"], *MOVE_FP_RANGE)
            hit.damage = _check("damage", nh["damage"], *MOVE_DAMAGE_RANGE)
        if move.total:
            total = payload.get("total")
            if total:
                move.total.fp = _check("total FP", total["fp"], *MOVE_FP_RANGE)
                move.total.damage = _check("total damage", total["damage"], *MOVE_DAMAGE_RANGE)
            else:
                move.total.fp = sum(h.fp for h in move.hits)
                move.total.damage = sum(h.damage for h in move.hits)
        if "effectChance" in payload:
            move.effect_chance = _check("effect chance", payload["effectChance"], *MOVE_CHANCE_RANGE)

        write_move(data, move)
        path.write_bytes(bytes(data))

    def _battle_path(self, project: HackProject, battle_id: int) -> Path:
        return self.rom_dir(project) / "battle_param" / f"battle_param_defs_{battle_id}"

    def list_battles(self, project: HackProject) -> list[dict]:
        """Every battle with its curated trainer/location and a one-line enemy
        summary for search/browse."""
        battle_dir = self.rom_dir(project) / "battle_param"
        if not battle_dir.exists():
            return []
        names = self._vivo_names(project)
        curation = _load_curation()
        battles = []
        for file in sorted(
            (f for f in battle_dir.iterdir() if not f.suffix and not f.name.endswith(".metadata")),
            key=lambda f: int(f.name.rsplit("_", 1)[1]),
        ):
            bid = int(file.name.rsplit("_", 1)[1])
            summary = ""
            try:
                battle = parse_dps(file.read_bytes())
                if battle:
                    enemy_names = [
                        names.get(s.vivo_id, f"#{s.vivo_id}")
                        for e in battle.entries
                        if not e.is_player_side
                        for s in e.slots
                        if s.vivo_id
                    ]
                    summary = ", ".join(enemy_names)
            except Exception:
                pass
            cur = curation.get(str(bid), {})
            battles.append(
                {
                    "id": bid,
                    "trainer": cur.get("trainer") or GENERIC_TRAINER,
                    "named": bool(cur.get("trainer")),
                    "location": cur.get("location"),
                    "summary": summary,
                }
            )
        return battles

    def battle_detail(self, project: HackProject, battle_id: int) -> dict:
        """Full battle contents: every entry, slot, and AI byte."""
        path = self._battle_path(project, battle_id)
        if not path.exists():
            raise FileNotFoundError(f"battle {battle_id} not found")
        battle = parse_dps(path.read_bytes())
        if not battle:
            raise ValueError(f"battle_param_defs_{battle_id} is not a DPS file")
        names = self._vivo_names(project)
        cur = _load_curation().get(str(battle_id), {})
        entries = []
        for e in battle.entries:
            entries.append(
                {
                    "isPlayer": e.is_player_side,
                    "preBattleMsg": e.pre_battle_msg,
                    "slots": [
                        {
                            "vivo": s.vivo_id,
                            "name": names.get(s.vivo_id, f"#{s.vivo_id}"),
                            "rank": s.rank,
                            "mult": round(s.mult / 0x1000, 4),
                            "tactic": s.tactic,
                            "hasMult": bool(s.mult_offset),
                            "hasTactic": bool(s.tac_offset),
                        }
                        for s in e.slots
                    ],
                    "ai": list(e.ai_bytes),
                }
            )
        return {
            "id": battle.battle_id,
            "trainer": cur.get("trainer") or GENERIC_TRAINER,
            "named": bool(cur.get("trainer")),
            "location": cur.get("location"),
            "entries": entries,
        }

    def set_battle(self, project: HackProject, battle_id: int, payload: dict) -> None:
        """Write edited entries back into the DPS file in place. The payload
        must mirror battle_detail's shape; structure (entry/slot/AI counts)
        cannot change, only values."""
        path = self._battle_path(project, battle_id)
        data = bytearray(path.read_bytes())
        battle = parse_dps(bytes(data))
        if not battle:
            raise ValueError(f"battle_param_defs_{battle_id} is not a DPS file")
        names = self._vivo_names(project)

        new_entries = payload.get("entries", [])
        if len(new_entries) != len(battle.entries):
            raise ValueError(
                f"entry count mismatch: file has {len(battle.entries)}, payload has {len(new_entries)}"
            )

        def _check(label: str, value, lo, hi):
            if not (lo <= value <= hi):
                raise ValueError(f"{label} {value} out of range {lo}-{hi}")

        for entry, new in zip(battle.entries, new_entries):
            new_slots = new.get("slots", [])
            if len(new_slots) != len(entry.slots):
                raise ValueError("slot count mismatch (slots cannot be added or removed)")
            for slot, ns in zip(entry.slots, new_slots):
                vivo = int(ns["vivo"])
                if vivo and vivo not in names:
                    raise ValueError(f"unknown vivosaur index {vivo}")
                rank = int(ns["rank"])
                _check("rank", rank, *BATTLE_RANK_RANGE)
                slot.vivo_id = vivo
                slot.rank = rank
                if slot.mult_offset and "mult" in ns:
                    mult = float(ns["mult"])
                    _check("stat multiplier", mult, *BATTLE_MULT_RANGE)
                    slot.mult = int(round(mult * 0x1000))
                if slot.tac_offset and "tactic" in ns:
                    tactic = int(ns["tactic"])
                    _check("tactic class", tactic, *BATTLE_TACTIC_RANGE)
                    slot.tactic = tactic
            new_ai = new.get("ai")
            if new_ai is not None and entry.ai_offset:
                if len(new_ai) != len(entry.ai_bytes):
                    raise ValueError("AI byte count mismatch")
                for value in new_ai:
                    _check("AI tactic id", int(value), *BATTLE_AI_RANGE)
                entry.ai_bytes = bytes(int(v) for v in new_ai)

        write_battle(data, battle)
        path.write_bytes(bytes(data))

    def apply_mods(self, project: HackProject, options: RandomizerOptions | None = None) -> None:
        rom_dir = self.rom_dir(project)
        if options and options.enabled:
            apply_randomizer(rom_dir, self.load_creatures(project), options)
        if project.hard_mode:
            apply_hard_mode(rom_dir)

    def build(self, project: HackProject, output: Path | None = None) -> Path:
        """Build a playable ROM by injecting the workspace's edits into a copy
        of the original ROM (ndspy). This only rewrites the files the editors
        can touch, so it is fast and cannot corrupt anything else. Falls back
        to a full carbonizer repack only when no original .nds is known."""
        options = RandomizerOptions(**project.randomizer) if project.randomizer else RandomizerOptions()
        self.apply_mods(project, options)

        out = output or (Path(project.workspace) / f"{project.name} (Hack).nds")
        base = self.find_base_rom(project)
        if base is None:
            carbonizer = Path(project.carbonizer) if project.carbonizer else find_carbonizer()
            return pack_rom(self.rom_dir(project), carbonizer, out)
        return self._build_injected(project, base, out)

    def _build_injected(self, project: HackProject, base_rom: Path, out: Path) -> Path:
        """Inject every workspace edit into a copy of the original ROM,
        preserving the original file layout (see nds_inplace.py): each
        changed file is re-encoded with its retail compression scheme and
        written back into its original slot; only files that outgrow their
        slot are relocated, using carbonizer's placement rule. Everything
        else in the ROM -- including the DSi region accurate emulators
        check -- stays byte-identical."""
        from .compression.mar import decompress_mar, repack_mar_like
        from .formats.dmg_format import build_dmg
        from .formats.dtx_format import build_dtx
        from .nds_inplace import InPlaceRom
        from .patches import element_fix

        rom_dir = self.rom_dir(project)
        rom = InPlaceRom(Path(base_rom).read_bytes())
        expected: dict[str, bytes] = {}

        def inject_if_changed(rom_path: str, payload: bytes) -> bool:
            try:
                original = rom.read_file(rom_path)
                if payload == decompress_mar(original)[0]:
                    return False
                rom.replace_file(
                    rom_path, repack_mar_like(original, [payload], fit=rom.slot_size(rom_path))
                )
            except Exception:
                return False
            expected[rom_path] = payload
            return True

        # vivosaur edits: re-encode the JSON with the verified DCL encoder
        creatures_json = self.creature_defs_path(project)
        if creatures_json.exists():
            payload = encode_dcl(json.loads(creatures_json.read_text(encoding="utf-8")))
            inject_if_changed("etc/creature_defs", payload)

        # elemental resistance fix: one constant in btl_adjust_defs, applied
        # at build time only so the toggle stays reversible (see
        # patches/element_fix.py)
        if project.element_fix:
            try:
                adjust = decompress_mar(rom.read_file("etc/btl_adjust_defs"))[0]
                inject_if_changed("etc/btl_adjust_defs", element_fix.patch_btl_adjust(adjust))
            except ValueError as err:
                raise RuntimeError(f"element fix: {err}")

        # battle, dig-record, fossil-rock and move edits: raw payload files
        battle_dir = rom_dir / "battle_param"
        if battle_dir.exists():
            for file in battle_dir.iterdir():
                if not file.suffix and not file.name.endswith(".metadata"):
                    inject_if_changed(f"battle_param/{file.name}", file.read_bytes())
        map_dir = rom_dir / "map" / "m"
        if map_dir.exists():
            for file in map_dir.iterdir():
                if not file.suffix and not file.name.endswith(".metadata"):
                    inject_if_changed(f"map/m/{file.name}", file.read_bytes())
        for etc_name in ("kaseki_defs", "attack_defs"):
            etc_file = rom_dir / "etc" / etc_name
            if etc_file.exists():
                inject_if_changed(f"etc/{etc_name}", etc_file.read_bytes())

        # text edits: re-encode the decoded JSON archives
        for info in self.list_texts(project):
            entries = self.text_entries(project, info["file"])["entries"]
            if info["kind"] == "dmg":
                payload = build_dmg([(e["index"], e["string"]) for e in entries])
            else:
                payload = build_dtx([e["string"] for e in entries])
            inject_if_changed(info["file"], payload)

        if project.hack_title:
            title = project.hack_title
            if project.author:
                title += f"\nby {project.author}"
            rom.set_banner_title(title)

        rom.save()
        out.write_bytes(rom.data)

        # verify every injected file decodes back from the written ROM
        check = InPlaceRom(out.read_bytes())
        for rom_path, payload in expected.items():
            if decompress_mar(check.read_file(rom_path))[0] != payload:
                raise RuntimeError(f"verification failed for {rom_path}")
        return out.resolve()

    def find_base_rom(self, project: HackProject) -> Path | None:
        """Best guess at the original .nds this project came from."""
        source = Path(project.source_rom)
        if source.is_file() and source.suffix.lower() == ".nds":
            return source
        return None

    def make_patch(self, project: HackProject, base_rom: Path | None = None) -> dict:
        """Build the hack ROM, then produce a shareable BPS patch against the
        original ROM. The patch is self-verified (decoded back and
        byte-compared) before being written. Returns a manifest dict."""
        base = base_rom or self.find_base_rom(project)
        if base is None or not Path(base).is_file():
            raise FileNotFoundError(
                "Original (unmodified) .nds ROM not found. A patch is a diff "
                "against the original game, so the tool needs it to compare."
            )
        base = Path(base)

        hack_rom = self.build(project)
        source = base.read_bytes()
        target = hack_rom.read_bytes()

        title = project.hack_title or project.name
        meta = f"{title} by {project.author}".encode("utf-8") if project.author else title.encode("utf-8")
        patch = encode_bps(source, target, metadata=meta)
        if decode_bps(patch, source) != target:
            raise RuntimeError("patch self-check failed: decoded patch does not reproduce the hack ROM")

        patch_path = Path(project.workspace) / f"{title}.bps"
        patch_path.write_bytes(patch)

        manifest = {
            "name": title,
            "author": project.author,
            "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "patchFile": str(patch_path),
            "patchSize": len(patch),
            "patchCrc32": f"{zlib.crc32(patch):08x}",
            "romFile": str(hack_rom),
            "romSize": len(target),
            "base": {
                "path": str(base),
                "size": len(source),
                "crc32": f"{zlib.crc32(source):08x}",
                "md5": hashlib.md5(source).hexdigest(),
            },
        }
        (Path(project.workspace) / "patch_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return manifest

    def _save_meta(self, project: HackProject) -> None:
        meta = Path(project.workspace) / "meta.json"
        meta.write_text(json.dumps(asdict(project), indent=2), encoding="utf-8")

    def save_project_settings(self, project: HackProject) -> None:
        self._save_meta(project)

    def list_projects(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and (p / "meta.json").exists())
