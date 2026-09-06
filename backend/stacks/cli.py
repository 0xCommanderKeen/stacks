import argparse
import json
from pathlib import Path

from stacks.backup import backup, restore
from stacks.library import Library
from stacks.thumbnails import rebuild


def main():
    parser = argparse.ArgumentParser(
        description="Stacks library maintenance (stop the server first)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "export"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "backup":
            command.add_argument("--mode", choices=("catalog", "full"), default="catalog")
    command = commands.add_parser("restore")
    command.add_argument("archive", type=Path)
    command.add_argument("--data-dir", type=Path, required=True)
    command.add_argument("--allow-missing-originals", action="store_true")
    command = commands.add_parser("rebuild-thumbnails")
    command.add_argument("--data-dir", type=Path, required=True)
    command.add_argument(
        "--sources", type=Path, help="JSON file mapping source aliases to absolute paths"
    )
    args = parser.parse_args()
    if args.command == "restore":
        restore(args.archive, args.data_dir, allow_missing_originals=args.allow_missing_originals)
    else:
        if not (args.data_dir / "catalog.sqlite3").is_file():
            parser.error("No catalog exists at this data directory.")
        sources = {}
        if args.command == "rebuild-thumbnails" and args.sources:
            sources = {
                name: Path(value) for name, value in json.loads(args.sources.read_text()).items()
            }
            if any(not path.is_absolute() for path in sources.values()):
                parser.error("Source paths must be absolute.")
        library = Library(args.data_dir, sources=sources)
        try:
            if args.command == "backup":
                backup(library, args.output, mode=args.mode)
            elif args.command == "rebuild-thumbnails":
                result = rebuild(library)
                print(json.dumps(result))
                if result["unavailable"]:
                    raise SystemExit(1)
            else:
                with args.output.open("x") as output:
                    json.dump(library.export(), output, ensure_ascii=False, indent=2)
        finally:
            library.close()
    print(f"{args.command.capitalize()} complete.")
