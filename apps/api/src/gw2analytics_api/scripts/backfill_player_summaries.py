"""v0.8.5: CLI entrypoint for the per-(fight, account) summary backfill.

The one-shot backfill that closes the v0.7.0 perf debt for
EXISTING users: the v0.8.4 migration created the
``fight_player_summaries`` table but did NOT populate it for
pre-v0.8.4 fights, so those fights still fall through to the
slow-path blob-walk on every player-route request. This CLI
iterates all such fights and materialises the summary rows.

Usage
-----

::

    # Backfill all fights without summary rows (the canonical
    # one-shot run after a production deploy of v0.8.4).
    python -m gw2analytics_api.scripts.backfill_player_summaries

    # Backfill the first 100 fights (operational "verify the
    # script behaves correctly on a small batch before
    # unleashing it on the full dataset" pattern).
    python -m gw2analytics_api.scripts.backfill_player_summaries --limit 100

    # Backfill a single fight (targeted retry after a known
    # failure, or manual verification that the script produces
    # the expected output for a specific fight id).
    python -m gw2analytics_api.scripts.backfill_player_summaries \\
        --fight-id abc123def456

    # Dry-run: log what WOULD be backfilled but skip the
    # commit. The counts are still reported.
    python -m gw2analytics_api.scripts.backfill_player_summaries --dry-run

    # Progress-every 10: log a progress line per 10 fights
    # (canonical for 10K+ fight backfills; default: every 100).
    python -m gw2analytics_api.scripts.backfill_player_summaries \\
        --progress-every 10

The script is safe to interrupt (``Ctrl+C``) and re-run: the
per-fight commit means at most one in-flight transaction is
lost; the discovery query on the next run retries the failed
fights (they still have zero summary rows). See
:mod:`gw2analytics_api.backfill` for the library contract.

Validation
----------

v0.9.10 plan 035 added ``--limit`` + ``--progress-every``
``_positive_int`` validation so a typoed ``--limit -1`` is
rejected with a clear argparse error (instead of crashing
Postgres with a cryptic syntax error on ``LIMIT -1``).
"""

from __future__ import annotations

import argparse
import logging
import sys

from gw2analytics_api.backfill import backfill_role_detection, run_backfill
from gw2analytics_api.database import get_sessionmaker


def _positive_int(value: str) -> int:
    """Argparse type: accept only positive integers (>= 1).

    v0.9.10 plan 035: rejects ``--limit -1`` +
    ``--progress-every 0`` with a clear error message
    identifying the bad value + the expected range. The
    error is printed by argparse in the canonical
    ``invalid value: '-1' for '--limit'`` format.
    Postgres rejects a negative ``LIMIT N`` with a
    cryptic syntax error otherwise; this proactive
    validation surfaces the operator's typoed intent
    before the SQL is issued.
    """
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected an integer, got {value!r}",
        ) from exc
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer (>= 1), got {n}",
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
            "script is making progress. Must be a positive integer "
            "(>= 1). Default: 100."
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
        "--roles-only",
        action="store_true",
        help=(
            "Only backfill detected_role + detected_tags on existing summary "
            "rows (no blob re-download). Use this for the v0.10.3 role-detection "
            "backfill on pre-migration rows."
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

    logger = logging.getLogger("backfill")

    def _progress_cb(
        backfilled: int,
        skipped: int,
        failed: int,
        fight_id: str | None,
    ) -> None:
        """v0.9.10 plan 035: progress reporter for large backfills.

        Logs a single line per ``--progress-every`` fights so the
        operator can see the script is making progress. The line
        includes the running counts + the most recent fight id so
        the operator can correlate with the SQL log if needed.
        """
        total = backfilled + skipped + failed
        if total % args.progress_every == 0:
            logger.info(
                "backfill progress: total=%d backfilled=%d skipped=%d failed=%d last_fight_id=%s",
                total,
                backfilled,
                skipped,
                failed,
                fight_id,
            )

    session = get_sessionmaker()()
    try:
        if args.roles_only:
            # v0.10.3 plan 119: role-detection backfill on existing
            # summary rows. No blob re-download — the heuristic runs
            # on the 3 magnitudes already on each row.
            updated, skipped, failed = backfill_role_detection(
                session,
                fight_id=args.fight_id,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            print(
                f"role backfill complete: updated={updated} "
                f"skipped={skipped} failed={failed} "
                f"{'(dry-run)' if args.dry_run else ''}",
            )
        else:
            backfilled, skipped, failed = run_backfill(
                session,
                fight_id=args.fight_id,
                limit=args.limit,
                dry_run=args.dry_run,
                progress_callback=_progress_cb,
            )
            # The summary line is the operator's primary signal: the
            # count of fights whose summary rows are now in the fast-path
            # table (backfilled), the count of fights that were
            # correctly skipped (no player agents), and the count of
            # fights that need a retry (failed -- re-run the script).
            # The exit code is non-zero if any fight failed so the script
            # can be wired into CI / cron with a proper failure signal.
            print(
                f"backfill complete: backfilled={backfilled} "
                f"skipped={skipped} failed={failed} "
                f"{'(dry-run)' if args.dry_run else ''}",
            )
    finally:
        session.close()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
