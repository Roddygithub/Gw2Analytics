import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "ops" / "private-corpus" / "executor.py"
SPEC = importlib.util.spec_from_file_location("private_executor", EXECUTOR)
assert SPEC and SPEC.loader
private_executor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(private_executor)


def request(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": "phase8-test",
        "purpose": "validation",
        "scope": "subset",
        "why_private_data": "synthetic validation",
        "worktree_ref": "synthetic-private-tests",
        "command_profile": "parser-validation-readonly",
        "selection_ref": "synthetic-subset-token",
        "requested_output": "status only",
        "authorization_token": "a" * 16,
    }
    value.update(changes)
    return value


def registry() -> dict[str, object]:
    return {
        "synthetic": True,
        "corpus_root": str(private_executor.SYNTHETIC_ROOT),
        "allowed_purposes": ["validation"],
        "worktrees": {"synthetic-private-tests": "/synthetic"},
        "selections": {"synthetic-subset-token": "fixture"},
    }


def test_subset_and_full_resolve_only_inside_the_registered_root(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    subset = root / "subset"
    subset.mkdir(parents=True)
    source_registry = {
        "corpus_root": str(root),
        "worktrees": {"synthetic-private-tests": "/synthetic"},
        "selections": {"synthetic-subset-token": "subset"},
    }
    assert private_executor._source_for(request(), source_registry) == subset
    assert (
        private_executor._source_for(
            request(scope="full", full_confirmation="confirm full", authorization_token="c" * 16),
            source_registry,
        )
        == root
    )
    source_registry["selections"] = {"synthetic-subset-token": "../outside"}
    with pytest.raises(SystemExit):
        private_executor._source_for(request(), source_registry)
    source_registry["selections"] = {"synthetic-subset-token": "."}
    with pytest.raises(SystemExit):
        private_executor._source_for(request(), source_registry)


def test_registered_worktree_is_resolved_and_limited_to_unit_writable_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(private_executor, "WORKTREE_BASE", tmp_path.resolve())
    source_registry = {"worktrees": {"synthetic-private-tests": str(worktree)}}
    assert private_executor._worktree_for(request(), source_registry) == worktree
    source_registry["worktrees"] = {"synthetic-private-tests": str(tmp_path.parent)}
    with pytest.raises(SystemExit):
        private_executor._worktree_for(request(), source_registry)


def test_mount_and_cleanup_use_private_runtime_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> object:
        calls.append(argv)
        return SimpleNamespace(returncode=0)

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(private_executor.subprocess, "run", run)
    private_executor._mount_source(source, runtime)
    private_executor._cleanup("a" * 16, runtime)
    assert ["/usr/bin/mount", "--bind", str(source), str(runtime / "source")] in calls
    assert any(command[0] == "/usr/bin/umount" for command in calls)
    assert not runtime.exists()


def test_consumed_token_is_an_atomic_persistent_tombstone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(private_executor, "CONSUMED_TOKENS", tmp_path / "consumed")
    token = "d" * 16
    private_executor._consume_token(token, request(authorization_token=token))
    tombstone = private_executor.CONSUMED_TOKENS / token
    assert json.loads(tombstone.read_text()) == {
        "task_id": "phase8-test",
        "scope": "subset",
        "command_profile": "parser-validation-readonly",
    }
    with pytest.raises(SystemExit):
        private_executor._consume_token(token, request(authorization_token=token))


def test_diagnostic_is_ttl_bounded_and_redacts_request_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(private_executor, "DIAGNOSTICS", tmp_path / "diagnostics")
    monkeypatch.setattr(private_executor.time, "time", lambda: 1000)
    diagnostic_id = "z" * 16
    request_data = request(why_private_data="sensitive reason", requested_output="sensitive output")
    private_executor._record_diagnostic(diagnostic_id, request_data, "validated", "registry")
    artifact = private_executor.read_diagnostic(diagnostic_id)
    assert artifact["stage"] == "validated"
    assert artifact["expires_at"] == 1600
    serialized = json.dumps(artifact)
    assert "sensitive reason" not in serialized
    assert "sensitive output" not in serialized
    assert "worktree" not in serialized
    monkeypatch.setattr(private_executor.time, "time", lambda: 1600)
    with pytest.raises(SystemExit):
        private_executor.read_diagnostic(diagnostic_id)
    assert not (private_executor.DIAGNOSTICS / diagnostic_id).exists()


def test_diagnostic_rejects_unknown_stage_or_category(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(private_executor, "DIAGNOSTICS", tmp_path / "diagnostics")
    with pytest.raises(SystemExit):
        private_executor._record_diagnostic("y" * 16, request(), "anything", "registry")
    with pytest.raises(SystemExit):
        private_executor._record_diagnostic("y" * 16, request(), "validated", "anything")


def test_diagnostic_request_proactively_purges_expired_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(private_executor, "DIAGNOSTICS", tmp_path / "diagnostics")
    private_executor.DIAGNOSTICS.mkdir()
    expired = private_executor.DIAGNOSTICS / ("e" * 16)
    expired.write_text('{"expires_at": 1}', encoding="utf-8")
    monkeypatch.setattr(private_executor.time, "time", lambda: 1000)
    private_executor._record_diagnostic("f" * 16, request(), "validated", "registry")
    assert not expired.exists()


def test_synthetic_request_requires_canonical_root_anchor() -> None:
    invalid_registry = registry() | {"corpus_root": "/var/lib/not-the-synthetic-root"}
    with pytest.raises(SystemExit):
        private_executor.validate_request(request(), invalid_registry)


def test_refusal_has_no_diagnostic_id_before_artifact(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        private_executor.refuse()
    assert "diagnostic=" not in capsys.readouterr().err


def test_refusal_has_opaque_diagnostic_id_after_artifact(
    capsys: pytest.CaptureFixture[str],
) -> None:
    diagnostic_id = "q" * 16
    with pytest.raises(SystemExit):
        private_executor.refuse_diagnostic(diagnostic_id)
    assert (
        capsys.readouterr().err == f"private corpus request refused [diagnostic={diagnostic_id}]\n"
    )


def test_runtime_root_is_not_listable_by_plain_gw2agent() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "RUNTIME_ROOT.mkdir(mode=0o710" in source
    assert "RUNTIME_ROOT.chmod(0o710)" in source
    assert "diag-enter" not in source


def test_profiles_use_only_the_runtime_bound_pinned_uv_binary() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")
    unit = (ROOT / "ops/private-corpus/gw2analytics-private-corpus@.service").read_text(
        encoding="utf-8"
    )
    assert 'UV_RUNTIME_BINARY = Path("toolchain/uv")' in source
    assert 'PINNED_UV = Path("/usr/local/lib/gw2analytics-private/uv/0.12.5/uv")' in source
    assert "_verify_pinned_uv()" in source
    assert '"uv",' not in source
    assert "ProtectHome=yes" in unit
    assert (
        "BindReadOnlyPaths=/usr/local/lib/gw2analytics-private/uv/0.12.5/uv:"
        "/run/gw2analytics-private/%i/toolchain/uv" in unit
    )


def test_pinned_uv_is_checked_before_single_use_token_consumption() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")
    request_start = source.index("def request(")
    assert source.index("_verify_pinned_uv()", request_start) < source.index(
        "_consume_token(token, data)", request_start
    )
    assert "/home/gw2agent" not in source


@pytest.mark.parametrize(
    "changes",
    [
        {"command_profile": "shell"},
        {"worktree_ref": "outside"},
        {"selection_ref": "outside"},
        {"authorization_token": "short"},
        {"task_id": "bad task id"},
        {"purpose": "other"},
        {"purpose": "analysis"},
        {"why_private_data": "x" * 501},
        {"requested_output": "x" * 201},
        {"unexpected": "argv"},
    ],
)
def test_refus_happens_before_a_unit_for_untrusted_request(changes: dict[str, object]) -> None:
    with pytest.raises(SystemExit):
        private_executor.validate_request(request(**changes), registry())


def test_full_requires_a_confirmation_that_names_full() -> None:
    with pytest.raises(SystemExit):
        private_executor.validate_request(
            request(scope="full", full_confirmation="yes"), registry()
        )
    assert (
        private_executor.validate_request(
            request(scope="full", full_confirmation="confirm full", authorization_token="b" * 16),
            registry(),
        )
        == "b" * 16
    )


def test_private_sources_do_not_contain_a_real_corpus_reference() -> None:
    for path in (ROOT / "ops" / "private-corpus").iterdir():
        if path.is_file():
            assert "WvW/" not in path.read_text(encoding="utf-8")


def test_profile_is_closed_and_raw_output_is_runtime_only() -> None:
    source = EXECUTOR.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "stdout.log" in source and "stderr.log" in source
    assert "commands[profile]" in source
    assert "test_mounted_input.py" in source
    assert "--request-stdin" in source
    assert "PYTHONDONTWRITEBYTECODE" in source
    assert "PYTEST_ADDOPTS" in source
    assert "SYNTHETIC_ROOT" in source
    assert 'uv_cache = runtime / "uv-cache"' in source
    assert "uv_cache.chmod(0o770)" in source
    contract = json.loads((ROOT / "ops" / "private-corpus" / "contract.json").read_text())[
        "request"
    ]
    assert set(contract["profiles"]) == private_executor.PROFILES
    assert set(contract["purposes"]) == {"validation", "reproduction", "analysis"}
