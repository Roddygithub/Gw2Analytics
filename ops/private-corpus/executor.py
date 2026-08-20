#!/usr/bin/env python3
"""Root-owned, single-use private-corpus request gate.

EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS.

The installed registry is deliberately outside the repository.  This source
contains no corpus path and never performs a shell invocation.
"""

from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

RUNTIME_ROOT = Path("/run/gw2analytics-private")
REGISTRY = Path("/etc/gw2analytics/private-corpus-registry.json")
CONSUMED_TOKENS = Path("/var/lib/gw2analytics/private-corpus-consumed")
DIAGNOSTICS = Path("/var/lib/gw2analytics/private-corpus-diagnostics")
SYNTHETIC_ROOT = Path("/var/lib/gw2analytics/private-corpus-synthetic")
CONTRACT = Path(__file__).with_name("contract.json")
if not CONTRACT.is_file():
    CONTRACT = Path("/usr/local/sbin/gw2analytics-private-corpus-contract.json")
PRIVATE_GROUP = "gw2analytics-private-readers"
WORKTREE_BASE = Path("/srv/gw2analytics").resolve()
UV_RUNTIME_BINARY = Path("toolchain/uv")
PINNED_UV = Path("/usr/local/lib/gw2analytics-private/uv/0.12.5/uv")
PINNED_UV_SHA256 = "6470fe2ab573e01f703fd76cada1952f7755dd0fc7f2f6ac0bee1d5f8ba4413e"
PINNED_UV_VERSION = "uv 0.12.5 (x86_64-unknown-linux-musl)"
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def refuse() -> None:
    print("private corpus request refused", file=sys.stderr)
    raise SystemExit(1)


def refuse_diagnostic(diagnostic_id: str) -> None:
    print(f"private corpus request refused [diagnostic={diagnostic_id}]", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        refuse()
    if not isinstance(value, dict):
        refuse()
    return value


def _contract() -> dict[str, object]:
    contract = load_json(CONTRACT).get("request")
    if not isinstance(contract, dict):
        refuse()
    return contract


PROFILES = frozenset(_contract().get("profiles", ()))


def validate_request(request: dict[str, object], registry: dict[str, object]) -> str:
    contract = _contract()
    required = set(contract.get("required", ()))
    profiles = set(contract.get("profiles", ()))
    purposes = set(contract.get("purposes", ()))
    limits = contract.get("text_limits")
    if not all(isinstance(value, str) for value in required) or not isinstance(limits, dict):
        refuse()
    if not required <= set(request) or set(request) - (
        required | {"selection_ref", "full_confirmation"}
    ):
        refuse()
    scope = request.get("scope")
    profile = request.get("command_profile")
    token = request.get("authorization_token")
    if (
        scope not in {"subset", "full"}
        or profile not in profiles
        or not isinstance(token, str)
        or not SAFE_ID.fullmatch(token)
    ):
        refuse()
    if request.get("purpose") not in purposes:
        refuse()
    allowed_purposes = registry.get("allowed_purposes")
    if (
        registry.get("synthetic") is not True
        or registry.get("corpus_root") != str(SYNTHETIC_ROOT)
        or not isinstance(allowed_purposes, list)
        or request["purpose"] not in allowed_purposes
    ):
        refuse()
    for field in ("task_id", "why_private_data", "requested_output"):
        value, limit = request.get(field), limits.get(field)
        if (
            not isinstance(value, str)
            or not value
            or not isinstance(limit, int)
            or len(value) > limit
        ):
            refuse()
    if not TASK_ID.fullmatch(request["task_id"]):
        refuse()
    worktrees = registry.get("worktrees")
    if not isinstance(worktrees, dict) or request.get("worktree_ref") not in worktrees:
        refuse()
    if scope == "subset":
        selections = registry.get("selections")
        if not isinstance(selections, dict) or request.get("selection_ref") not in selections:
            refuse()
    if scope == "full" and (
        not isinstance(request.get("full_confirmation"), str)
        or "full" not in request["full_confirmation"].lower()
    ):
        refuse()
    return token


def _diagnostic_contract() -> tuple[int, set[str], set[str]]:
    value = _contract().get("diagnostics")
    if not isinstance(value, dict):
        refuse()
    ttl = value.get("ttl_seconds")
    stages, categories = value.get("stages"), value.get("categories")
    if (
        not isinstance(ttl, int)
        or ttl <= 0
        or not isinstance(stages, list)
        or not isinstance(categories, list)
        or not all(isinstance(item, str) for item in stages + categories)
    ):
        refuse()
    return ttl, set(stages), set(categories)


def _record_diagnostic(
    diagnostic_id: str,
    request_data: dict[str, object],
    stage: str,
    category: str,
) -> None:
    ttl, stages, categories = _diagnostic_contract()
    if not SAFE_ID.fullmatch(diagnostic_id) or stage not in stages or category not in categories:
        refuse()
    now = int(time.time())
    artifact = {
        "schema_version": 1,
        "diagnostic_id": diagnostic_id,
        "task_id": request_data["task_id"],
        "scope": request_data["scope"],
        "command_profile": request_data["command_profile"],
        "stage": stage,
        "category": category,
        "created_at": now,
        "expires_at": now + ttl,
    }
    _purge_expired_diagnostics()
    DIAGNOSTICS.mkdir(mode=0o700, parents=True, exist_ok=True)
    diagnostic_path = DIAGNOSTICS / diagnostic_id
    temporary = DIAGNOSTICS / f".{diagnostic_id}.tmp"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(artifact, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    temporary.replace(diagnostic_path)


def _purge_expired_diagnostics() -> None:
    if not DIAGNOSTICS.is_dir():
        return
    now = int(time.time())
    for path in DIAGNOSTICS.iterdir():
        if not path.is_file() or not SAFE_ID.fullmatch(path.name):
            continue
        try:
            expires_at = load_json(path).get("expires_at")
        except SystemExit:
            path.unlink(missing_ok=True)
            continue
        if not isinstance(expires_at, int) or expires_at <= now:
            path.unlink(missing_ok=True)


def read_diagnostic(diagnostic_id: str) -> dict[str, object]:
    if not SAFE_ID.fullmatch(diagnostic_id):
        refuse()
    _purge_expired_diagnostics()
    artifact_path = DIAGNOSTICS / diagnostic_id
    artifact = load_json(artifact_path)
    expires_at = artifact.get("expires_at")
    if not isinstance(expires_at, int) or expires_at <= int(time.time()):
        artifact_path.unlink(missing_ok=True)
        refuse()
    return artifact


def _source_for(request_data: dict[str, object], registry: dict[str, object]) -> Path:
    root = registry.get("corpus_root")
    if not isinstance(root, str):
        refuse()
    try:
        corpus_root = Path(root).resolve(strict=True)
    except OSError:
        refuse()
    selection: object = "."
    if request_data["scope"] == "subset":
        selections = registry.get("selections")
        if not isinstance(selections, dict):
            refuse()
        selection = selections.get(request_data.get("selection_ref"))
    if not isinstance(selection, str) or Path(selection).is_absolute():
        refuse()
    if request_data["scope"] == "subset" and selection in {"", ".", ".."}:
        refuse()
    try:
        source = (corpus_root / selection).resolve(strict=True)
        source.relative_to(corpus_root)
    except (OSError, ValueError):
        refuse()
    if source.is_symlink():
        refuse()
    return source


def _worktree_for(request_data: dict[str, object], registry: dict[str, object]) -> Path:
    worktrees = registry.get("worktrees")
    registered = (
        worktrees.get(request_data["worktree_ref"]) if isinstance(worktrees, dict) else None
    )
    if not isinstance(registered, str):
        refuse()
    try:
        worktree = Path(registered).resolve(strict=True)
    except OSError:
        refuse()
    if worktree == WORKTREE_BASE or WORKTREE_BASE not in worktree.parents:
        refuse()
    return worktree


def _mount_source(source: Path, runtime: Path) -> None:
    staged = runtime / "source"
    staged.mkdir(mode=0o700)
    subprocess.run(  # noqa: S603 - fixed mount utility and validated absolute source
        ["/usr/bin/mount", "--bind", str(source), str(staged)], check=True
    )
    subprocess.run(  # noqa: S603 - fixed mount utility and private staging path
        ["/usr/bin/mount", "-o", "remount,bind,ro", str(staged)], check=True
    )


def _consume_token(token: str, request_data: dict[str, object]) -> None:
    """Create an atomic root-owned replay tombstone before any mount occurs."""
    CONSUMED_TOKENS.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            CONSUMED_TOKENS / token,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        refuse()
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "task_id": request_data["task_id"],
                "scope": request_data["scope"],
                "command_profile": request_data["command_profile"],
            },
            stream,
        )


def _verify_pinned_uv() -> None:
    """Fail closed before token consumption if the root-owned toolchain drifts."""
    try:
        metadata = PINNED_UV.stat()
        with PINNED_UV.open("rb") as binary:
            digest = hashlib.file_digest(binary, "sha256").hexdigest()
        version = subprocess.run(  # noqa: S603 - fixed root-owned binary and argument
            [str(PINNED_UV), "--version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        refuse()
    if (
        metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o511
        or digest != PINNED_UV_SHA256
        or version.returncode != 0
        or version.stdout.strip() != PINNED_UV_VERSION
    ):
        refuse()


def _cleanup(access_id: str, runtime: Path) -> bool:
    stopped = subprocess.run(  # noqa: S603 - fixed unit and opaque generated identifier
        ["/usr/bin/systemctl", "stop", f"gw2analytics-private-corpus@{access_id}.service"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    unmounted = subprocess.run(  # noqa: S603 - fixed unmount utility and private staging path
        ["/usr/bin/umount", "--lazy", str(runtime / "source")],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        shutil.rmtree(runtime)
    except OSError:
        return False
    return stopped.returncode == 0 and unmounted.returncode == 0


def request(data: dict[str, object]) -> int:
    registry = load_json(REGISTRY)
    token = validate_request(data, registry)
    _verify_pinned_uv()
    _consume_token(token, data)
    access_id = secrets.token_urlsafe(24)
    _record_diagnostic(access_id, data, "validated", "registry")
    runtime = RUNTIME_ROOT / access_id
    try:
        RUNTIME_ROOT.mkdir(mode=0o710, parents=True, exist_ok=True)
        os.chown(RUNTIME_ROOT, 0, grp.getgrnam(PRIVATE_GROUP).gr_gid)
        RUNTIME_ROOT.chmod(0o710)
        runtime.mkdir(mode=0o770, parents=True)
        os.chown(runtime, 0, grp.getgrnam(PRIVATE_GROUP).gr_gid)
        uv_cache = runtime / "uv-cache"
        uv_cache.mkdir(mode=0o770)
        os.chown(uv_cache, 0, grp.getgrnam(PRIVATE_GROUP).gr_gid)
        uv_cache.chmod(0o770)
        toolchain = runtime / UV_RUNTIME_BINARY.parent
        toolchain.mkdir(mode=0o750)
        os.chown(toolchain, 0, grp.getgrnam(PRIVATE_GROUP).gr_gid)
        uv_target = runtime / UV_RUNTIME_BINARY
        uv_target.touch(mode=0o550)
        os.chown(uv_target, 0, grp.getgrnam(PRIVATE_GROUP).gr_gid)
        _record_diagnostic(access_id, data, "runtime-created", "mount")
        try:
            source = _source_for(data, registry)
        except SystemExit:
            _record_diagnostic(access_id, data, "unit-failed", "registry")
            refuse_diagnostic(access_id)
        _mount_source(source, runtime)
        _record_diagnostic(access_id, data, "source-mounted", "mount")
        try:
            worktree = _worktree_for(data, registry)
        except SystemExit:
            _record_diagnostic(access_id, data, "unit-failed", "worktree")
            refuse_diagnostic(access_id)
        runtime_data = {**data, "worktree_path": str(worktree)}
        (runtime / "request.json").write_text(json.dumps(runtime_data), encoding="utf-8")
        subprocess.run(  # noqa: S603 - fixed system service and opaque generated identifier
            [  # noqa: S607 - systemctl is resolved from the root-controlled system PATH
                "systemctl",
                "start",
                f"gw2analytics-private-corpus@{access_id}.service",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _record_diagnostic(access_id, data, "unit-started", "service")
    except (OSError, subprocess.CalledProcessError):
        _record_diagnostic(access_id, data, "unit-failed", "service")
        refuse_diagnostic(access_id)
    finally:
        if not _cleanup(access_id, runtime):
            _record_diagnostic(access_id, data, "unit-failed", "cleanup")
    return 0


def run_unit(access_id: str) -> int:
    if not SAFE_ID.fullmatch(access_id):
        refuse()
    runtime = RUNTIME_ROOT / access_id
    uv_binary = runtime / UV_RUNTIME_BINARY
    request_data = load_json(runtime / "request.json")
    profile = request_data.get("command_profile")
    if profile not in set(_contract().get("profiles", ())):
        refuse()
    input_dir = runtime / "input"
    worktree = request_data.get("worktree_path")
    if (
        not isinstance(worktree, str)
        or Path(worktree).resolve() == WORKTREE_BASE
        or WORKTREE_BASE not in Path(worktree).resolve().parents
    ):
        refuse()
    (runtime / "tmp").mkdir(exist_ok=True)
    commands = {
        "parser-validation-readonly": [
            str(uv_binary),
            "run",
            "pytest",
            "tests/private_corpus/test_mounted_input.py",
            "-q",
        ],
        "ei-parity-readonly": [
            str(uv_binary),
            "run",
            "python",
            "scripts/ei-parity/ei_diff.py",
            "--private-subset",
            "--corpus-dir",
            str(input_dir),
            "--manifest",
            str(input_dir / "corpus-manifest.json"),
            "--runtime-dir",
            str(runtime),
        ],
        "pytest-private-fixture": [
            str(uv_binary),
            "run",
            "pytest",
            "tests/private_corpus/test_mounted_input.py",
            "-q",
        ],
    }
    try:
        with (
            (runtime / "stdout.log").open("wb") as output,
            (runtime / "stderr.log").open("wb") as errors,
        ):
            completed = subprocess.run(  # noqa: S603 - selected exclusively from closed commands above
                commands[profile],
                cwd=worktree,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPYCACHEPREFIX": str(runtime / "pycache"),
                    "PYTEST_ADDOPTS": "-p no:cacheprovider",
                    "TMPDIR": str(runtime / "tmp"),
                },
                stdout=output,
                stderr=errors,
                check=False,
            )
    except OSError:
        return 1
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--request-stdin", action="store_true")
    group.add_argument("--read-diagnostic-stdin", action="store_true")
    group.add_argument("--run-unit")
    args = parser.parse_args()
    if (args.request_stdin or args.read_diagnostic_stdin) and os.geteuid() != 0:
        refuse()
    if args.request_stdin:
        try:
            payload = sys.stdin.buffer.read(8192)
            if sys.stdin.isatty() or len(payload) == 8192:
                refuse()
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            refuse()
        if not isinstance(data, dict):
            refuse()
        return request(data)
    if args.read_diagnostic_stdin:
        diagnostic_id = sys.stdin.read(129).strip()
        if len(diagnostic_id) > 128:
            refuse()
        print(json.dumps(read_diagnostic(diagnostic_id), sort_keys=True))
        return 0
    return run_unit(args.run_unit)


if __name__ == "__main__":
    raise SystemExit(main())
