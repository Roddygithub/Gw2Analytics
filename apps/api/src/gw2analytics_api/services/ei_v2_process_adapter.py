"""Bounded Elite Insights ``WvwExportV2`` process adapter (prototype).

This module is the first piece of the Elite Insights process boundary
prescribed by ``docs/architecture/parser-boundary.md``: it invokes a
configured Elite Insights CLI in a subprocess, requests exactly the
certified ``WvwExportV2`` output, and validates the result with the
certified Gw2Analytics V2 contract. It is deliberately NOT wired into
production ingestion yet — the legacy ``parser_adapter`` remains the
only production parse path, and nothing in the product calls this
module. A later slice will swap ``parser_adapter`` over to it.

Doctrine:

- Elite Insights is the canonical EVTC interpreter; this adapter never
  reinterprets EVTC semantics, it only transports EI's export.
- The certified V2 contract (``gw2_core.WvwExportV2``) is the single
  validator; its rules are not duplicated here.
- Every invocation runs in its own isolated temporary workspace, so
  the consumed export provably belongs to that invocation and
  parallel invocations cannot collide.
- Diagnostics describe paths, exit codes, counts and contract field
  errors only — never combat-log or export contents.
"""

from __future__ import annotations

import fnmatch
import glob
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from gw2_core import WvwExportV2

__all__ = [
    "CERTIFIED_EI_PARSER_VERSION",
    "EiProcessAmbiguousOutputError",
    "EiProcessConfigError",
    "EiProcessContractError",
    "EiProcessError",
    "EiProcessExitError",
    "EiProcessMissingOutputError",
    "EiProcessOutputFormatError",
    "EiProcessTimeoutError",
    "EiProcessVersionError",
    "EiProcessWorkspaceError",
    "EiV2ExportResult",
    "EiV2ProcessAdapter",
]

logger = logging.getLogger(__name__)

#: Parser version of the certified Elite Insights V2 candidate
#: ``445eeb80e373b4597b0b38f9fbf90099c475fefc``.
#:
#: The certified exporter writes ``source_commit = null`` into every V2
#: export, so a document cannot prove the exact Git commit of the build
#: that produced it. The adapter's version guard therefore pins this
#: parser version — a necessary, but NOT sufficient, condition for the
#: certified candidate. Exact-commit provenance would require the
#: exporter to fill ``source_commit`` in a future EI change.
CERTIFIED_EI_PARSER_VERSION = "3.26.0.0"

#: Suffix of the V2 export sidecar EI writes next to the log name.
_EXPORT_SUFFIX = "_wvw_export_v2.json"

#: Maximum bytes of captured EI stdout/stderr kept on a failure, as a
#: bounded diagnostic tail. The tail is metadata-safe by construction
#: (EI console output is progress/error logging), and it is never
#: written to the adapter's logs by default.
_PROCESS_OUTPUT_TAIL_BYTES = 2048


class EiProcessError(Exception):
    """Base class for every failure raised by the EI V2 process adapter."""


class EiProcessConfigError(EiProcessError):
    """The adapter or invocation is misconfigured (bad command, input, workspace)."""


class EiProcessWorkspaceError(EiProcessError):
    """A material filesystem operation in the invocation workspace failed.

    Covers workspace creation, writing the per-invocation EI config
    file, and reading the selected V2 export, so a raw ``OSError``
    never leaks through the adapter's typed failure model.
    """


class EiProcessTimeoutError(EiProcessError):
    """EI did not finish within the configured timeout (the child was terminated)."""

    def __init__(self, message: str, *, timeout_seconds: float, elapsed_seconds: float):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds


class EiProcessExitError(EiProcessError):
    """EI exited with a non-zero status."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        elapsed_seconds: float,
        stdout_tail: str = "",
        stderr_tail: str = "",
    ):
        super().__init__(message)
        self.returncode = returncode
        self.elapsed_seconds = elapsed_seconds
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail


class EiProcessOutputError(EiProcessError):
    """The invocation produced an unusable set of V2 export candidates."""


class EiProcessMissingOutputError(EiProcessOutputError):
    """The invocation produced no V2 export output."""


class EiProcessAmbiguousOutputError(EiProcessOutputError):
    """The invocation produced more than one V2 export candidate."""


class EiProcessOutputFormatError(EiProcessError):
    """The V2 export output is not valid JSON."""


class EiProcessContractError(EiProcessError):
    """The V2 export output violates the certified Gw2Analytics V2 contract.

    Contract details live on the exception, not in the message: player
    identities from a malformed export must not leak into logs.
    """

    def __init__(self, message: str, *, field_errors: list[tuple[str, str]]):
        super().__init__(message)
        self.field_errors = field_errors


class EiProcessVersionError(EiProcessError):
    """The export reports an unexpected EI parser version.

    The certified EI V2 exporter writes ``source_commit = null``, so an
    export cannot prove the exact Git commit of its producing build;
    this guard verifies the certified ``parser_version`` instead.
    """

    def __init__(self, message: str, *, expected_parser_version: str, actual_parser_version: str):
        super().__init__(message)
        self.expected_parser_version = expected_parser_version
        self.actual_parser_version = actual_parser_version


@dataclass(frozen=True)
class EiV2ExportResult:
    """Successful outcome of one EI V2 export invocation.

    EI version and export identity are carried by ``export`` itself
    (``parser_version`` and the fight envelope); temporary workspace
    paths are deliberately not part of stable result state.
    """

    #: The export document validated by the certified V2 contract.
    export: WvwExportV2
    #: The combat log that was exported.
    source_log: Path
    #: Wall-clock duration of the EI process, in seconds.
    elapsed_seconds: float
    #: The EI command that was executed, program first.
    ei_command: tuple[str, ...]


def _resolve_program(program: str) -> Path:
    """Return the absolute program path, or raise an explicit config error.

    The returned path is fully resolved at construction time (absolute
    and with symlinks followed), so a later working-directory change —
    or a swapped symlink — can no longer alter which executable a
    stored command invokes.
    """
    if not program:
        raise EiProcessConfigError("ei_command must start with a non-empty program")
    candidate = Path(program)
    if candidate.parent != Path():
        if not candidate.is_file():
            raise EiProcessConfigError(f"EI executable does not exist: {program}")
    else:
        which = shutil.which(program)
        if which is None:
            raise EiProcessConfigError(
                f"EI executable was not found on PATH or as a file: {program!r}"
            )
        candidate = Path(which)
    if not os.access(candidate, os.X_OK):
        raise EiProcessConfigError(f"EI executable is not executable: {candidate!s}")
    return candidate.resolve()


def _ei_settings(out_location: Path) -> str:
    """Write the certified EI invocation settings for one V2 export.

    Mirrors the configuration certified by
    ``scripts/ei-certification/certify_wvw_export.py`` (replay-disabled
    mode) against EI candidate
    ``445eeb80e373b4597b0b38f9fbf90099c475fefc``: every other output
    format and upload target is off, healing extensions are parsed, and
    the detailed-WvW mode required by the export is on.
    """
    settings = {
        "SaveAtOut": "false",
        "OutLocation": str(out_location),
        "SaveOutWvwExport": "false",
        "SaveOutWvwExportV2": "true",
        "SaveOutJSON": "false",
        "SaveOutHTML": "false",
        "SaveOutCSV": "false",
        "SaveOutTrace": "false",
        "SingleThreaded": "true",
        "ParsePhases": "true",
        "ParseCombatReplay": "false",
        "ParseExtensions": "true",
        "ComputeDamage": "true",
        "ComputeBuff": "true",
        "ComputeCast": "true",
        "ComputeMechanics": "true",
        "ComputeDamageModifiers": "true",
        "ParseMultipleLogs": "false",
        "RawTimelineArrays": "false",
        "DetailledWvW": "true",
        "UploadToDPSReports": "false",
        "UploadToWingman": "false",
        "UploadToMistWarrior": "false",
        "UploadToRaidar": "false",
    }
    return "\n".join(f"{key}={value}" for key, value in settings.items()) + "\n"


def _decode_tail(data: bytes | None) -> str:
    """Decode a bounded diagnostic tail of captured process output."""
    if not data:
        return ""
    tail = data[-_PROCESS_OUTPUT_TAIL_BYTES:]
    return tail.decode("utf-8", errors="replace")


def _select_export(workspace: Path, log_stem: str) -> Path:
    """Deterministically select the one V2 export the invocation produced.

    The workspace was empty before EI ran, so any match is necessarily
    fresh; the log stem is escaped so exotic file names cannot widen
    the pattern.
    """
    pattern = glob.escape(log_stem) + "*" + _EXPORT_SUFFIX
    try:
        candidates = sorted(
            path
            for path in workspace.iterdir()
            if path.is_file() and fnmatch.fnmatch(path.name, pattern)
        )
    except OSError as exc:
        raise EiProcessWorkspaceError(
            f"could not enumerate the V2 export candidates in {workspace}: {exc.strerror}"
        ) from exc
    if not candidates:
        raise EiProcessMissingOutputError(
            f"EI produced no {_EXPORT_SUFFIX} output in the invocation workspace "
            f"for log stem {log_stem!r}"
        )
    if len(candidates) > 1:
        raise EiProcessAmbiguousOutputError(
            f"EI produced {len(candidates)} {_EXPORT_SUFFIX} candidates in the "
            f"invocation workspace for log stem {log_stem!r}; expected exactly one"
        )
    return candidates[0]


@dataclass
class EiV2ProcessAdapter:
    """Invoke the certified Elite Insights V2 export for one combat log.

    The adapter is process infrastructure around the canonical EI
    boundary: it owns invocation, output isolation and validation, and
    nothing else. Instances are safe to reuse and to run concurrently —
    all mutable state lives in per-invocation workspaces.

    Configuration is explicit (no global settings, no environment
    sniffing): the EI command, timeout and optional workspace parent
    directory are constructor dependencies, so a deployment wires them
    at composition time.
    """

    #: EI command prefix, program first, e.g.
    #: ``("/opt/dotnet/dotnet", "/opt/ei/GuildWars2EliteInsights-CLI.dll")``.
    #: The program may be an absolute path, a ``PATH``-relative name, or
    #: any executable file; it is resolved to an absolute path at
    #: construction time, so later working-directory changes cannot
    #: alter which executable runs. The V2 config file and log path are
    #: appended at invocation time.
    ei_command: Sequence[str]
    #: Hard wall-clock limit for one EI invocation, in seconds. Must be
    #: positive and finite.
    timeout_seconds: float = 600.0
    #: Parent directory for per-invocation workspaces. Defaults to the
    #: system temporary directory. Must already exist.
    workspace_root: Path | None = None
    #: Parser version the export must report. Defaults to the certified
    #: candidate's version; see ``CERTIFIED_EI_PARSER_VERSION`` for why
    #: this is a version pin, not an exact-commit proof.
    expected_parser_version: str = CERTIFIED_EI_PARSER_VERSION
    #: Command actually executed, normalized in ``__post_init__``.
    _normalized_command: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.ei_command, Sequence) or isinstance(self.ei_command, str):
            raise EiProcessConfigError("ei_command must be a sequence of strings")
        if not self.ei_command:
            raise EiProcessConfigError("ei_command must not be empty")
        if any(not isinstance(part, str) or not part for part in self.ei_command):
            raise EiProcessConfigError("ei_command parts must be non-empty strings")
        program = _resolve_program(self.ei_command[0])
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise EiProcessConfigError(
                f"timeout_seconds must be a positive finite number, got {self.timeout_seconds!r}"
            )
        if self.workspace_root is not None and not self.workspace_root.is_dir():
            raise EiProcessConfigError(
                f"workspace_root is not an existing directory: {self.workspace_root}"
            )
        if not self.expected_parser_version:
            raise EiProcessConfigError("expected_parser_version must not be empty")
        self._normalized_command = (str(program), *tuple(self.ei_command[1:]))

    def export(self, log_path: Path | str) -> EiV2ExportResult:
        """Export one ``.evtc``/``.zevtc`` log and return the validated V2 document."""
        log = Path(log_path).resolve()
        if not log.is_file():
            raise EiProcessConfigError(f"input log does not exist or is not a file: {log}")
        workspace = self._create_workspace()
        try:
            config_path = workspace / "ei.conf"
            try:
                config_path.write_text(_ei_settings(workspace), encoding="utf-8")
            except OSError as exc:
                raise EiProcessWorkspaceError(
                    f"could not write the EI invocation config in {workspace}: {exc.strerror}"
                ) from exc
            argv = (*self._normalized_command, "-c", str(config_path), str(log))
            started = time.monotonic()
            try:
                completed = subprocess.run(  # noqa: S603 - argument-vector invocation of a validated, explicitly configured local executable
                    argv,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                # subprocess.run terminates and reaps the child before
                # re-raising, so no zombie is left behind.
                raise EiProcessTimeoutError(
                    f"EI exceeded the {self.timeout_seconds} s timeout exporting "
                    f"{log.name}; the process was terminated",
                    timeout_seconds=self.timeout_seconds,
                    elapsed_seconds=time.monotonic() - started,
                ) from exc
            elapsed_seconds = time.monotonic() - started
            if completed.returncode != 0:
                raise EiProcessExitError(
                    f"EI exited with status {completed.returncode} after "
                    f"{elapsed_seconds:.1f} s exporting {log.name}; "
                    "captured stdout/stderr tails are attached to this error",
                    returncode=completed.returncode,
                    elapsed_seconds=elapsed_seconds,
                    stdout_tail=_decode_tail(completed.stdout),
                    stderr_tail=_decode_tail(completed.stderr),
                )
            output_path = _select_export(workspace, log.stem)
            try:
                output_bytes = output_path.read_bytes()
            except OSError as exc:
                raise EiProcessWorkspaceError(
                    f"could not read the V2 export produced in {workspace}: {exc.strerror}"
                ) from exc
            try:
                payload: Any = json.loads(output_bytes)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise EiProcessOutputFormatError(
                    f"the V2 export produced for {log.name} is not valid JSON: {exc}"
                ) from exc
            try:
                export = WvwExportV2.model_validate(payload)
            except ValidationError as exc:
                field_errors = [
                    (
                        ".".join(str(part) for part in error.get("loc", ())),
                        str(error.get("msg", "")),
                    )
                    for error in exc.errors(include_url=False, include_input=False)
                ]
                raise EiProcessContractError(
                    f"the V2 export produced for {log.name} violates the certified "
                    f"WvwExportV2 contract at {len(field_errors)} field(s); "
                    "see field_errors on this error",
                    field_errors=field_errors,
                ) from exc
            if export.parser_version != self.expected_parser_version:
                raise EiProcessVersionError(
                    f"the V2 export produced for {log.name} reports parser version "
                    f"{export.parser_version!r}; this adapter is certified for "
                    f"{self.expected_parser_version!r}",
                    expected_parser_version=self.expected_parser_version,
                    actual_parser_version=export.parser_version,
                )
            return EiV2ExportResult(
                export=export,
                source_log=log,
                elapsed_seconds=elapsed_seconds,
                ei_command=self._normalized_command,
            )
        finally:
            self._remove_workspace(workspace)

    def _create_workspace(self) -> Path:
        try:
            return Path(tempfile.mkdtemp(prefix="ei-v2-", dir=self.workspace_root))
        except OSError as exc:
            raise EiProcessWorkspaceError(
                "could not create an isolated EI invocation workspace under "
                f"{self.workspace_root or Path(tempfile.gettempdir())}"
            ) from exc

    def _remove_workspace(self, workspace: Path) -> None:
        try:
            shutil.rmtree(workspace)
        except OSError:
            logger.warning("could not remove EI invocation workspace %s", workspace, exc_info=True)
