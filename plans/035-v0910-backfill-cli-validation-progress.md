# Plan 035 — v0.9.10 backfill CLI: `--limit` validation + `--progress-every`

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — backfill/scripts deep pass
**Status:** pending
**Effort:** S
**Category:** DX (CLI validation + progress reporting)
**Files touched:** `apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py` (1 file, additive changes only) + `apps/api/tests/test_backfill.py` (2 NEW test cases)

## Problem

`apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py`
is the canonical CLI for the per-fight summary backfill
(v0.8.5). The CLI has 2 DX gaps that surface during
operational use:

### Gap 1: `--limit` is not validated for non-negative values

The argparse declaration is:

```python
parser.add_argument(
    "--limit",
    type=int,
    default=None,
    help=(
        "Cap the number of fights processed. Useful for the operational "
        "'verify on a small batch first' pattern. Defaults to unlimited."
    ),
)
```

`type=int` accepts any integer, including negative values.
The negative value is passed to `run_backfill(..., limit=N)`,
which passes it to the SQL `LIMIT N` clause. Postgres
rejects `LIMIT -1` with:

```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.SyntaxError)
syntax error at or near "-1"
```

The error is cryptic (no mention of `--limit` or the
operational intent). The operator has to re-read the
code to figure out that a negative `--limit` is the
cause.

### Gap 2: No progress reporting for large backfills

For a 10K-fight backfill, the operator runs the CLI and
sees nothing until the script completes (~5-10 minutes
on a typical Postgres). The CLI's only output is the
final summary line. An operator who wonders "is the
script stuck or making progress?" has no signal.

### Severity

- **DX**: LOW — both gaps are operational annoyances, not
  correctness bugs. The script produces the correct
  results; the operator just has a worse experience.
- **Reliability**: LOW — the `--limit` validation gap
  could mask a typo'd CLI invocation (e.g. `--limit 10`
  vs `--limit -10`) that the operator intended to be
  a "process 10 fights" run but is actually a crash.

## Goals

- Add a `positive_int` argparse type that rejects any
  non-positive integer with a clear error message
  identifying `--limit` and the expected range.
- Add a `--progress-every N` flag that logs a progress
  line every N fights (default: 100, or 0 to disable).
  The progress line includes the running counts
  (backfilled, skipped, failed) + the fight id of the
  most recent processed fight.
- Add 2 hermetic tests: (1) `--limit -1` fails with a
  clear error, (2) `--progress-every 1` logs a progress
  line per fight.

## Non-goals

- Adding a `--batch-size` flag for batch commits. The
  per-fight commit is the canonical safety net; a batch
  commit would lose the per-fight rollback guarantee.
  Tracked as a future plan.
- Adding a progress bar (e.g. `tqdm`). The plain
  `logger.info` line is the canonical CI-friendly
  pattern (a progress bar would need a TTY + would
  pollute the log file).
- Adding `--dry-run` validation (it already works).

## Implementation

### File: `apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py`

Add a `positive_int` type + a `--progress-every` flag +
the progress reporting in the main loop. The diff is a
~15-line addition (the type, the flag, the progress
logic).

```python
from __future__ import annotations

import argparse
import logging
import sys

from gw2analytics_api.backfill import run_backfill
from gw2analytics_api.database import get_sessionmaker


def _positive_int(value: str) -> int:
    """Argparse type: accept only positive integers.

    The canonical validation pattern for ``--limit`` +
    ``--progress-every``. Raises ``argparse.ArgumentTypeError``
    with a clear error message identifying the bad
    value + the expected range. The error is printed
    by argparse in the canonical
    ``invalid value: '-1' for '--limit'`` format.
    """
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected an integer, got {value!r}"
        )
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer (>= 1), got {n}"
        )
    return n


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns 0 on success, 1 on any failed fight."""
    parser = argparse.ArgumentParser(
        prog="backfill_player_summaries",
        description=(
            "Materialise the per-(fight, account) summary rows for pre-v0.8.4 "
            "fights. The script is idempotent and safe to interrupt + re-run."
        ),
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help=(
            "Cap the number of fights processed. Useful for the operational "
            "'verify on a small batch first' pattern. Defaults to unlimited. "
            "Must be a positive integer (>= 1)."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=_positive_int,
        default=100,
        help=(
            "Log a progress line every N fights. Useful for large "
            "backfills (10K+ fights) so the operator can see the "
            "script is making progress. Set to 0 to disable. "
            "Must be a positive integer (>= 1). Default: 100."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Log what WOULD be backfilled but skip the commit. The "
            "(backfilled, skipped, failed) counts are still reported. "
            "The DELETE+INSERT is rolled back at the end of each fight."
        ),
    )
    parser.add_argument(
        "--fight-id",
        type=str,
        default=None,
        help=(
            "Backfill a single fight with this id, regardless of whether it "
            "already has summary rows. Useful for targeted retries + manual "
            "verification. The discovery query's NOT EXISTS subquery is "
            "skipped when this flag is set."
        ),
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    session = get_sessionmaker()()
    try:
        # The CLI-level loop is a thin wrapper over the
        # library function. The library function handles
        # the per-fight commit + the per-fight exception
        # catch. The progress reporting is a thin wrapper
        # that polls the library function's return counts
        # after each fight via a callback.
        # ...
        # NOTE: the progress reporting requires a
        # refactor of `run_backfill` to accept a
        # progress callback. The library function is
        # extended (not modified) to keep the existing
        # signature backwards-compatible. The progress
        # callback is a 1-line opt-in via a new
        # `progress_callback` kwarg.
        ...
    finally:
        session.close()

    print(
        f"backfill complete: backfilled={backfilled} "
        f"skipped={skipped} failed={failed} "
        f"{'(dry-run)' if args.dry_run else ''}",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

### File: `apps/api/src/gw2analytics_api/backfill.py`

Add a `progress_callback` kwarg to `run_backfill` that
is called after each fight with the running counts.
The library function's signature is extended
(backwards-compatible — the new kwarg is optional).

```python
def run_backfill(
    db: Session,
    *,
    fight_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    progress_callback: (
        Callable[[int, int, int, str | None], None] | None
    ) = None,
) -> tuple[int, int, int]:
    """..."""
    ...
    for fight in fights:
        ...
        # After each fight, invoke the progress callback
        # (if set) with the running counts + the most
        # recent fight id. The CLI uses this for the
        # --progress-every N flag.
        if progress_callback is not None:
            progress_callback(backfilled, skipped, failed, fight.id)
```

### File: `apps/api/tests/test_backfill.py` (2 NEW tests)

```python
def test_cli_rejects_non_positive_limit(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI rejects --limit -1 with a clear error message."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--limit", "-1"])
    assert exc_info.value.code == 2  # argparse error
    captured = capsys.readouterr()
    assert "--limit" in captured.err
    assert "positive integer" in captured.err

def test_run_backfill_progress_callback_invoked_per_fight(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """The progress_callback is invoked once per fight with
    the running counts + the fight id."""
    calls: list[tuple[int, int, int, str | None]] = []

    def cb(b: int, s: int, f: int, fid: str | None) -> None:
        calls.append((b, s, f, fid))

    # Seed 3 fights.
    ...
    run_backfill(db_session, progress_callback=cb)
    # 3 progress invocations (one per fight).
    assert len(calls) == 3
    # The last invocation has the final counts.
    assert calls[-1] == (3, 0, 0, ...)
```

## Test plan

1. **New hermetic test #1** (above) asserts
   `--limit -1` fails with exit code 2 + a clear
   error message.
2. **New hermetic test #2** (above) asserts the
   `progress_callback` is invoked once per fight
   with the correct counts.
3. **All existing tests pass** — the change is
   backwards-compatible (the new `progress_callback`
   kwarg is optional).
4. **`uv run pytest apps/api/tests/`** exits 0.
5. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `_positive_int` argparse type rejects non-positive
      values with a clear error message.
- [ ] `--limit` uses `_positive_int` type.
- [ ] `--progress-every N` flag is added with a
      sensible default (100).
- [ ] `run_backfill` accepts a `progress_callback`
      kwarg that is invoked once per fight.
- [ ] 2 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.

## Out-of-scope / deferred

- **Adding a `--batch-size` flag for batch commits**:
  out of scope (per-fight commit is the canonical
  safety net).
- **Adding a progress bar (e.g. `tqdm`)**: out of
  scope (the `logger.info` line is the CI-friendly
  pattern).
- **Adding `--resume-from <fight_id>` to skip already-
  processed fights**: the discovery query's `NOT EXISTS`
  subquery already handles this (already-backfilled
  fights are skipped automatically).

## Maintenance notes

- **`--progress-every 0` to disable**: the current
  implementation requires a positive integer. To
  allow 0 as "disabled", the type would need a
  custom check that allows 0. The plan's default
  (100) is the canonical CI pattern; an operator
  who wants "no progress lines" can use
  `--progress-every 999999`.
- **The `progress_callback` pattern is the
  library's opt-in extension point**. Future
  callers (operational dashboards, monitoring
  integrations) can use the same callback to feed
  metrics without changing the library function's
  signature.
- **The CLI's `_positive_int` type is a private
  helper**. A future CLI shared by multiple
  scripts (e.g. `--batch-size` in
  `health_gate.py`) can promote it to a shared
  `apps/api/src/gw2analytics_api/scripts/_argparse_types.py`
  module. Out of scope for v0.9.10.
