"""Domain ⇄ ORM translation.

Maps a :class:`gw2_core.Fight` (Pydantic V2, stable internal model) to
the SQLAlchemy ORM rows persisted in Postgres. Errors here write to
``uploads.error_message`` rather than raised, so the API stays alive.

Phase 7 v1 also persists the parsed event stream: after :func:`_save_fight`
inserts the fight row + per-agent + per-skill rows, the same parser is
fed through :meth:`PythonEvtcParser.parse_events` to drain the cbtevent
block. Each :class:`DamageEvent` is serialised as JSONL, the stream is
gzip-compressed, the bytes are uploaded to MinIO at
``events/{fight_id}.jsonl.gz``, and the storage key is written back to
``OrmFight.events_blob_uri``. Zero-event fights keep ``events_blob_uri
= NULL`` -- the parser degrades to no-blob rather than persist an
empty file. The ``GET /fights/{id}/events`` route surfaces ``404 Not
Found`` for those rows rather than a misleading empty aggregation.
"""

from __future__ import annotations

import gzip
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from gw2_core import BuffRemovalEvent, DamageEvent, EliteSpec, Event, HealingEvent, Profession
from gw2_core import Fight as DomainFight
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser, read_zevtc_bytes
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    UPLOAD_STATUS_FAILED,
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerSummary,
    OrmFightSkill,
    Upload,
)
from gw2analytics_api.storage import put_events

logger = logging.getLogger(__name__)


def process_parse(
    session_factory: Callable[[], Session],
    upload_id: uuid.UUID,
    raw_bytes: bytes,
) -> None:
    with session_factory() as db:
        """Run the V0 parser on the uploaded blob and persist Fight+Agent rows.

        Dispatched by FastAPI ``BackgroundTasks`` from ``POST /api/v1/uploads``.
        The ``db`` Session is the request-scoped one; FastAPI runs background
        tasks *after* the response is sent and *before* the dependency
        generator's ``finally`` block closes the session, so the session is
        still usable here. When 5+ concurrent uploads is the norm, we move
        to a dedicated queue (Arq) with a **fresh, worker-scoped** session
        — never reuse the request session in the worker.
        """
        upload = db.get(Upload, upload_id)
        if upload is None:
            logger.error("upload %s disappeared between POST and parse", upload_id)
            return
        try:
            # ``.zevtc`` files are zip wrappers around the raw EVTC blob.
            # ``read_zevtc_bytes`` is the single source of truth for the
            # zip-discriminate-unwrap contract: it returns the inner EVTC for
            # valid zips and raises :class:`EvtcParseError` for anything else
            # (bogus zip, non-zip bytes, empty archive — all caught below).
            evtc_bytes = read_zevtc_bytes(raw_bytes)
            fights = list(PythonEvtcParser().parse(evtc_bytes))
        except EvtcParseError as exc:
            logger.warning("parse failed for upload %s: %s", upload_id, exc)
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = f"EvtcParseError: {exc}"
            db.commit()
            return
        except (RuntimeError, ValueError) as exc:
            # Surface genuine Python bugs (e.g. ``_save_fight`` raises
            # ``ValueError`` defensively if a fight arrives without a header) and
            # unexpected parser misbehaviour (``RuntimeError``) rather than hide
            # them behind a generic "failed" status.
            logger.exception("parse exception for upload %s", upload_id)
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = f"{type(exc).__name__}: {exc}"
            db.commit()
            return

        if not fights:
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = "parser yielded no fights"
            db.commit()
            return

        core_fight = fights[0]
        if core_fight.header is None:
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = "parser yielded fight without header"
            db.commit()
            return

        _save_fight(db, upload, core_fight)
        _persist_event_blob(db, upload, evtc_bytes, core_fight.id)
        upload.status = UPLOAD_STATUS_COMPLETED
        upload.error_message = None
        db.commit()


def _save_fight(db: Session, upload: Upload, cf: DomainFight) -> None:
    """Translate ``core_fight`` to ORM rows in the current session."""
    if cf.header is None:
        msg = "_save_fight called without header"
        raise ValueError(msg)

    head = cf.header
    # EVTC blobs do not carry a wall clock. ``cf.started_at`` defaults
    # to the Unix epoch sentinel (``datetime(1970, 1, 1, tzinfo=UTC)``
    # in :class:`gw2_core.Fight`), so we MUST override with the
    # server's wall clock at parse time. The previous
    # ``cf.started_at if cf.started_at.tzinfo else datetime.now(UTC)``
    # guard was a bug: the epoch sentinel HAS tzinfo (UTC), so the
    # guard fell through and every fight landed on 1970-01-01
    # midnight UTC, breaking the v0.8.0 timeline chart (all points
    # stack at the leftmost X-axis slot). v0.8.1 unconditionally
    # uses ``datetime.now(UTC)``; a future v0.9 could parse the
    # EVTC build field (``yyyymmdd``) to get a date anchor.
    started_at = datetime.now(UTC)

    orm_fight = OrmFight(
        id=cf.id,
        upload_id=upload.id,
        build_version=head.build_version,
        encounter_id=head.encounter_id,
        agent_count=head.agent_count,
        started_at=started_at,
        game_type=int(cf.game_type),
    )
    db.add(orm_fight)
    db.flush()

    for agent in cf.agents:
        db.add(
            OrmFightAgent(
                fight_id=cf.id,
                agent_id=int(agent.id),
                name=agent.name or "",
                profession=_prof_id(agent.profession),
                elite_spec=_elite_id(agent.elite),
                is_player=agent.is_player,
                account_name=agent.account_name,
                subgroup=agent.subgroup,
            ),
        )

    for skill in cf.skills:
        db.add(
            OrmFightSkill(
                fight_id=cf.id,
                skill_id=int(skill.id),
                name=skill.name or "",
            ),
        )

    # Flush the staged agents + skills so the re-query in
    # :func:`_persist_event_blob` can see them via the
    # ``selectinload(OrmFight.agents)`` pre-load. The session is
    # configured with ``autoflush=False`` (see
    # :func:`gw2analytics_api.database.get_sessionmaker`), so
    # the staged rows are NOT visible to the next query until we
    # explicitly flush. Without this flush the re-query returns
    # an orm_fight with an empty agents list and the per-fight
    # per-account summary silently produces zero rows (the
    # route's slow-path fallback then serves the data -- correct,
    # but the materialised fast-path is lost for the fight).
    # The flush is intentionally local: it does NOT commit; the
    # outer :func:`process_parse` commits at the end of the
    # happy path.
    db.flush()


def _prof_id(p: Profession) -> int:
    return int(p.value)


def _elite_id(e: EliteSpec) -> int:
    return int(e.value)


def _persist_event_blob(
    db: Session,
    upload: Upload,
    evtc_bytes: bytes,
    fight_id: str,
) -> None:
    """Drain the cbtevent block into a MinIO blob and write the key back.

    Phase 7 v1 behaviour:

    - Empty streams (zero damage events after the ``is_statechange == 0`` /
      ``is_nondamage == 0`` / ``value > 0`` filter) leave
      ``events_blob_uri`` as ``NULL``. We deliberately do NOT persist an
      empty blob: an empty blob would round-trip through the route as
      ``200 OK`` with zero damage + zero events, misleading consumers
      into thinking the parser ran but nothing happened. ``NULL`` instead
      signals "no event data available", which the route surfaces as
      ``404 Not Found`` (consistent with pre-Phase 7 fights).
    - ANY exception raised by ``parse_events`` or ``put_events`` is
      logged and swallowed so the upload still flips to ``COMPLETED``
      with the fight-row + agents + skills persisted. The events blob
      is a deep-metrics concern; losing it must NOT lose the agents /
      skills already written. Operators can re-parse the upload to
      retry the blob upload without losing the agents/skills. The
      catch is intentionally broad because this call sits OUTSIDE
      the ``process_parse`` try/except -- the 3-tier classification
      previously here has been collapsed to one ``except Exception``
      (the outer ``process_parse`` cannot classify the re-raise, and
      the historical ``(RuntimeError, ValueError, OSError)`` tier was
      both drift-prone (mentioned ``S3Error`` in the docstring but
      did not catch it) and effectively dead under the broad
      ``except Exception`` below it).
    """

    parser = PythonEvtcParser()
    try:
        events = list(parser.parse_events(evtc_bytes))
        if not events:
            logger.debug("upload %s yielded zero events; events_blob_uri stays NULL", upload.id)
            return
        jsonl = "\n".join(event.model_dump_json() for event in events).encode("utf-8")
        gz_bytes = gzip.compress(jsonl)
        blob_uri = put_events(fight_id, gz_bytes)
    except Exception:
        # ``parse_events`` raises ``EvtcParseError`` on malformed
        # archives; ``put_events`` raises ``S3Error`` (and ``OSError``
        # variants) on MinIO failures; anything truly unexpected
        # lands here too. All three are treated identically: degrade
        # to ``events_blob_uri = NULL``, keep the fight-row contract
        # intact.
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return

    # ``selectinload(OrmFight.agents)`` pre-loads the agents in the
    # same query so the per-source-side attribution in
    # ``_persist_player_summaries`` does not pay an extra round-trip.
    # The pre-load is the canonical fix for the lazy-load
    # ``orm_fight.agents`` access in the helper below; without it
    # SQLAlchemy would issue a fresh SELECT when the relationship
    # is first dereferenced.
    orm_fight = db.execute(
        select(OrmFight).where(OrmFight.id == fight_id).options(selectinload(OrmFight.agents)),
    ).scalar_one_or_none()
    if orm_fight is not None:
        orm_fight.events_blob_uri = blob_uri
        # v0.8.4: also materialise the per-(fight, account_name) roll-up
        # so the player routes can serve the per-account view with a
        # pure SQL aggregation (avoids the O(fights x events) per-request
        # cost documented in the v0.7.0 CHANGELOG). The summary is
        # populated from the same ``events`` list the blob was built
        # from -- one walk, two outputs. The DELETE+INSERT pattern
        # inside the helper is re-parse safe: re-uploading the same
        # SHA replaces the per-fight rows atomically before the new
        # INSERTs land.
        #
        # **Best-effort semantics.** A failure here degrades to the
        # slow-path fallback (the route falls through to the blob
        # walk for fights without a summary row); the upload still
        # flips to ``COMPLETED`` with the fight + blob contract
        # intact. The summary is a perf optimization, not a
        # correctness invariant -- losing it must not lose the
        # fight row. The try/except is intentionally narrow: the
        # summary write only touches a single table (no MinIO, no
        # S3), so a raise signals either a programming bug or a
        # transient DB issue.
        # Narrow ``SQLAlchemyError`` (not bare ``Exception``) so a
        # programming bug in the helper surfaces during development
        # instead of being silently swallowed. A broad ``except
        # Exception`` was hiding a real bug in the selectinload /
        # flush chain during the v0.8.4 bring-up (round 131 review);
        # the narrow catch preserves the production resilience for
        # transient DB issues without silencing future regressions.
        try:
            _persist_player_summaries(db, orm_fight, events)
        except SQLAlchemyError:
            logger.exception(
                "player summary materialization failed for fight %s; "
                "slow-path fallback will serve the player routes",
                fight_id,
            )


def _persist_player_summaries(
    db: Session,
    orm_fight: OrmFight,
    events: list[Event],
) -> None:
    """Materialise the per-(fight, account_name) roll-up from ``events``.

    v0.8.4 perf-debt fix: the player routes (``/api/v1/players``,
    ``/api/v1/players/{name}``, ``/api/v1/players/{name}/timeline``)
    previously walked the events blob on every request. The
    ``fight_player_summaries`` table caches the per-(fight, account)
    totals so the routes can serve the per-account view with a
    pure SQL aggregation (O(rows) instead of O(fights x events)).

    Aggregation rules (mirrors :class:`PlayerProfileAggregator`):
    - ``account_name`` is the source-agent's account_name (the
      player who generated the events). NPC-only fights (no player
      agents) produce zero summary rows -- the cross-fight join is
      keyed on account_name so NPCs cannot contribute to a profile.
    - ``name`` is the last-seen char-name (the aggregator's contract).
    - ``profession`` / ``elite_spec`` are first-seen anchors (also
      the aggregator's contract). Denormalised on the summary row
      so the player routes don't JOIN ``OrmFightAgent`` on every
      request.
    - ``total_damage`` / ``total_healing`` / ``total_buff_removal``
      are the per-account SUMS of the event magnitudes
      (``DamageEvent.damage`` / ``HealingEvent.healing`` /
      ``BuffRemovalEvent.buff_removal``). Zero-init when no events
      of a given kind target the account.

    Re-parse safety: the function DELETEs the existing rows for
    ``orm_fight.id`` before INSERTing the new ones. A re-upload of
    the same SHA (which lands on the same ``OrmFight`` row) replaces
    the per-fight rows atomically -- the fight_id PK + CASCADE FK
    keeps the table consistent.

    NPC rows are filtered: only events whose
    ``source_agent_id`` maps to a player agent (is_player=True AND
    account_name is non-empty) contribute. This matches the
    :func:`routes.players._compute_contributions` filter.
    """
    # Build the source-agent map for the per-fight agents. The
    # route's helper uses ``OrmFightAgent.fight_id == fight_id`` so
    # we mirror that here. ``selectinload(OrmFight.agents)`` is
    # available on the orm_fight we just queried, so the agents
    # list is pre-loaded -- no extra round-trip.
    source_map: dict[int, OrmFightAgent] = {
        a.agent_id: a for a in orm_fight.agents if a.is_player and a.account_name
    }
    if not source_map:
        # Pure NPC fight (no player agents); nothing to materialise.
        return

    # Per-account accumulator: ``account_name -> {damage, healing, strip, name, prof, elite}``.
    # ``name`` is last-seen (overwritten on every event); ``prof`` /
    # ``elite`` are first-seen (set once on the first event for
    # the account).
    per_account: dict[str, dict[str, int | str]] = {}
    for event in events:
        agent = source_map.get(event.source_agent_id)
        if agent is None:
            # NPC source (or unknown agent) -- silently skip. The
            # per-target roll-ups still see the event (their filter
            # is on ``target_agent_id``), but the per-source-side
            # attribution only counts player agents.
            continue
        account = agent.account_name
        # ``source_map`` filters out agents where ``account_name`` is
        # falsy (``if a.is_player and a.account_name``), so the
        # comprehension guarantees ``account_name`` is a non-empty
        # ``str`` here. mypy doesn't infer this from the
        # comprehension's filter, so we narrow with an ``assert`` --
        # the check is type-narrowing only and never fires in
        # practice (``# noqa: S101`` to silence the assert-detection
        # lint; the codebase doesn't run with ``python -O`` so the
        # assert cannot be optimised away in production).
        assert account is not None  # noqa: S101  # narrowed by the source_map comprehension
        # Last-seen name (overwrite on every event after the first)
        # + first-seen profession / elite (initialised on the first
        # event). The ``account in per_account`` branch is the
        # subsequent-event path; the else branch is the
        # first-event path that seeds the bucket. This replaces
        # the earlier ``bucket["set"]`` sentinel which conflated
        # "first" and "subsequent" in the same dict as the data.
        if account in per_account:
            bucket: dict[str, int | str] = per_account[account]
            bucket["name"] = agent.name or ""
        else:
            bucket = {
                "damage": 0,
                "healing": 0,
                "strip": 0,
                "name": agent.name or "",
                "prof": int(agent.profession),
                "elite": int(agent.elite_spec),
            }
            per_account[account] = bucket
        if isinstance(event, DamageEvent):
            bucket["damage"] = int(bucket["damage"]) + event.damage
        elif isinstance(event, HealingEvent):
            bucket["healing"] = int(bucket["healing"]) + event.healing
        elif isinstance(event, BuffRemovalEvent):
            bucket["strip"] = int(bucket["strip"]) + event.buff_removal

    # Re-parse safety: delete the existing rows for this fight_id
    # before inserting the new ones. The CASCADE FK on fight_id
    # means the per-fight rows are removed when the fight is
    # deleted, but a re-upload of the same SHA does NOT delete
    # the fight -- it reuses the existing ``OrmFight`` row, so
    # the summary rows MUST be explicitly replaced.
    db.execute(
        delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == orm_fight.id),
    )
    for account_name, bucket in per_account.items():
        db.add(
            OrmFightPlayerSummary(
                fight_id=orm_fight.id,
                account_name=account_name,
                name=str(bucket["name"]),
                profession=int(bucket["prof"]),
                elite_spec=int(bucket["elite"]),
                total_damage=int(bucket["damage"]),
                total_healing=int(bucket["healing"]),
                total_buff_removal=int(bucket["strip"]),
            ),
        )
