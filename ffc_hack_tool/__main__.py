import argparse
from pathlib import Path

from .project import ProjectManager
from .carbonizer import find_carbonizer


def main() -> None:
    parser = argparse.ArgumentParser(description="Fossil Fighters Champions ROM Hack Tool")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="Launch the web editor")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8765)
    gui.add_argument("--projects", default="projects")
    gui.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")

    create = sub.add_parser("create", help="Create a project from a ROM")
    create.add_argument("name")
    create.add_argument("rom")
    create.add_argument("--projects", default="projects")
    create.add_argument("--carbonizer", default="")

    build = sub.add_parser("build", help="Build a patched ROM")
    build.add_argument("name")
    build.add_argument("--output", default="")
    build.add_argument("--projects", default="projects")

    args = parser.parse_args()

    if args.command == "gui":
        from .web.app import run_server

        run_server(args.host, args.port, Path(args.projects), open_browser=not args.no_browser)
    elif args.command == "create":
        manager = ProjectManager(Path(args.projects))
        carbonizer = Path(args.carbonizer) if args.carbonizer else None
        project = manager.create(args.name, Path(args.rom), carbonizer)
        print(f"Created project '{project.name}' at {project.workspace}")
    elif args.command == "build":
        manager = ProjectManager(Path(args.projects))
        project = manager.load(args.name)
        output = Path(args.output) if args.output else None
        result = manager.build(project, output)
        print(f"Built ROM: {result}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
