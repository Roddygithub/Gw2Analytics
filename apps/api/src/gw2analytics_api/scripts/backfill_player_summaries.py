"""v0.8.5: backfill the ``OrmFightPlayerSummary`` table for pre-v0.8.4 fights.

The v0.8.4 migration created the ``fight_player_summaries`` table but
did NOT populate it for existing fights. Pre-v0.8.4 fights therefore
fall through to the slow-path blob-walk on every player-route request.
This module is the one-shot backfill that closes the debt for existing
users; new uploads are handled by the v0.8.4 write path in services.

Public surface
--------------
- :func:`run_backfill` is the importable library entrypoint.
- :func:`backfill_role_detection` backfills role detection on existing rows.
- :mod:`__main__` is the thin CLI wrapper (argparse + a single call).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable

from minio.error import S3Error
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.role_detection import detect_role_lite
from gw2analytics_api import storage
from gw2analytics_api._event_dispatch import build_event_iterator
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerSummary,
)
from gw2analytics_api.services import _persist_player_summaries, _sanitize_name

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, int, str | None], None]


# ---------------------------------------------------------------------------
# Library entrypoints
# ---------------------------------------------------------------------------


def run_backfill(
    db: Session,
    *,
    fight_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> tuple[int, int, int]:
    fights = _discover_fights(db, fight_id=fight_id, limit=limit)
    backfilled = 0
    skipped = 0
    failed = 0

    for fight in fights:
        player_agents = [a for a in fight.agents if a.is_player and a.account_name]
        if not player_agents:
            logger.debug("fight %s has no player agents; skipping", fight.id)
            skipped += 1
            if progress_callback is not None:
                progress_callback(backfilled, skipped, failed, fight.id)
            continue

        try:
            _backfill_one_fight(db, fight, player_agents, dry_run=dry_run)
        except (S3Error, OSError, EOFError, SQLAlchemyError, ValidationError) as exc:
            logger.exception("failed backfilling fight %s: %s", fight.id, exc)
            db.rollback()
            failed += 1
            if progress_callback is not None:
                progress_callback(backfilled, skipped, failed, fight.id)
            continue

        if not dry_run:
            db.commit()
        backfilled += 1
        logger.info("backfilled fight %s (%d player agents)", fight.id, len(player_agents))
        if progress_callback is not None:
            progress_callback(backfilled, skipped, failed, fight.id)

    return backfilled, skipped, failed


def backfill_role_detection(
    db: Session,
    *,
    fight_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int, int]:
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _discover_fights(
    db: Session,
    *,
    fight_id: str | None,
    limit: int | None,
) -> list[OrmFight]:
    stmt = select(OrmFight).options(selectinload(OrmFight.agents))
    if fight_id is not None:
        stmt = stmt.where(OrmFight.id == fight_id)
    else:
        stmt = stmt.where(
            ~select(OrmFightPlayerSummary.fight_id)
            .where(OrmFightPlayerSummary.fight_id == OrmFight.id)
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
    if fight.events_blob_uri is None:
        _backfill_pre_phase7(db, fight, player_agents)
        if dry_run:
            db.rollback()
        return

    gz_bytes = storage.get_events(fight.events_blob_uri)
    events = list(build_event_iterator(gz_bytes=gz_bytes))
    _persist_player_summaries(db, fight, events)
    if dry_run:
        db.rollback()


def _backfill_pre_phase7(
    db: Session,
    fight: OrmFight,
    player_agents: list[OrmFightAgent],
) -> None:
    db.execute(
        delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight.id),
    )
    for agent in player_agents:
        assert agent.account_name is not None
        db.add(
            OrmFightPlayerSummary(
                fight_id=fight.id,
                account_name=_sanitize_name(agent.account_name.lstrip(":")),
                name=_sanitize_name(agent.name),
                profession=int(agent.profession),
                elite_spec=int(agent.elite_spec),
                total_damage=0,
                total_healing=0,
                total_buff_removal=0,
            ),
        )


# ---------------------------------------------------------------------------
# CLI (argparse wrapper)
# ---------------------------------------------------------------------------


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from exc
    if n < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer (>= 1), got {n}")
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_player_summaries",
        description="Materialise the per-(fight, account) summary rows for pre-v0.8.4 fights.",
    )
    parser.add_argument("--limit", type=_positive_int, default=None)
    parser.add_argument("--progress-every", type=_positive_int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fight-id", type=str, default=None)
    parser.add_argument("--roles-only", action="store_true")
    parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger = logging.getLogger("backfill")

    def _progress_cb(backfilled: int, skipped: int, failed: int, fight_id: str | None) -> None:
        total = backfilled + skipped + failed
        if total % args.progress_every == 0:
            logger.info(
                "backfill progress: total=%d backfilled=%d skipped=%d failed=%d last_fight_id=%s",
                total, backfilled, skipped, failed, fight_id,
            )

    session = get_sessionmaker()()
    try:
        if args.roles_only:
            updated, skipped, failed = backfill_role_detection(
                session, fight_id=args.fight_id, limit=args.limit, dry_run=args.dry_run,
            )
            print(f"role backfill complete: updated={updated} skipped={skipped} failed={failed} {'(dry-run)' if args.dry_run else ''}")
        else:
            backfilled, skipped, failed = run_backfill(
                session, fight_id=args.fight_id, limit=args.limit,
                dry_run=args.dry_run, progress_callback=_progress_cb,
            )
            print(f"backfill complete: backfilled={backfilled} skipped={skipped} failed={failed} {'(dry-run)' if args.dry_run else ''}")
    finally:
        session.close()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
