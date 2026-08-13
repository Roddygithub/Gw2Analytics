#!/usr/bin/env python3
"""Run the in-house parser against EI reference JSON and categorise the deltas.

Usage:
    uv run python .tooling/ei_diff.py [--json out.json] [log-stem ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "zevtc files"
EI_OUT = ROOT / ".tooling" / "ei-out"
CORPUS = Path(__file__).resolve().parent / "corpus.txt"
MANIFEST = Path(__file__).resolve().parent / "corpus-manifest.json"
EI_CLI = ROOT / ".tooling" / "GW2EICLI" / "GuildWars2EliteInsights-CLI.dll"

EI_VERSION = "3.26.0.0"
EXPORT_TYPE = "detailed_wvw_kill"
MANIFEST_KEYS = {"schema_version", "reference", "tag_vocabulary", "entries"}
REFERENCE_KEYS = {"ei_version", "cli_sha256", "export_type"}
ENTRY_KEYS = {"stem", "date", "evtc_sha256", "export_sha256", "tags"}
SHA256 = re.compile(r"[0-9a-f]{64}")
STEM = re.compile(r"[0-9]{8}-[0-9]{6}")
TAG_VOCABULARY = [
    "monthly-size-1",
    "monthly-size-2",
    "monthly-size-3",
    "monthly-size-4",
    "monthly-supplement",
    "pre-2026-05-07-format",
    "post-2026-05-07-format",
]

KNOWN_ROTATION_DEAD_ENDS = {
    -41,
    -37,
    -29,
    -14,
    -11,
    -7,
    -6,
    1066,
    13046,
    29560,
    43470,
    44663,
    62834,
    62887,
    62975,
}

from gw2_analytics.ei_compare import compare_elite_insights  # noqa: E402
from gw2_evtc_parser import (  # noqa: E402
    PythonEvtcParser,
    read_zevtc_archive,
    scan_agent_awareness,
    scan_regeneration_overstacks,
)

_BRACKET = re.compile(r"\[[^\]]*\]")


def bucket(key: str) -> str:
    """Collapse ``players[foo.1234].statsAll.totalDmg`` -> ``players.statsAll.totalDmg``."""
    return _BRACKET.sub("", key)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(message: str) -> None:
    raise SystemExit(f"certification refused: {message}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load_json(path: Path, label: str, *, reject_duplicates: bool = False) -> object:
    try:
        text = path.read_bytes().decode("utf-8")
        return json.loads(text, object_pairs_hook=_unique_object if reject_duplicates else None)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail(f"invalid {label}")


def _validate_stem(stem: object) -> str:
    if not isinstance(stem, str) or not STEM.fullmatch(stem):
        _fail("invalid stem")
    try:
        parsed = datetime.strptime(stem, "%Y%m%d-%H%M%S")
    except ValueError:
        _fail(f"{stem}: invalid stem")
    if parsed.strftime("%Y%m%d-%H%M%S") != stem:
        _fail(f"{stem}: invalid stem")
    return stem


def _check_artifact(stem: str, artifact: str, path: Path, expected_sha256: object) -> None:
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        _fail(f"{stem}: invalid {artifact} SHA-256")
    if not path.is_file():
        _fail(f"{stem}: missing {artifact}")
    if _sha256(path) != expected_sha256:
        _fail(f"{stem}: altered {artifact}")


def validate_corpus() -> tuple[list[str], str, dict[str, object]]:  # noqa: PLR0912
    """Validate the complete certification corpus before any log is parsed."""
    try:
        manifest_bytes = MANIFEST.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _fail("invalid corpus manifest")
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        _fail("invalid corpus manifest fields")
    if manifest["schema_version"] != 1:
        _fail("invalid corpus manifest schema version")

    reference = manifest["reference"]
    if not isinstance(reference, dict) or set(reference) != REFERENCE_KEYS:
        _fail("invalid reference fields")
    if reference["ei_version"] != EI_VERSION:
        _fail("invalid EI version")
    if reference["export_type"] != EXPORT_TYPE:
        _fail("invalid export type")
    _check_artifact("corpus", "EI CLI", EI_CLI, reference["cli_sha256"])

    vocabulary = manifest["tag_vocabulary"]
    if vocabulary != TAG_VOCABULARY:
        _fail("invalid tag vocabulary")
    allowed_tags = set(vocabulary)

    try:
        corpus = [
            line.strip()
            for line in CORPUS.read_bytes().decode("utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeDecodeError):
        _fail("invalid corpus.txt")
    corpus = [_validate_stem(stem) for stem in corpus]
    if len(corpus) != 35 or len(corpus) != len(set(corpus)):
        _fail("corpus.txt must contain 35 unique stems")
    entries = manifest["entries"]
    if not isinstance(entries, list) or len(entries) != len(corpus):
        _fail("manifest must contain exactly one entry per corpus stem")

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            _fail("invalid manifest entry fields")
        stem = _validate_stem(entry["stem"])
        if stem in seen:
            _fail(f"{stem}: duplicate manifest entry")
        seen.add(stem)
        if stem != corpus[index]:
            _fail(f"{stem}: manifest order differs from corpus.txt")
        if entry["date"] != f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}":
            _fail(f"{stem}: invalid date")
        tags = entry["tags"]
        if (
            not isinstance(tags, list)
            or not tags
            or any(not isinstance(tag, str) for tag in tags)
            or len(tags) != len(set(tags))
            or not set(tags) <= allowed_tags
        ):
            _fail(f"{stem}: invalid tags")
        _check_artifact(stem, "EVTC", LOGS / f"{stem}.zevtc", entry["evtc_sha256"])
        export_path = EI_OUT / f"{stem}_{EXPORT_TYPE}.json"
        _check_artifact(stem, "EI export", export_path, entry["export_sha256"])
        _load_json(export_path, f"{stem}: EI export JSON")

    return corpus, hashlib.sha256(manifest_bytes).hexdigest(), reference


def _validate_baseline_destination(path: Path, corpus: list[str]) -> Path:
    destination = path.resolve()
    inputs = {MANIFEST.resolve(), CORPUS.resolve(), EI_CLI.resolve()}
    inputs.update((LOGS / f"{stem}.zevtc").resolve() for stem in corpus)
    inputs.update((EI_OUT / f"{stem}_{EXPORT_TYPE}.json").resolve() for stem in corpus)
    if destination in inputs:
        _fail("baseline destination is a certification input")
    return destination


def _write_baseline(destination: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)  # noqa: PTH105 - atomic replacement is required
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        _fail("unable to write baseline")


def _rotation_deltas(diffs: dict[str, object]) -> tuple[Counter[int], Counter[int]]:
    missing: Counter[int] = Counter()
    extra: Counter[int] = Counter()
    for key, value in diffs.items():
        if not key.endswith(".rotation") or not isinstance(value, dict):
            continue
        expected_casts = {tuple(c) for c in value.get("expected") or ()}
        actual_casts = {tuple(c) for c in value.get("actual") or ()}
        missing.update(int(cast[0]) for cast in expected_casts - actual_casts if cast)
        extra.update(int(cast[0]) for cast in actual_casts - expected_casts if cast)
    return missing, extra


def _print_rotation_skill_deltas(
    reports: list[dict[str, object]],
    limit: int,
    *,
    show_known_dead_ends: bool,
) -> None:
    missing_by_skill: Counter[int] = Counter()
    extra_by_skill: Counter[int] = Counter()
    names: dict[int, str] = {}
    for rep in reports:
        missing_by_skill.update(rep["rotation_missing_by_skill"])
        extra_by_skill.update(rep["rotation_extra_by_skill"])
        names.update(rep["skill_names"])

    print(f"\n=== TOP {limit} rotation skill deltas ===")
    print(" missing  extra  skill")
    skills = set(missing_by_skill) | set(extra_by_skill)
    if not show_known_dead_ends:
        skipped = skills & KNOWN_ROTATION_DEAD_ENDS
        skills -= KNOWN_ROTATION_DEAD_ENDS
        if skipped:
            print(f" skipped {len(skipped)} known dead-end skills")
    ranked = sorted(
        skills,
        key=lambda skill_id: (
            missing_by_skill[skill_id] + extra_by_skill[skill_id],
            missing_by_skill[skill_id],
        ),
        reverse=True,
    )
    for skill_id in ranked[:limit]:
        name = names.get(skill_id, "?")
        print(f"{missing_by_skill[skill_id]:>8} {extra_by_skill[skill_id]:>6}  {skill_id} {name}")


def run_one(stem: str) -> dict[str, object]:
    log_path = LOGS / f"{stem}.zevtc"
    ei_path = EI_OUT / f"{stem}_{EXPORT_TYPE}.json"

    started = time.monotonic()
    raw = read_zevtc_archive(log_path)
    parser = PythonEvtcParser()
    fight = next(parser.parse(raw))
    events = list(parser.parse_events(raw))
    parse_s = time.monotonic() - started

    expected = json.loads(ei_path.read_text())
    result = compare_elite_insights(
        fight,
        expected,
        events,
        scan_agent_awareness(raw),
        scan_regeneration_overstacks(raw),
    )
    diffs = result["differences"]
    if not isinstance(diffs, dict):  # pragma: no cover - contract of compare_elite_insights
        raise TypeError(f"expected a differences mapping, got {type(diffs).__name__}")

    # ``rotation`` is one difference key per player carrying the whole cast
    # list, so the bucket count only moves when a player's list matches
    # *exactly*. Wiring a single instant-cast finder can remove dozens of
    # missing casts and still show zero progress -- or hide a net regression,
    # if it also adds spurious ones. Count both sides separately.
    missing_by_skill, extra_by_skill = _rotation_deltas(diffs)
    skill_names = {
        int(skill_id[1:]): data["name"]
        for skill_id, data in expected.get("skillMap", {}).items()
        if skill_id.startswith("s") and isinstance(data, dict) and data.get("name")
    }

    return {
        "rotation_missing": sum(missing_by_skill.values()),
        "rotation_extra": sum(extra_by_skill.values()),
        "rotation_missing_by_skill": missing_by_skill,
        "rotation_extra_by_skill": extra_by_skill,
        "skill_names": skill_names,
        "stem": stem,
        "parse_seconds": round(parse_s, 2),
        "events": len(events),
        "agents": len(fight.agents),
        "ei_players": len(expected.get("players", [])),
        "ei_targets": len(expected.get("targets", [])),
        "n_diffs": len(diffs),
        "differences": diffs,
        "buckets": Counter(bucket(k) for k in diffs),
    }


def main() -> int:  # noqa: PLR0912
    ap = argparse.ArgumentParser()
    ap.add_argument("stems", nargs="*")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument(
        "--rotation-skills",
        type=int,
        default=15,
        help="print top rotation skill deltas",
    )
    ap.add_argument(
        "--show-known-rotation-dead-ends",
        action="store_true",
        help="include rotation skills already proven noisy or regressive",
    )
    ap.add_argument("--show", default=None, help="print raw diffs whose bucket matches this regex")
    args = ap.parse_args()

    corpus, manifest_sha256, reference = validate_corpus()
    if len(args.stems) != len(set(args.stems)):
        _fail("duplicate positional stem")
    for stem in args.stems:
        _validate_stem(stem)
    unknown_stems = set(args.stems) - set(corpus)
    if unknown_stems:
        _fail("requested stem is not in corpus.txt")
    if args.json_out and args.stems:
        _fail("baseline output requires the complete corpus")
    json_out = (
        _validate_baseline_destination(Path(args.json_out), corpus) if args.json_out else None
    )
    stems = args.stems or corpus
    reports = []
    grand = Counter()
    for stem in stems:
        rep = run_one(stem)
        reports.append(rep)
        grand.update(rep["buckets"])
        print(
            f"{stem}: {rep['n_diffs']:>6} diffs  "
            f"({rep['events']} events, {rep['agents']} agents, "
            f"{rep['ei_players']} EI players, {rep['ei_targets']} EI targets, "
            f"{rep['parse_seconds']}s)",
            flush=True,
        )

    missing = sum(int(r["rotation_missing"]) for r in reports)
    extra = sum(int(r["rotation_extra"]) for r in reports)
    print(f"\n=== TOTAL {sum(grand.values())} differences across {len(reports)} logs ===")
    if missing or extra:
        print(
            f"    (rotation: {missing} casts missing, {extra} extra -- the bucket "
            f"below counts player rows, not casts)"
        )
    for key, count in grand.most_common(args.top):
        print(f"{count:>8}  {key}")

    if args.rotation_skills and (missing or extra):
        _print_rotation_skill_deltas(
            reports,
            args.rotation_skills,
            show_known_dead_ends=args.show_known_rotation_dead_ends,
        )

    if args.show:
        pat = re.compile(args.show)
        print(f"\n=== samples matching /{args.show}/ ===")
        shown = 0
        for rep in reports:
            for key, value in rep["differences"].items():
                if pat.search(bucket(key)) and shown < 25:
                    print(f"[{rep['stem']}] {key}\n    {json.dumps(value)[:400]}")
                    shown += 1

    if json_out is not None:
        _write_baseline(
            json_out,
            json.dumps(
                {
                    "reference": reference,
                    "manifest_sha256": manifest_sha256,
                    "log_count": len(reports),
                    "buckets": dict(sorted(grand.items())),
                },
                indent=2,
            )
            + "\n",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
