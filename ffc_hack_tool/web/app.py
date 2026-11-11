from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from ..project import ProjectManager
from ..randomizer import RandomizerOptions
from ..data.constants import DIGSITE_NAMES, ELEMENTS, FOSSIL_PART_NAMES, RANGES


def create_app(projects_root: Path) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    manager = ProjectManager(projects_root)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            projects=manager.list_projects(),
            elements=ELEMENTS,
            ranges=RANGES,
            digsites=DIGSITE_NAMES,
            parts=FOSSIL_PART_NAMES,
        )

    @app.get("/api/projects")
    def api_projects():
        return jsonify(manager.list_projects())

    @app.post("/api/projects")
    def api_create_project():
        body = request.get_json(force=True)
        name = body["name"].strip()
        rom = Path(body["rom"].strip().strip('"'))
        try:
            project = manager.create(name, rom)
        except Exception as err:
            return jsonify({"error": str(err)}), 400
        return jsonify(asdict(project))

    @app.get("/api/projects/<name>/creatures")
    def api_creatures(name: str):
        project = manager.load(name)
        try:
            data = manager.load_creatures(project)
        except FileNotFoundError as err:
            return jsonify({"error": str(err)}), 404
        vivosaurs = []
        for index, entry in enumerate(data.get("vivosaurs", [])):
            if not entry or not entry.get("isEntry"):
                continue
            vivosaurs.append(
                {
                    "index": index,
                    "id": entry.get("_id", index),
                    "name": entry.get("_defaultName", f"Vivosaur {index}"),
                    "element": entry.get("element"),
                    "range": entry.get("range"),
                    "digsite": entry.get("sortOrderDigsite"),
                    "stats": {
                        "attack": entry.get("stat1Attack"),
                        "defense": entry.get("stat2Defense"),
                        "accuracy": entry.get("stat3Accuracy"),
                        "speed": entry.get("stat4Speed"),
                    },
                    "healthAtEachRank": entry.get("healthAtEachRank", []),
                    "skills": entry.get("skillIDs", []),
                    "raw": entry,
                }
            )
        return jsonify(vivosaurs)

    SUPPORT_KEYS = ("supportEffectsForAlly", "supportEffectsForEnemy")
    SUPPORT_STATS = ("attack", "defense", "accuracy", "speed")

    def _check_support_effects(raw: dict) -> str | None:
        """Support effects must be the exact 4-stat shape the DCL encoder
        packs as signed bytes; the game uses the -99..99 percent range."""
        for key in SUPPORT_KEYS:
            effects = raw.get(key)
            if effects is None:
                continue
            if not isinstance(effects, dict) or set(effects) != set(SUPPORT_STATS):
                return f"{key} must have exactly these fields: {', '.join(SUPPORT_STATS)}"
            for stat, value in effects.items():
                if not isinstance(value, int) or not (-100 <= value <= 100):
                    return f"{key}.{stat} must be a whole number from -100 to 100"
        return None

    @app.put("/api/projects/<name>/creatures/<int:index>")
    def api_update_creature(name: str, index: int):
        project = manager.load(name)
        data = manager.load_creatures(project)
        body = request.get_json(force=True)
        if index >= len(data.get("vivosaurs", [])):
            return jsonify({"error": "Invalid index"}), 404
        error = _check_support_effects(body["raw"])
        if error:
            return jsonify({"error": error}), 400
        data["vivosaurs"][index] = body["raw"]
        manager.save_creatures(project, data)
        return jsonify({"ok": True})

    @app.get("/api/projects/<name>/fossils")
    def api_fossils(name: str):
        project = manager.load(name)
        return jsonify(manager.list_dig_sites(project))

    @app.put("/api/projects/<name>/fossils/<map_id>")
    def api_update_fossil(name: str, map_id: str):
        project = manager.load(name)
        body = request.get_json(force=True)
        replace = {int(k): int(v) for k, v in body.get("replace", {}).items()}
        changed = manager.set_dig_site(project, map_id, replace)
        return jsonify({"ok": True, "changed": changed})

    @app.get("/api/projects/<name>/vivosaur-names")
    def api_vivosaur_names(name: str):
        project = manager.load(name)
        try:
            creatures = manager.load_creatures(project)
        except FileNotFoundError as err:
            return jsonify({"error": str(err)}), 404
        return jsonify(
            [
                {"index": i, "name": e.get("_defaultName", f"Vivosaur {i}")}
                for i, e in enumerate(creatures.get("vivosaurs", []))
                if e and e.get("isEntry")
            ]
        )

    @app.get("/api/projects/<name>/fossils/<map_id>/records")
    def api_fossil_records(name: str, map_id: str):
        project = manager.load(name)
        try:
            return jsonify(manager.dig_site_records(project, map_id))
        except FileNotFoundError as err:
            return jsonify({"error": str(err)}), 404

    @app.put("/api/projects/<name>/fossils/<map_id>/records")
    def api_update_fossil_records(name: str, map_id: str):
        project = manager.load(name)
        body = request.get_json(force=True)
        changed, errors = manager.set_dig_records(project, map_id, body.get("changes", []))
        return jsonify({"ok": not errors, "changed": changed, "errors": errors})

    @app.get("/api/projects/<name>/battles")
    def api_battles(name: str):
        project = manager.load(name)
        return jsonify(manager.list_battles(project))

    @app.get("/api/projects/<name>/battles/<int:battle_id>")
    def api_battle_detail(name: str, battle_id: int):
        project = manager.load(name)
        try:
            return jsonify(manager.battle_detail(project, battle_id))
        except FileNotFoundError as err:
            return jsonify({"error": str(err)}), 404
        except ValueError as err:
            return jsonify({"error": str(err)}), 400

    @app.put("/api/projects/<name>/battles/<int:battle_id>")
    def api_update_battle(name: str, battle_id: int):
        project = manager.load(name)
        body = request.get_json(force=True)
        try:
            manager.set_battle(project, battle_id, body)
        except (FileNotFoundError, ValueError) as err:
            return jsonify({"error": str(err)}), 400
        return jsonify({"ok": True})

    @app.get("/api/projects/<name>/moves")
    def api_moves(name: str):
        project = manager.load(name)
        try:
            return jsonify(manager.list_moves(project))
        except FileNotFoundError as err:
            return jsonify({"error": str(err)}), 404

    @app.put("/api/projects/<name>/moves/<int:move_id>")
    def api_update_move(name: str, move_id: int):
        project = manager.load(name)
        body = request.get_json(force=True)
        try:
            manager.set_move(project, move_id, body)
        except (FileNotFoundError, ValueError, KeyError) as err:
            return jsonify({"error": str(err)}), 400
        return jsonify({"ok": True})

    @app.get("/api/projects/<name>/texts")
    def api_texts(name: str):
        project = manager.load(name)
        return jsonify(manager.list_texts(project))

    @app.get("/api/projects/<name>/texts/entries")
    def api_text_entries(name: str):
        project = manager.load(name)
        rel = request.args.get("file", "")
        try:
            return jsonify(manager.text_entries(project, rel))
        except FileNotFoundError as err:
            return jsonify({"error": str(err)}), 404

    @app.put("/api/projects/<name>/texts/entries")
    def api_update_text_entries(name: str):
        project = manager.load(name)
        body = request.get_json(force=True)
        rel = body.get("file", "")
        try:
            changed = manager.set_text_entries(project, rel, body.get("entries", []))
        except (FileNotFoundError, ValueError, KeyError) as err:
            return jsonify({"error": str(err)}), 400
        return jsonify({"ok": True, "changed": changed})

    @app.get("/api/projects/<name>/texts/search")
    def api_search_texts(name: str):
        project = manager.load(name)
        query = request.args.get("q", "").strip()
        if len(query) < 2:
            return jsonify([])
        return jsonify(manager.search_texts(project, query))

    @app.get("/api/projects/<name>/settings")
    def api_settings(name: str):
        project = manager.load(name)
        return jsonify(
            {
                "randomizer": project.randomizer,
                "hard_mode": project.hard_mode,
                "element_fix": project.element_fix,
                "notes": project.notes,
                "author": project.author,
                "hack_title": project.hack_title,
            }
        )

    @app.put("/api/projects/<name>/settings")
    def api_update_settings(name: str):
        project = manager.load(name)
        body = request.get_json(force=True)
        project.randomizer = body.get("randomizer", project.randomizer)
        project.hard_mode = bool(body.get("hard_mode", project.hard_mode))
        project.element_fix = bool(body.get("element_fix", project.element_fix))
        if "notes" in body:
            project.notes = str(body["notes"])
        if "author" in body:
            project.author = str(body["author"]).strip()
        if "hack_title" in body:
            project.hack_title = str(body["hack_title"]).strip()
        manager.save_project_settings(project)
        return jsonify({"ok": True})

    @app.get("/api/projects/<name>/meta")
    def api_meta(name: str):
        project = manager.load(name)
        base = manager.find_base_rom(project)
        return jsonify(
            {
                **asdict(project),
                "base_rom": str(base) if base else "",
                "workspace": project.workspace,
            }
        )

    @app.post("/api/projects/<name>/build")
    def api_build(name: str):
        project = manager.load(name)
        try:
            output = manager.build(project)
        except Exception as err:
            return jsonify({"error": str(err)}), 500
        return jsonify({"output": str(output)})

    @app.post("/api/projects/<name>/patch")
    def api_patch(name: str):
        project = manager.load(name)
        body = request.get_json(force=True) if request.data else {}
        base = body.get("base_rom", "").strip()
        try:
            manifest = manager.make_patch(project, Path(base) if base else None)
        except Exception as err:
            return jsonify({"error": str(err)}), 500
        return jsonify(manifest)

    return app


def run_server(host: str, port: int, projects_root: Path, open_browser: bool = True) -> None:
    app = create_app(projects_root)
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}/")).start()
    app.run(host=host, port=port, debug=False)
