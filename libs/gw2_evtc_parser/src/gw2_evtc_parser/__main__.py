"""Command-line interface for the EVTC parser.

Usage::

    gw2-parser dump-agents <file.zevtc>            # Print every agent
    gw2-parser dump-agents <file.zevtc> --json     # One JSON line per agent
    gw2-parser inspect-zip <file.zevtc>             # ZIP entries + first 16 bytes of inner

The detected build version is printed to stderr so it stays out of the
piped payload.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from gw2_core import Fight
from gw2_evtc_parser.exceptions import EvtcParseError, UnsupportedVersionError
from gw2_evtc_parser.parser import PythonEvtcParser, read_zevtc_archive


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gw2-parser",
        description="Read arcdps EVTC combat logs.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump-agents", help="List every agent in the log.")
    p_dump.add_argument("file", type=Path, help="Path to a .zevtc or .evtc file")
    p_dump.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object per agent instead of a human-readable table.",
    )

    p_inspect = sub.add_parser("inspect-zip", help="Dump the zip layout of a .zevtc file.")
    p_inspect.add_argument("file", type=Path)

    return parser


def _print_human(fight: Fight) -> None:
    """Human-readable table dump."""
    header = fight.header
    if header is not None:
        sys.stderr.write(
            f"# build={header.build_version}  encounter_id={header.encounter_id}"
            f"  agents={header.agent_count}  fight_id={fight.id[:12]}\n",
        )
    for a in fight.agents:
        prof_label = a.profession.name if a.profession.value > 0 else f"PROF({a.profession.value})"
        elite_label = a.elite.name if a.elite.value > 0 else f"ELITE({a.elite_raw})"
        marker = "P" if a.is_player else "."
        print(f"{marker}  {a.id:<20d}  {a.name:<32.32}  {prof_label:<14.14}  {elite_label}")


def _print_json(fight: Fight) -> None:
    for a in fight.agents:
        print(
            json.dumps(
                {
                    "id": a.id,
                    "name": a.name,
                    "profession": a.profession.name,
                    "profession_id": a.profession.value,
                    "elite": a.elite.name,
                    "elite_raw": a.elite_raw,
                    "is_player": a.is_player,
                },
                ensure_ascii=False,
            ),
        )


def cmd_dump_agents(args: argparse.Namespace) -> int:
    raw = _load_payload(args.file)
    parser = PythonEvtcParser()
    try:
        fights = list(parser.parse(raw))
    except (EvtcParseError, UnsupportedVersionError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    if not fights:
        sys.stderr.write("ERROR: parser yielded no fights\n")
        return 1
    fight = fights[0]
    if args.json:
        _print_json(fight)
    else:
        _print_human(fight)
    return 0


def cmd_inspect_zip(args: argparse.Namespace) -> int:
    try:
        with zipfile.ZipFile(args.file, "r") as zf:
            print(f"# {args.file} -- {len(zf.namelist())} entries")
            for name in zf.namelist():
                info = zf.getinfo(name)
                print(f"  {name:<40s}  uncompressed={info.file_size}")
                if info.file_size > 0:
                    head = zf.read(name)[:16]
                    print(f"    head: {head!r}")
    except zipfile.BadZipFile as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    return 0


def _load_payload(path: Path) -> bytes:
    if path.suffix.lower() == ".zevtc":
        return read_zevtc_archive(path)
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "dump-agents":
        return cmd_dump_agents(args)
    if args.cmd == "inspect-zip":
        return cmd_inspect_zip(args)
    sys.stderr.write(f"Unknown command: {args.cmd}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
