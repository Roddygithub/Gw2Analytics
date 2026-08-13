import hashlib
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ei-parity" / "ei_diff.py"
SPEC = importlib.util.spec_from_file_location("ei_diff", SCRIPT)
assert SPEC and SPEC.loader
ei_diff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ei_diff)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _certification_files(tmp_path):
    logs = tmp_path / "logs"
    exports = tmp_path / "exports"
    logs.mkdir()
    exports.mkdir()
    cli = tmp_path / "GuildWars2EliteInsights-CLI.dll"
    cli.write_bytes(b"cli")
    start = datetime(2026, 1, 1)
    stems = [(start + timedelta(days=index)).strftime("%Y%m%d-000000") for index in range(35)]
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("\n".join(stems) + "\n")
    entries = []
    for stem in stems:
        evtc = logs / f"{stem}.zevtc"
        export = exports / f"{stem}_detailed_wvw_kill.json"
        evtc.write_bytes(stem.encode())
        export.write_text("{}")
        entries.append(
            {
                "stem": stem,
                "date": f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}",
                "evtc_sha256": _sha256(evtc),
                "export_sha256": _sha256(export),
                "tags": [ei_diff.TAG_VOCABULARY[0]],
            }
        )
    manifest = tmp_path / "corpus-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reference": {
                    "ei_version": "3.26.0.0",
                    "cli_sha256": _sha256(cli),
                    "export_type": "detailed_wvw_kill",
                },
                "tag_vocabulary": ei_diff.TAG_VOCABULARY,
                "entries": entries,
            }
        )
    )
    return logs, exports, cli, corpus, manifest, stems


def _configure(monkeypatch, files):
    logs, exports, cli, corpus, manifest, _ = files
    monkeypatch.setattr(ei_diff, "LOGS", logs)
    monkeypatch.setattr(ei_diff, "EI_OUT", exports)
    monkeypatch.setattr(ei_diff, "EI_CLI", cli)
    monkeypatch.setattr(ei_diff, "CORPUS", corpus)
    monkeypatch.setattr(ei_diff, "MANIFEST", manifest)


def _manifest(files):
    return json.loads(files[4].read_text())


def _write_manifest(files, data):
    files[4].write_text(json.dumps(data))


def _assert_before_parsing(monkeypatch, message):
    monkeypatch.setattr(ei_diff, "run_one", lambda _stem: pytest.fail("parsed a log"))
    monkeypatch.setattr(ei_diff.sys, "argv", [str(SCRIPT)])
    with pytest.raises(SystemExit, match=message):
        ei_diff.main()


def test_manifest_and_versioned_baseline_match_canonical_corpus():
    manifest = json.loads((ROOT / "scripts/ei-parity/corpus-manifest.json").read_text())
    baseline = json.loads((ROOT / "scripts/ei-parity/corpus-baseline.json").read_text())
    corpus = (ROOT / "scripts/ei-parity/corpus.txt").read_text().splitlines()

    assert len(corpus) == len(set(corpus)) == baseline["log_count"] == 35
    assert [entry["stem"] for entry in manifest["entries"]] == corpus
    assert baseline["reference"] == manifest["reference"]
    assert baseline["manifest_sha256"] == _sha256(ROOT / "scripts/ei-parity/corpus-manifest.json")
    assert sum(baseline["buckets"].values()) == 133
    assert len(baseline["buckets"]) == 13


@pytest.mark.parametrize(
    ("artifact", "change", "message"),
    [
        ("cli", "missing", "missing EI CLI"),
        ("cli", "altered", "altered EI CLI"),
        ("evtc", "missing", "missing EVTC"),
        ("evtc", "altered", "altered EVTC"),
        ("export", "missing", "missing EI export"),
        ("export", "altered", "altered EI export"),
    ],
)
def test_missing_or_altered_artifacts_fail_before_parsing(
    monkeypatch, tmp_path, artifact, change, message
):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    path = {
        "cli": files[2],
        "evtc": files[0] / f"{files[-1][-1]}.zevtc",
        "export": files[1] / f"{files[-1][-1]}_detailed_wvw_kill.json",
    }[artifact]
    path.unlink() if change == "missing" else path.write_bytes(b"altered")

    _assert_before_parsing(monkeypatch, message)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ei_version", "3.27.0.0", "invalid EI version"),
        ("export_type", "summary", "invalid export type"),
    ],
)
def test_wrong_reference_contract_is_rejected(monkeypatch, tmp_path, field, value, message):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    data = _manifest(files)
    data["reference"][field] = value
    _write_manifest(files, data)

    _assert_before_parsing(monkeypatch, message)


@pytest.mark.parametrize(
    "stem",
    ["../private", "20260230-000000", "\uff12\uff10\uff12\uff16\uff10\uff11\uff10\uff11-000000"],
)
def test_invalid_stem_is_rejected_before_path_construction(monkeypatch, tmp_path, stem):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    data = _manifest(files)
    files[3].write_text(stem + "\n" + "\n".join(files[-1][1:]) + "\n")
    data["entries"][0]["stem"] = stem
    _write_manifest(files, data)

    _assert_before_parsing(monkeypatch, "invalid stem")


@pytest.mark.parametrize("change", ["missing", "reordered", "duplicate", "tag"])
def test_manifest_and_corpus_incoherence_is_rejected(monkeypatch, tmp_path, change):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    data = _manifest(files)
    if change == "missing":
        data["entries"].pop()
    elif change == "reordered":
        data["entries"][0], data["entries"][1] = data["entries"][1], data["entries"][0]
    elif change == "duplicate":
        data["entries"][-1] = data["entries"][0]
    else:
        data["entries"][0]["tags"] = ["unknown"]
    _write_manifest(files, data)

    _assert_before_parsing(monkeypatch, "manifest|duplicate|invalid tags")


@pytest.mark.parametrize("source", ["manifest", "corpus", "export"])
def test_invalid_unicode_is_rejected(monkeypatch, tmp_path, source):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    path = {
        "manifest": files[4],
        "corpus": files[3],
        "export": files[1] / f"{files[-1][0]}_detailed_wvw_kill.json",
    }[source]
    path.write_bytes(b"\xff")
    if source == "export":
        data = _manifest(files)
        data["entries"][0]["export_sha256"] = _sha256(path)
        _write_manifest(files, data)

    _assert_before_parsing(monkeypatch, "invalid")


def test_duplicate_manifest_key_is_rejected(monkeypatch, tmp_path):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    text = (
        files[4]
        .read_text()
        .replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
    )
    files[4].write_text(text)

    _assert_before_parsing(monkeypatch, "invalid corpus manifest")


def test_unreadable_export_json_is_rejected_before_parsing(monkeypatch, tmp_path):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    export = files[1] / f"{files[-1][0]}_detailed_wvw_kill.json"
    export.write_text("{")
    data = _manifest(files)
    data["entries"][0]["export_sha256"] = _sha256(export)
    _write_manifest(files, data)

    _assert_before_parsing(monkeypatch, "invalid .* EI export JSON")


@pytest.mark.parametrize(
    "args",
    [["20260101-000000", "20260101-000000"], ["--json", "out.json", "20260101-000000"]],
)
def test_duplicate_or_partial_positional_run_is_rejected(monkeypatch, tmp_path, args):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    monkeypatch.setattr(ei_diff.sys, "argv", [str(SCRIPT), *args])
    monkeypatch.setattr(ei_diff, "run_one", lambda _stem: pytest.fail("parsed a log"))

    with pytest.raises(SystemExit, match=r"duplicate positional stem|complete corpus"):
        ei_diff.main()


@pytest.mark.parametrize("input_name", ["cli", "corpus", "manifest", "evtc", "export"])
def test_json_destination_cannot_replace_certification_input(monkeypatch, tmp_path, input_name):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    destination = {
        "cli": files[2],
        "corpus": files[3],
        "manifest": files[4],
        "evtc": files[0] / f"{files[-1][0]}.zevtc",
        "export": files[1] / f"{files[-1][0]}_detailed_wvw_kill.json",
    }[input_name]
    monkeypatch.setattr(ei_diff.sys, "argv", [str(SCRIPT), "--json", str(destination)])
    monkeypatch.setattr(ei_diff, "run_one", lambda _stem: pytest.fail("parsed a log"))

    with pytest.raises(SystemExit, match="destination is a certification input"):
        ei_diff.main()


def test_json_baseline_is_atomic_aggregate_only_and_sorted(monkeypatch, tmp_path):
    files = _certification_files(tmp_path)
    _configure(monkeypatch, files)
    output = tmp_path / "baseline.json"
    replaced = []
    real_replace = ei_diff.os.replace

    def replace(source, destination):
        replaced.append((Path(source), Path(destination)))
        real_replace(source, destination)

    def report(stem):
        return {
            "stem": stem,
            "n_diffs": 2,
            "events": 1,
            "agents": 1,
            "ei_players": 1,
            "ei_targets": 1,
            "parse_seconds": 0,
            "rotation_missing": 0,
            "rotation_extra": 0,
            "differences": {"players[Private].z": {"expected": "A", "actual": "B"}},
            "buckets": ei_diff.Counter({"z.bucket": 1, "a.bucket": 1}),
        }

    monkeypatch.setattr(ei_diff, "run_one", report)
    monkeypatch.setattr(ei_diff.os, "replace", replace)
    monkeypatch.setattr(
        ei_diff.sys, "argv", [str(SCRIPT), "--json", str(output), "--rotation-skills", "0"]
    )

    assert ei_diff.main() == 0
    baseline = json.loads(output.read_text())
    assert list(baseline["buckets"]) == ["a.bucket", "z.bucket"]
    assert baseline["buckets"] == {"a.bucket": 35, "z.bucket": 35}
    assert replaced and replaced[0][1] == output
    assert replaced[0][0].parent == output.parent
    assert not any(word in output.read_text() for word in ("Private", "expected", "actual"))
