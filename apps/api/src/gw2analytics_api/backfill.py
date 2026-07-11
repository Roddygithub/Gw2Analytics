"""v0.8.5: backfill the ``OrmFightPlayerSummary`` table for pre-v0.8.4 fights.

The v0.8.4 migration created the ``fight_player_summaries`` table but
did NOT populate it for existing fights. Pre-v0.8.4 fights therefore
fall through to the slow-path blob-walk on every player-route request
(the v0.7.0 perf debt: 5-30s latency for users with 100+ fights).
This module is the one-shot backfill that closes the debt for existing
users; new uploads are handled by the v0.8.4 write path in
:mod:`gw2analytics_api.services`.

Public surface
--------------
- :func:`run_backfill` is the importable library entrypoint. It accepts
  an open :class:`sqlalchemy.orm.Session` plus optional filters, and
  returns a ``(backfilled, skipped, failed)`` count tuple for caller
  reporting (the CLI script, the test suite, the operational dashboards).
- :mod:`gw2analytics_api.scripts.backfill_player_summaries` is the
  thin CLI wrapper (argparse + a single ``run_backfill`` call).

Discovery
---------
The discovery query uses a ``NOT EXISTS`` subquery against
``OrmFightPlayerSummary.fight_id`` to find fights that have zero
summary rows. The query is a single ``SELECT`` that returns
``(OrmFight, agents)`` with ``selectinload`` so the per-fight
processing is a pure in-memory walk over the pre-loaded agents
list (no N+1). A ``--fight-id`` filter short-circuits the subquery
for targeted retries.

Per-fight commit + skip-on-error
--------------------------------
Each fight is its own transaction. A failure on one fight (corrupt
blob, S3 error, programming bug) is logged + counted + skipped; the
next fight is processed. The operator can re-run the script to
retry the failed fights (the discovery query sees them as
"still no summary rows" + retries them). The per-fight commit
also makes the script safe to interrupt: ``Ctrl+C`` between
fights loses at most one in-flight transaction, and the
discovery query on the next run starts from the last successfully
backfilled fight.

Pre-Phase-7 branch (``events_blob_uri IS NULL``)
------------------------------------------------
Fights uploaded before the Phase 7 v1 wire-up have no events
blob (the column is ``NULL``) but DO have player-agent rows
(the agents were persisted in V0.5). The slow-path fallback
writes 0-total ``FightContribution`` rows for these fights
(the "analyst expects 'I attended fight X' to be visible
even if the fight had no events" contract). The backfill
mirrors that contract exactly: for fights with
``events_blob_uri IS NULL`` AND player agents, write 0-total
summary rows. Without this branch, pre-Phase-7 fights would
keep falling through to the slow-path even after the
backfill runs.

Idempotency
-----------
The function is re-runnable. The discovery query
``~OrmFight.id.in_(select(OrmFightPlayerSummary.fight_id))``
skips fights with existing summary rows. Re-running on an
already-backfilled dataset is a no-op (every fight is in
the "already has summary rows" set). The post-Phase-7 branch
also calls :func:`services._persist_player_summaries` which
DELETEs + INSERTs, so a partial backfill (one fight's
``commit()`` fails mid-INSERT) is retryable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from minio.error import S3Error
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.role_detection import detect_role_lite

# v0.10.8 plan 140 Fix-D: switched from module-local binding to
# live attribute lookup. The module-local binding (``from ... import
# get_events``) created a snapshot at import time; tests monkeypatching
# ``gw2analytics_api.storage.get_events`` had no effect on the backfill
# module's local binding. Live attribute lookup via ``storage.get_events``
# resolves the monkeypatch path mismatch (test_backfill_eoferror.py:1).
from gw2analytics_api import storage
from gw2analytics_api._event_dispatch import build_event_iterator
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerSummary,
)
from gw2analytics_api.services import _persist_player_summaries, _sanitize_name

logger = logging.getLogger(__name__)

# v0.9.10 plan 035: opt-in progress callback signature. The
# CLI wires a callback that logs a progress line every N
# fights; the library's ``run_backfill`` accepts the callback
# as an optional kwarg so non-CLI callers (tests, future
# dashboards) can opt-in without changing the signature.
# The callback receives the running ``(backfilled, skipped,
# failed)`` counts + the most recent ``fight_id`` (None if
# the loop has not yet visited any fight). The callback is
# invoked AFTER the per-fight state is updated (success or
# skip) but BEFORE the count is returned -- the canonical
# "last event fires last" ordering.
ProgressCallback = Callable[[int, int, int, str | None], None]


def run_backfill(
    db: Session,
    *,
    fight_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> tuple[int, int, int]:
    """Materialise the per-(fight, account) summary rows.

    Returns a ``(backfilled, skipped, failed)`` count tuple. The
    caller (CLI script, test suite, operational dashboard) is
    responsible for reporting the counts to the operator.

    Parameters
    ----------
    db:
        An open :class:`sqlalchemy.orm.Session` bound to the
        target database. The function does NOT close the session;
        the caller owns the lifecycle.
    fight_id:
        If set, backfill only the single fight with this id
        (the discovery query short-circuits the ``NOT EXISTS``
        subquery). Useful for targeted retries + the test suite.
    limit:
        If set, cap the number of fights processed. Useful for
        the operational "backfill the first 100 fights, then
        re-run" pattern that lets operators verify the script
        behaves correctly on a small batch before unleashing it
        on the full dataset.
    dry_run:
        If True, log what WOULD be backfilled but skip the
        ``db.commit()`` and the DELETE+INSERT. The counts are
        still returned. Useful for operational "is this script
        going to do what I think it will?" verification.

    Edge cases
    ----------
    - **No player agents** (NPC-only fight or a fight with
      agents whose ``account_name`` is empty): the fight is
      counted as ``skipped`` and no rows are written. The
      cross-fight join is keyed on ``account_name`` so NPCs
      cannot contribute to a profile; writing 0-total rows
      for NPCs would inflate the table without serving any
      route.
    - **S3 / gzip errors** (blob missing, blob corrupted): the
      fight is counted as ``failed`` and the next fight is
      processed. The script is re-runnable; a re-run retries
      the failed fights.
    - **SQLAlchemy errors** (constraint violations, transient
      DB issues): the fight is counted as ``failed`` and the
      transaction is rolled back. The next fight is processed.
    """
    fights = _discover_fights(db, fight_id=fight_id, limit=limit)

    backfilled = 0
    skipped = 0
    failed = 0

    for fight in fights:
        player_agents = [a for a in fight.agents if a.is_player and a.account_name]
        if not player_agents:
            # NPC-only fight or a fight whose player agents all
            # have empty account_names (the parser sets
            # ``account_name`` from the arcdps combo string; a
            # missing combo is filtered to ``None`` and then
            # skipped here). Nothing to materialise -- the
            # cross-fight join on ``account_name`` would not
            # match these rows anyway.
            logger.debug("fight %s has no player agents; skipping", fight.id)
            skipped += 1
            # v0.9.10 plan 035 (semantic fix v2): fire the progress
            # callback on the SKIP branch too, so the operator sees
            # progress lines even on datasets with many NPC-only fights
            # (where every visit goes through this path and the
            # ``backfilled`` count never increments).
            if progress_callback is not None:
                progress_callback(backfilled, skipped, failed, fight.id)
            continue

        try:
            _backfill_one_fight(db, fight, player_agents, dry_run=dry_run)
        except (S3Error, OSError, EOFError, SQLAlchemyError, ValidationError) as exc:
            # The 5 caught exception types are the per-fight
            # failure modes the backfill is designed to survive:
            #
            # - ``S3Error``: a single missing MinIO blob (the
            #   operator may have deleted the blob out-of-band
            #   or the pre-Phase-7 fight never had one). NOT a
            #   MinIO outage (which would be an operational
            #   concern, not a per-fight issue) -- the catch is
            #   narrow enough to let a real MinIO outage
            #   propagate (e.g. ``ConnectionError`` from the
            #   boto3 layer).
            # - ``OSError``: gzip decode errors on a corrupted
            #   blob (the gzip module raises ``OSError`` with
            #   ``errno.EIO`` on bad CRC + length).
            # - ``EOFError``: ``gzip.decompress`` on a truncated
            #   blob raises ``EOFError`` (NOT a subclass of
            #   ``OSError`` — it inherits from ``Exception``
            #   directly). A partially-uploaded blob whose gzip
            #   trailer is missing produces this error. The fight
            #   is counted as ``failed`` and the next fight is
            #   processed (same blameless-error contract as the
            #   other 4 types).
            # - ``SQLAlchemyError``: constraint violations,
            #   transient DB issues, etc.
            # - ``ValidationError``: a single malformed event
            #   line in the gzipped JSONL (e.g. a corrupted
            #   record). The ``TypeAdapter.validate_json`` in
            #   :func:`_backfill_one_fight` raises this.
            #
            # Each of these is a per-fight issue -- the next
            # fight is processed. The script is re-runnable;
            # a re-run retries the failed fights (they still
            # have zero summary rows + their failures were
            # transient or out-of-band).
            logger.exception("failed backfilling fight %s: %s", fight.id, exc)
            db.rollback()
            failed += 1
            # v0.9.10 plan 035 (semantic fix v2): fire the progress
            # callback on the FAIL branch too, so the operator sees
            # the running per-row counts even when transient failures
            # accumulate.
            if progress_callback is not None:
                progress_callback(backfilled, skipped, failed, fight.id)
            continue

        if not dry_run:
            db.commit()
        backfilled += 1
        logger.info("backfilled fight %s (%d player agents)", fight.id, len(player_agents))

        # v0.9.10 plan 035: progress callback. Fires ONCE per visit
        # AFTER the count is updated (on the SUCCESS branch — the
        # SKIP and FAIL branches have their own invocations above).
        # The CLI uses the callback to throttle progress logs via
        # ``total % N == 0``; non-CLI callers can wire richer
        # behaviour (metrics, dashboards) without re-implementing
        # the loop.
        if progress_callback is not None:
            progress_callback(backfilled, skipped, failed, fight.id)

    return backfilled, skipped, failed


def _discover_fights(
    db: Session,
    *,
    fight_id: str | None,
    limit: int | None,
) -> list[OrmFight]:
    """Return the list of fights that need backfilling.

    Discovery rules:
    - If ``fight_id`` is set, return ONLY that fight (regardless
      of whether it has summary rows -- the operator may want
      to force a re-backfill of a specific fight).
    - Otherwise, return fights with zero summary rows. The
      ``NOT EXISTS`` subquery is the canonical SQL for "not in
      the right-hand-side set"; SQLAlchemy compiles it to a
      correlated subquery that uses the
      ``ix_fight_player_summaries_account_fight`` index
      (the query planner can use either the PK index on
      ``(fight_id, account_name)`` or the composite index on
      ``(account_name, fight_id)``; the PK is preferred for
      the EXISTS check).

    The query pre-loads the agents via ``selectinload`` so the
    per-fight iteration does not pay an N+1.
    """
    stmt = select(OrmFight).options(selectinload(OrmFight.agents))
    if fight_id is not None:
        stmt = stmt.where(OrmFight.id == fight_id)
    else:
        # ``NOT EXISTS`` (the ``~exists()`` form) is the
        # canonical SQL for "no matching rows in the right-hand
        # side". It is preferred over ``NOT IN`` because
        # ``NOT IN`` has surprising NULL semantics (a single
        # NULL in the right-hand side drops the whole query).
        stmt = stmt.where(
            ~select(OrmFightPlayerSummary.fight_id)
            .where(
                OrmFightPlayerSummary.fight_id == OrmFight.id,
            )
            .exists(),
        )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars().all())


def _backfill_one_fight(
    db: Session,
    fight: OrmFight,
    player_agents: list[OrmFightAgent],
    *,
    dry_run: bool,
) -> None:
    """Materialise the summary rows for one fight.

    Branches on ``events_blob_uri``:
    - ``NULL``: pre-Phase-7 fight. Write 0-total summary rows for
      each player agent (mirrors the v0.7.0 slow-path's "attended
      fight X is visible" contract).
    - non-``NULL``: post-Phase-7 fight. Load the gzipped JSONL
      blob from MinIO, decompress, parse to ``list[Event]``,
      and delegate to :func:`services._persist_player_summaries`
      (which does the DELETE+INSERT).

    The function does NOT commit -- the caller
    (:func:`run_backfill`) commits per fight so a single bad
    fight does not poison the whole batch.
    """
    if fight.events_blob_uri is None:
        _backfill_pre_phase7(db, fight, player_agents)
        if dry_run:
            db.rollback()  # undo the DELETE+INSERT in dry-run mode
        return

    gz_bytes = storage.get_events(fight.events_blob_uri)
    events = list(build_event_iterator(gz_bytes=gz_bytes))
    _persist_player_summaries(db, fight, events)
    if dry_run:
        db.rollback()  # undo the DELETE+INSERT in dry-run mode


def _backfill_pre_phase7(
    db: Session,
    fight: OrmFight,
    player_agents: list[OrmFightAgent],
) -> None:
    """Write 0-total summary rows for a pre-Phase-7 fight.

    The v0.7.0 slow-path fallback wrote 0-total
    ``FightContribution`` rows for fights whose
    ``events_blob_uri IS NULL`` (the "attended fight X is
    visible even if the fight had no events" contract). The
    backfill mirrors that contract exactly so the fast-path
    produces the same output as the slow-path for these
    fights.

    The DELETE before the INSERTs makes the operation
    idempotent: a re-run of the backfill on an already-
    backfilled pre-Phase-7 fight would re-DELETE + re-INSERT
    the same rows (the discovery query would skip the fight
    in the first place, but the ``--fight-id`` filter can
    force a re-run).
    """
    db.execute(
        delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight.id),
    )
    for agent in player_agents:
        # ``agent.account_name`` is truthy (filtered by the
        # caller), so the cast to ``str`` is safe. The
        # ``agent.name or ""`` fallback matches the write
        # path's contract (the parser may surface an empty
        # char-name for synthetic agents). The ``assert`` is
        # type-narrowing only; ``# noqa: S101`` silences the
        # assert-detection lint (the codebase doesn't run
        # with ``python -O`` so the assert cannot be
        # optimised away in production).
        assert agent.account_name is not None  # noqa: S101
        db.add(
            OrmFightPlayerSummary(
                fight_id=fight.id,
                # v0.10.2 hotfix followup #7: route the
                # ``account_name`` + ``name`` through
                # :func:`_sanitize_name` so the
                # sanitization contract is centralised at
                # every ORM write boundary (mirrors the
                # services.py fix from followup #5). The
                # ``OrmFightAgent`` here is already
                # NUL-stripped (the write path runs
                # ``_sanitize_name`` before INSERT) AND
                # bounded to 68 bytes by the arcdps
                # combo-string layout, so the call is
                # defensive -- but it keeps the new
                # 128-char truncation consistent across
                # the two ORM write boundaries and catches
                # any future regression that bypasses the
                # write path's sanitization (e.g. an
                # operator manually UPDATEing the agent
                # row via SQL with a > 128 char name, then
                # running the backfill).
                account_name=_sanitize_name(agent.account_name),
                name=_sanitize_name(agent.name),
                profession=int(agent.profession),
                elite_spec=int(agent.elite_spec),
                total_damage=0,
                total_healing=0,
                total_buff_removal=0,
            ),
        )


def backfill_role_detection(
    db: Session,
    *,
    fight_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Backfill ``detected_role`` + ``detected_tags`` on existing summary rows.

    Discovers ``OrmFightPlayerSummary`` rows where
    ``detected_role IS NULL`` (pre-v0.10.3 rows), runs
    :func:`detect_role_lite` on the 3 magnitudes already on each
    row, and UPDATEs the row in-place. No blob re-download, no
    re-parse — the heuristic only needs ``total_damage``,
    ``total_healing``, ``total_buff_removal``, ``profession``,
    and ``elite_spec``, all of which are already on the summary
    row.

    Returns ``(updated, skipped, failed)`` count tuple. The
    caller (CLI script, test suite) is responsible for reporting
    the counts to the operator.

    Parameters
    ----------
    db:
        An open :class:`sqlalchemy.orm.Session`. The caller owns
        the lifecycle.
    fight_id:
        If set, backfill only rows for the single fight with
        this id. Useful for targeted runs + the test suite.
    limit:
        If set, cap the number of rows processed.
    dry_run:
        If True, compute the role/tags but skip the ``db.commit()``.
        The counts are still returned.

    Idempotency
    -----------
    The discovery query filters ``WHERE detected_role IS NULL``,
    so re-running on already-populated rows is a no-op.
    """
    stmt = select(OrmFightPlayerSummary).where(
        OrmFightPlayerSummary.detected_role.is_(None),
    )
    if fight_id is not None:
        stmt = stmt.where(OrmFightPlayerSummary.fight_id == fight_id)
    if limit is not None:
        stmt = stmt.limit(limit)

    rows = list(db.execute(stmt).scalars().all())
    updated = 0
    skipped = 0
    failed = 0

    for row in rows:
        role, tags = detect_role_lite(
            total_damage=row.total_damage,
            total_healing=row.total_healing,
            total_buff_removal=row.total_buff_removal,
            profession_int=row.profession,
            elite_spec_int=row.elite_spec,
        )
        row.detected_role = role
        row.detected_tags = tags
        updated += 1

    if updated > 0:
        try:
            if dry_run:
                db.rollback()
            else:
                db.commit()
        except SQLAlchemyError:
            logger.exception("failed committing role detection backfill")
            db.rollback()
            failed = updated
            updated = 0

    return updated, skipped, failed


__all__ = [
    "ProgressCallback",
    "backfill_role_detection",
    "run_backfill",
]  # v0.9.10 plan 035
