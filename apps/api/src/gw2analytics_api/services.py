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
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from gw2_core import BuffRemovalEvent, DamageEvent, EliteSpec, Event, HealingEvent, Profession
from gw2_core import Fight as DomainFight
from gw2_evtc_parser import (
    EvtcParseError,
    PythonEvtcParser,
    read_zevtc_bytes,
)
from gw2_evtc_parser import (
    __version__ as PARSER_VERSION,  # noqa: N812
)
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
        # v0.10.2 hotfix followup #6: stamp the parser version on
        # the upload envelope so operators can correlate a
        # ``completed`` row with the exact ``gw2_evtc_parser``
        # release that processed it. The ``Upload.parser_version``
        # column defaults to the sentinel ``"0"`` (the
        # "not parsed yet" signal); flipping it to the real
        # ``PARSER_VERSION`` here is the canonical "this upload
        # was successfully processed by parser X.Y.Z" marker.
        # The change is post-commit-safe: a re-parse that flips
        # a previously-failed upload to ``completed`` will also
        # stamp the version (the assignment overwrites the
        # sentinel). On failure, the sentinel stays (the
        # ``failed`` branch in the except clauses above
        # short-circuits before reaching this line, so the
        # version is NOT stamped on a failed parse -- correct
        # semantics: we never ran the parser, so we cannot
        # attribute a version to the parse attempt).
        upload.parser_version = PARSER_VERSION
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

    # v0.10.2 hotfix followup: deduplicate agents by ``agent_id`` before
    # INSERT. arcdps can yield the same ``agent_id`` multiple times in a
    # single fight (a player who switches accounts mid-fight triggers a
    # second agent struct with the same id but a different name /
    # account_name). Without dedup, the 2nd INSERT explodes on the
    # ``(fight_id, agent_id)`` composite PK. The first-seen agent wins
    # (the parser yields them in EVTC order, so the FIRST entry is the
    # one that was active for the longest portion of the fight). The
    # dedup is scoped to this loop; the parser's event-stream output
    # is NOT deduplicated because the source_agent_id attribution in
    # :func:`_persist_player_summaries` depends on the event order.
    seen_agent_ids: set[int] = set()
    for agent in cf.agents:
        agent_id_int = int(agent.id)
        if agent_id_int in seen_agent_ids:
            logger.info(
                "fight %s: deduplicating duplicate agent_id=%s (name=%r, "
                "is_player=%s); first-seen entry wins",
                cf.id,
                agent_id_int,
                agent.name,
                agent.is_player,
            )
            continue
        seen_agent_ids.add(agent_id_int)
        db.add(
            OrmFightAgent(
                fight_id=cf.id,
                agent_id=agent_id_int,
                name=_sanitize_name(agent.name),
                profession=_prof_id(agent.profession),
                elite_spec=_elite_id(agent.elite),
                is_player=agent.is_player,
                # Preserve the exact nullable semantic: ``None`` stays
                # ``None`` (a missing account / subgroup); non-None strings
                # (including empty strings) are sanitized. The previous
                # ``_sanitize_name(...) or None`` collapsed empty strings
                # to ``None`` (since ``"" or None == None``), which
                # ``test_uploads_e2e_happy_path`` caught.
                account_name=(
                    None if agent.account_name is None else _sanitize_name(agent.account_name)
                ),
                subgroup=(None if agent.subgroup is None else _sanitize_name(agent.subgroup)),
            ),
        )

    # v0.10.2 hotfix followup #3: deduplicate skills by ``skill_id``
    # before INSERT. Same root cause as the agent dedup above: arcdps
    # can yield the same ``skill_id`` multiple times in a single
    # fight (the parser misreads the skill table when ``name_len`` is
    # garbage from the event stream -- see the
    # ``MAX_SKILL_NAME_BYTES`` warning in :mod:`gw2_evtc_parser`).
    # Without dedup, the 2nd INSERT explodes on the ``(fight_id,
    # skill_id)`` composite PK. First-seen wins (mirrors the agent
    # policy). The dedup is scoped to this loop; the parser's
    # event-stream output is NOT deduplicated because the
    # ``source_skill_id`` attribution in :func:`_persist_player_summaries`
    # depends on the event order.
    seen_skill_ids: set[int] = set()
    for skill in cf.skills:
        skill_id_int = int(skill.id)
        if skill_id_int in seen_skill_ids:
            logger.info(
                "fight %s: deduplicating duplicate skill_id=%s (name=%r); first-seen entry wins",
                cf.id,
                skill_id_int,
                skill.name,
            )
            continue
        seen_skill_ids.add(skill_id_int)
        db.add(
            OrmFightSkill(
                fight_id=cf.id,
                skill_id=skill_id_int,
                name=_sanitize_name(skill.name),
            ),
        )

    # v0.10.2 hotfix followup #8: defensive WARNING when the
    # header claims skills but the parser yielded 0. This is
    # the same kind of "silent data quality" observability as
    # the #4 followup (0-summary on non-empty source_map).
    # The case happens when the parser's safety bound
    # (``MAX_SKILL_NAME_BYTES``) fires on the first skill
    # record (the parser stops reading the skill table), or
    # when the skill table is truncated before the first
    # record. The upload still completes (the events blob
    # may reference ``skill_id``s that don't have a name in
    # the ``fight_skills`` table, but the routes degrade
    # gracefully -- the ``/fights/{id}/events`` route
    # surfaces the events as raw ``skill_id`` integers, and
    # the SkillUsageTable component shows the id without a
    # name). The WARNING makes the silent failure visible
    # to operators monitoring the parser logs.
    if head.skill_count > 0 and not cf.skills:
        logger.warning(
            "fight %s: header claims skill_count=%d but parser yielded 0 skills; "
            "skill table likely truncated or corrupted (see MAX_SKILL_NAME_BYTES "
            "warning in gw2_evtc_parser.parser)",
            cf.id,
            head.skill_count,
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


#: Maximum length of a name-like field written to the ORM. Matches
#: the ``String(128)`` NOT NULL column constraint on
#: ``OrmFightAgent.name`` / ``OrmFightSkill.name`` /
#: ``OrmFightPlayerSummary.name`` (and the corresponding
#: ``account_name`` / ``subgroup`` columns where applicable). Names
#: longer than this are silently truncated to fit the column.
#: Centralised here so a future schema bump (e.g. ``String(256)``)
#: only needs to touch this constant.
MAX_NAME_LEN: Final[int] = 128


def _sanitize_name(name: str | None, max_length: int = MAX_NAME_LEN) -> str:
    """Strip NUL (0x00) bytes from a name; coerce None to empty string; truncate to ``max_length``.

    PostgreSQL TEXT/VARCHAR columns cannot contain 0x00 (the byte is
    reserved as the C-string terminator in the wire protocol). The
    arcdps parser can yield skill names with embedded NULs from
    malformed EVTC skill tables (the ``MAX_SKILL_NAME_BYTES`` check
    surfaces the boundary as a WARNING and stops reading, but the
    YIELDED skills before the cut-off may still contain NULs). An
    unguarded INSERT raises ``psycopg.DataError`` and rolls back the
    whole transaction, losing the fight row + agents + skills.

    Additionally, the arcdps parser can yield ``name_len`` up to
    ``MAX_SKILL_NAME_BYTES = 4096`` for skill names -- a 200-char
    custom skill name from an arcdps add-on would otherwise fail the
    INSERT with ``value too long for type character varying(128)``
    and roll back the whole ``_save_fight`` transaction (losing the
    fight row + agents + skills). The truncation is silent (no
    warning) because the column constraint is the canonical source
    of truth and a future schema bump will lift the cap.

    Policy (applied in order):
        1. ``None`` and empty string round-trip to the empty string.
        2. Strip NUL (0x00) bytes only. Other control characters
           (tab, newline, etc.) are preserved because they're
           sometimes part of legitimate skill names (e.g.
           add-on-supplied custom names).
        3. Truncate to ``max_length`` (default 128, the String(128)
           column constraint). Applied AFTER NUL stripping so a
           name with NULs followed by > 128 chars of content is
           truncated on the surviving (post-strip) string, not on
           the original (pre-strip) string.

    An all-NUL name collapses to the empty string, which the ORM
    accepts (String(128) NOT NULL with an empty value is valid).

    Used by :func:`_save_fight` for ALL name-like fields (agent.name,
    skill.name, account_name, subgroup) AND by
    :func:`_persist_player_summaries` for the summary's ``name`` +
    ``account_name`` to centralise the sanitization contract at
    every ORM write boundary.
    """
    if not name:
        return ""
    return name.replace("\x00", "")[:max_length]


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
        assert account is not None  # noqa: S101
        # Last-seen name (overwrite on every event after the first)
        # + first-seen profession / elite (initialised on the first
        # event). The ``account in per_account`` branch is the
        # subsequent-event path; the else branch is the
        # first-event path that seeds the bucket. This replaces
        # the earlier ``bucket["set"]`` sentinel which conflated
        # "first" and "subsequent" in the same dict as the data.
        if account in per_account:
            bucket: dict[str, int | str] = per_account[account]
            # v0.10.2 hotfix followup #5: route the bucket's ``name``
            # through :func:`_sanitize_name` so the sanitization
            # contract is centralised at every ORM write boundary
            # (the same helper ``_save_fight`` uses for
            # ``OrmFightAgent.name``). The ``OrmFightAgent`` here is
            # already NUL-stripped (the write path runs
            # ``_sanitize_name`` before INSERT) AND bounded to 68
            # bytes by the arcdps combo string layout, so the call
            # is defensive -- but it keeps the new 128-char
            # truncation consistent across the two ORM write
            # boundaries and catches any future regression that
            # bypasses the agent-side write path.
            bucket["name"] = _sanitize_name(agent.name)
        else:
            bucket = {
                "damage": 0,
                "healing": 0,
                "strip": 0,
                "name": _sanitize_name(agent.name),
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

    # v0.10.2 hotfix followup: surface silent 0-summary failures.
    # If we got past the source_map check (player agents with
    # account_name exist) but the event loop yielded 0 per_account
    # entries, the events likely have wrong source_agent_id values
    # -- the parser misreads the event-stream offset when the skill
    # table is malformed (see the ``MAX_SKILL_NAME_BYTES`` warning
    # in :mod:`gw2_evtc_parser`). This is a defensive observability
    # log so operators can spot the regression in monitoring. The
    # behavior is unchanged (still 0 summary rows); the WARNING
    # just makes the silent failure visible. The corresponding
    # v0.10.3 hotfix should fix the parser-side root cause
    # (either fail the whole parse on a malformed skill table or
    # recover the correct event offset by scanning forward for the
    # cbtevent magic).
    if not per_account and source_map:
        logger.warning(
            "fight %s: %d player agent(s) with account_name but 0 summary "
            "rows; events likely have wrong source_agent_id (parser skill "
            "table misreading cascade -- see v0.10.3 parser fix)",
            orm_fight.id,
            len(source_map),
        )

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
        # v0.10.2 hotfix followup #5: route the loop key (the
        # ``account_name`` PK) through :func:`_sanitize_name` so the
        # sanitization contract is centralised at every ORM write
        # boundary (the same helper ``_save_fight`` uses for
        # ``OrmFightAgent.account_name``). The ``account_name`` here
        # is already NUL-stripped (the source ``OrmFightAgent`` was
        # sanitized in ``_save_fight``) AND bounded to 68 bytes by
        # the arcdps combo-string layout, so the call is defensive
        # -- but it keeps the new 128-char truncation consistent
        # across the two ORM write boundaries.
        sanitized_account = _sanitize_name(account_name)
        # Defensive guard: an all-NUL ``account_name`` (from a
        # malformed arcdps record) would be NUL-stripped to the
        # empty string by ``_sanitize_name``. The ``String(128) NOT
        # NULL`` column would happily accept an empty string, so
        # the INSERT would silently succeed and create a
        # degenerate row with ``account_name=""``. The
        # ``source_map`` filter (``if a.is_player and
        # a.account_name``) already filters this case at the
        # source_map level (the ORM's NUL-stripped ``account_name``
        # is the empty string, which is falsy and therefore
        # excluded), so this guard is a load-bearing coincidence
        # pin -- if a future refactor bypasses the source_map
        # filter (e.g. reads the account_name from a different
        # source), the guard still drops the degenerate row.
        # The log line is INFO (not WARNING) because the case
        # cannot happen in the current code path; the log makes
        # the guard visible to operators who might wonder why a
        # row is missing.
        if not sanitized_account:
            logger.info(
                "fight %s: skipping summary row for account_name=%r "
                "(sanitized to empty string after NUL strip; "
                "degenerate input -- see v0.10.3 parser fix for "
                "all-NUL account_name detection)",
                orm_fight.id,
                account_name,
            )
            continue
        # The ``bucket["name"]`` is already routed through
        # ``_sanitize_name`` at the bucket-set site (above), so the
        # value is guaranteed NUL-free and <= 128 chars. The
        # ``str(...)`` cast is removed because the bucket value is
        # already a ``str`` post-sanitization.
        db.add(
            OrmFightPlayerSummary(
                fight_id=orm_fight.id,
                account_name=sanitized_account,
                name=bucket["name"],
                profession=int(bucket["prof"]),
                elite_spec=int(bucket["elite"]),
                total_damage=int(bucket["damage"]),
                total_healing=int(bucket["healing"]),
                total_buff_removal=int(bucket["strip"]),
            ),
        )
