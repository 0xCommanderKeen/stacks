import argparse
import json
from pathlib import Path

from stacks.backup import backup, restore
from stacks.library import Library


def main():
    parser = argparse.ArgumentParser(
        description="Stacks library maintenance (stop the server first)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "export"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("restore")
    command.add_argument("archive", type=Path)
    command.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "restore":
        restore(args.archive, args.data_dir)
    else:
        if not (args.data_dir / "catalog.sqlite3").is_file():
            parser.error("No catalog exists at this data directory.")
        library = Library(args.data_dir)
        try:
            if args.command == "backup":
                backup(library, args.output)
            else:
                with args.output.open("x") as output:
                    json.dump(library.export(), output, ensure_ascii=False, indent=2)
        finally:
            library.close()
    print(f"{args.command.capitalize()} complete.")
