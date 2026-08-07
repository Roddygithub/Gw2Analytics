#!/usr/bin/env python3
"""Dump every ``InstantCastFinder`` rule declared in Elite Insights' sources.

The WvW corpus only ever deviates from EI on skills that have an instant-cast
*finder*: EH the friend transcribed the seven they could isolate by hand, the
remaining ~500 are still only reachable by reading EI's declarative rules out
of its per-profession ``*Helper.cs`` files. This turns those declarations into
one queryable list, resolved against ``SkillIDs.cs``, so a missing skill can be
found and transcribed with ``probe_ei_finders.py``.

Read-only by design: it only reports. Transcribing stays a manual,
``probe_ei_finders.py``-verified step.

Usage:
    dump_ei_finders.py --json              # machine-readable rows
    dump_ei_finders.py --core-only         # drop EXT_* heal/barrier finders
    dump_ei_finders.py --only Guardian     # one profession
    dump_ei_finders.py --filter BuffGain   # one finder kind
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EL_CANDIDATES = [ROOT / ".tooling" / "ei-src", Path("/tmp/opencode/ei-src")]  # noqa: S108
PARSER_REL = "GW2EIEvtcParser"

#: ``new <Finder>(args...)`` — optional namespace prefix on the finder name.
_FINDER_RE = re.compile(r"\bnew\s+(?P<finder>[A-Za-z]+CastFinder)\s*\((?P<args>[^()]*)\)")
#: ``public const long NAME = value;``
_CONST_RE = re.compile(r"public\s+const\s+long\s+(\w+)\s*=\s*(-?\d+)\s*;")

#: Finder types that credit a player rotation entry in the WvW context.
_CORE_FINDERS = {
    "DamageCastFinder",
    "EffectCastFinder",
    "EffectCastFinderByDst",
    "BuffGainCastFinder",
    "BuffLossCastFinder",
    "BuffGiveCastFinder",
    "BuffExtendCastFinder",
    "MinionCastCastFinder",
    "MinionSpawnCastFinder",
    "MinionCommandCastFinder",
    "WeaponSwapCastFinder",
    "MissileCastFinder",
    "MarkerCastFinder",
    "CheckedCastFinder",
}


def find_ei_root() -> Path:
    for cand in EL_CANDIDATES:
        if (cand / PARSER_REL).exists():
            return cand
    raise FileNotFoundError(
        "No Elite Insights checkout at .tooling/ei-src or /tmp/opencode/ei-src."
    )


def load_skill_ids(root: Path) -> dict[str, int]:
    path = root / PARSER_REL / "ParserHelpers/IDs/SkillIDs.cs"
    return {
        name: int(value)
        for name, value in _CONST_RE.findall(path.read_text())
        if not value.lstrip("-").isdigit() or int(value) >= 0
    }


def helper_files(root: Path) -> list[tuple[str, str]]:
    base = root / PARSER_REL / "EIData/ProfHelpers"
    out = []
    for path in sorted(base.rglob("*Helper.cs")):
        text = path.read_text()
        if "CastFinder" in text and "new " in text:
            out.append((path.parent.name, text))
    return out


def rows(root: Path, *, prof_dir: str | None = None, kind: str | None = None) -> list[dict]:
    ids = load_skill_ids(root)
    out = []
    for prof, text in helper_files(root):
        if prof_dir and prof != prof_dir:
            continue
        for m in _FINDER_RE.finditer(text):
            finder = m["finder"]
            if kind and finder not in kind:
                continue
            args = [a.strip() for a in m["args"].split(",")]
            first = args[0] if args else ""
            out.append(
                {
                    "profession": prof,
                    "finder": finder,
                    "skill_name": first,
                    "skill_id": ids.get(first),
                    "args": m["args"],
                    "core": finder in _CORE_FINDERS,
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ei", help="EI checkout root (default auto)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--core-only", action="store_true")
    ap.add_argument("--only", help="one profession dir, e.g. Guardian")
    ap.add_argument("--filter", help="one finder kind, e.g. BuffGain")
    args = ap.parse_args()

    root = Path(args.ei) if args.ei else find_ei_root()
    all_rows = rows(root, prof_dir=args.only, kind=args.filter)

    if args.core_only:
        all_rows = [r for r in all_rows if r["core"]]

    by_prof = defaultdict(list)
    for r in all_rows:
        by_prof[r["profession"]].append(r)

    if args.json:
        print(json.dumps(all_rows, indent=2, default=str))
        return 0

    resolved = sum(1 for r in all_rows if r["skill_id"] is not None)
    print(f"EI root: {root}")
    print(f"Total: {len(all_rows)} decls, {resolved} with resolved skill_id")
    for prof in sorted(by_prof):
        lrows = by_prof[prof]
        print(f"\n[{prof}] {len(lrows)}")
        for r in lrows:
            sid = r["skill_id"]
            sid_s = str(sid) if sid is not None else "?"
            suffix = "" if r["core"] else " (ext)"
            print(f"  {r['finder']:<26} {r['skill_name']:<30} -> {sid_s}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
