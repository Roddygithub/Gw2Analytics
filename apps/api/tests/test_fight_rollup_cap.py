"""v0.10.2 hotfix followup #12: per-target roll-up lists are capped at 100 rows.

Pre-fix: when the v0.10.3 parser bug produced hundreds of thousands of
unique garbage ``agent_id`` values (from a misread ``source_agent_id``),
the per-target aggregators in :func:`get_fight_events` and
:func:`get_fight_skills` happily grouped by ALL of them. The JSON
response exploded to multi-MB, the connection dropped (HTTP 000 / the
Next.js "fetch failed" timeout surfaced on the fight drilldown page),
and the analyst lost the page to a transparent error.

Post-fix: the route handler slices the per-target roll-up lists to
``[:100]`` after the aggregator runs. The aggregators already order
rows by damage / healing / strip descending (the canonical "top-N"
shape), so the kept 100 rows ARE the meaningful analyst signal --
the dropped 50+ are the noise floor. ``event_windows`` is NOT
capped -- it groups by time bucket, so its row count is naturally
bounded by the fight duration (a 30-minute fight with ``window_s=5``
yields 360 rows; with ``window_s=1`` it yields 1800 rows; both are
acceptable for an analyst's "where is the spike?" chart).

The 4 tests below cover the 4 capped roll-up lists (3 in
``GET /fights/{id}/events`` + 1 in ``GET /fights/{id}/skills``) by
seeding a fight with 150 unique targets / skills and asserting the
response is sliced to exactly 100 rows AND the top-100 by
descending magnitude is preserved. The cap invariant is the
canonical "what the analyst gets" guarantee; a future refactor
that silently drops the cap would regress the response-size
bound and surface the original "fetch failed" symptom.
"""

from __future__ import annotations

import struct
import time
import uuid as _uuid
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from gw2analytics_api.main import app

client = TestClient(app)

# V1.3 EVTC layout (matches libs/gw2_evtc_parser parser.py).
_HEADER_FMT = "<4s8sBHBI IB"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 25
_AGENT_RECORD_FMT = "<QIIhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)  # 24
_AGENT_NAME_SIZE = 72
_AGENT_SIZE = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96
_SKILL_HEADER_FMT = "<II"
_SKILL_HEADER_SIZE = struct.calcsize(_SKILL_HEADER_FMT)  # 8
_EVENT_FMT = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)  # 64


def _make_cbtevent(
    time_ms: int,
    src: int,
    dst: int,
    value: int,
    skill_id: int,
    *,
    is_statechange: int = 0,
    is_nondamage: int = 0,
    buff_dmg: int = 0,
) -> bytes:
    """Pack one 64-byte cbtevent record matching the parser's struct layout.

    Mirrors the ``_make_cbtevent`` helper in
    :mod:`apps.api.tests.test_uploads_e2e`; copied here so the cap
    tests are self-contained and don't share fixture state with the
    other e2e suite (the conftest's ``_isolate_test_state`` already
    isolates DB state; in-file fixture isolation keeps the e2e
    suite's wallclock from coupling to this file's 4 151-agent
    fixtures).
    """
    return struct.pack(
        _EVENT_FMT,
        time_ms,
        src,
        dst,
        value,
        buff_dmg,
        0,
        skill_id,
        0,
        0,
        0,
        0,
        is_nondamage,
        is_statechange,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )[:_EVENT_SIZE]


def _make_minimal_zevtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str,
    skills: list[tuple[int, str]] | None = None,
    events: list[bytes] | None = None,
) -> bytes:
    """Build a synthetic ``.zevtc`` blob (zip wrapper around EVTC).

    Mirrors the V1.3 layout the parser expects: 25-byte header +
    ``agent_count`` x 96-byte agent records +
    ``skill_count`` x variable-size skill records + N x 64-byte cbtevent
    records. The 151-agent fixtures in this file stay under the 1M-agent
    parser limit (the parser reads ``header.agent_count`` agents
    in a single pass with no internal cap).
    """
    if skills is None:
        skills = []
    if events is None:
        events = []
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        header = struct.pack(
            _HEADER_FMT,
            b"EVTC",
            build.encode("ascii"),
            0,
            0,
            0,
            len(agents),
            len(skills),
            0,  # lang
        )
        assert len(header) == _HEADER_SIZE
        body = bytearray()
        for aid, prof, elite, name, is_player in agents:
            prefix = struct.pack(
                _AGENT_RECORD_FMT,
                aid,
                prof,
                elite,
                0,
                0,
                0,
                0,
            )
            if is_player:
                raw = name.encode() + b"\x00" + f":synth.{aid}".encode() + b"\x00\x00"
            else:
                raw = name.encode() + b"\x00"
            if len(raw) > _AGENT_NAME_SIZE:
                msg = f"agent name region {len(raw)} > {_AGENT_NAME_SIZE}"
                raise ValueError(msg)
            name_buf = raw + b"\x00" * (_AGENT_NAME_SIZE - len(raw))
            body += prefix + name_buf
        for skill_id, skill_name in skills:
            name_bytes = skill_name.encode("utf-8")
            skill_record = (
                struct.pack(_SKILL_HEADER_FMT, skill_id, len(name_bytes)) + name_bytes + b"\x00"
            )
            body += skill_record
        for ev in events:
            body += ev
        zf.writestr("fight.evtc", header + bytes(body))
    return buf.getvalue()


def _wait_for_upload_completion(upload_id: str) -> str:
    """Poll the upload status until completed, then return the ``fight_id``.

    Mirrors the helper in
    :mod:`apps.api.tests.test_uploads_e2e`. The 5s ceiling is
    generous for a fixture-sized blob (the parser completes in
    milliseconds). The trailing ``time.sleep(0.1)`` gives the
    parser a beat to write the events blob before the test's
    subsequent ``GET /fights/{id}/events`` query hits MinIO.
    """
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        if upload_resp.status_code == 200 and upload_resp.json()["status"] == "completed":
            time.sleep(0.1)
            return str(upload_resp.json()["fight_id"])
        time.sleep(0.1)
    msg = f"upload {upload_id} did not reach 'completed' within 5s"
    raise AssertionError(msg)


def test_target_dps_rollup_capped_at_100_rows() -> None:
    """v0.10.2 hotfix followup #12: ``target_dps`` is capped at 100 rows.

    Seeds 150 unique NPC targets + 150 damage events (one per
    target, descending damage values 1..150) and asserts the
    ``/fights/{id}/events`` response has exactly 100 ``target_dps``
    rows, ordered by ``total_damage`` descending, with the kept
    100 being the top-100 by damage (i.e. damages 150..51;
    the bottom 50 with damages 1..50 are dropped).

    Pre-fix: the aggregator returned 150 rows, the JSON response
    was multi-MB, the connection dropped. Post-fix: the cap
    slices to 100. The ordering invariant confirms the cap
    preserved the analyst-relevant top-N (a future refactor
    that sorted by ``target_agent_id`` ascending post-cap would
    regress this).
    """
    suffix = _uuid.uuid4().hex[:8]
    n_targets = 150
    n_keep = 100
    base_id_player = 200_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    npc_ids = list(range(1_000_000_000, 1_000_000_000 + n_targets))
    base_skill_a = 2_000_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    # 1 player (source) + 150 NPCs (targets). Player has the
    # canonical ``:synth.<id>`` combo string; NPCs are name-only
    # (no combo string, no account_name) -- the target rollup
    # does NOT filter on is_player, so NPCs are valid targets.
    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_player, 2, 18, f"CapDpsTester {suffix}", True),
    ]
    for npc_id in npc_ids:
        agents.append((npc_id, 0, 0, f"NPC_{npc_id}", False))

    # 150 damage events, one per NPC, descending damage values.
    # Target i (1..150) receives damage (n_targets - i + 1) =
    # 150, 149, ..., 1. The aggregator's deterministic-ordering
    # contract is "descending by total_damage" (matches
    # ``target_dps.py``'s pair-wise compare), so the top-100
    # by damage are targets 0..99 in descending order.
    events: list[bytes] = []
    for i, npc_id in enumerate(npc_ids):
        damage = n_targets - i  # 150, 149, ..., 1
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_player,
                dst=npc_id,
                value=damage,
                skill_id=base_skill_a,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build=f"2025{int(suffix[:4], 16) % 10000:04d}" if len(suffix) >= 4 else "20250925",
        skills=[(base_skill_a, f"CapDpsSkill {suffix}")],
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    events_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()

    # Cap: exactly 100 rows, not 150. The 50 dropped rows are
    # the bottom of the descending order (damages 1..50).
    assert len(summary["target_dps"]) == n_keep, (
        f"target_dps cap broken: expected {n_keep} rows, got "
        f"{len(summary['target_dps'])} (v0.10.2 hotfix followup #12 regression)"
    )
    # Ordering invariant: rows are descending by total_damage.
    damages = [r["total_damage"] for r in summary["target_dps"]]
    assert damages == sorted(damages, reverse=True), (
        f"target_dps rows not in descending damage order: {damages[:5]}..."
    )
    # Top-100 invariant: the 100 kept rows are damages 150..51.
    # The 100th-highest damage in [1, 150] is 150 - 100 + 1 = 51.
    assert min(damages) == n_targets - n_keep + 1, (
        f"cap kept wrong rows: expected min damage {n_targets - n_keep + 1}, "
        f"got {min(damages)} (v0.10.2 hotfix followup #12 regression)"
    )
    # Sanity: the highest damage (150) is preserved.
    assert max(damages) == n_targets, (
        f"cap dropped top rows: expected max damage {n_targets}, got {max(damages)}"
    )
    # Negative invariant: the dropped 50 values (damages 1..50) are
    # NOT in the response. A future refactor that dropped the cap
    # (returning all 150 rows) would surface these; a future refactor
    # that mis-sorted (e.g. sort by target_agent_id ascending post-cap)
    # could also keep some of them. The disjoint check pins both
    # failure modes in one assertion.
    dropped = set(range(1, n_targets - n_keep + 1))
    leaked = set(damages) & dropped
    assert not leaked, (
        f"cap kept dropped values {sorted(leaked)}; v0.10.2 hotfix followup #12 regression"
    )


def test_target_healing_rollup_capped_at_100_rows() -> None:
    """v0.10.2 hotfix followup #12: ``target_healing`` is capped at 100 rows.

    Strict parallel of
    :func:`test_target_dps_rollup_capped_at_100_rows` but for
    heals. The v0.10.3 parser bug affects the source_agent_id,
    not the target_agent_id directly, but the SAME per-target
    aggregator grouping logic produces the same explosion when
    the parser misreads other agent-related fields; the cap is
    applied uniformly to all 3 per-target rollups (DPS +
    Healing + BuffRemoval).
    """
    suffix = _uuid.uuid4().hex[:8]
    n_targets = 150
    n_keep = 100
    base_id_player = 200_001 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    npc_ids = list(range(1_000_000_000, 1_000_000_000 + n_targets))
    base_skill_a = 2_000_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_player, 2, 18, f"CapHealTester {suffix}", True),
    ]
    for npc_id in npc_ids:
        agents.append((npc_id, 0, 0, f"NPC_{npc_id}", False))

    # 150 heal events (``is_nondamage=1``, ``value>0``). Each
    # target receives a different heal value so the descending
    # order is deterministic.
    events: list[bytes] = []
    for i, npc_id in enumerate(npc_ids):
        heal = (n_targets - i) * 10  # 1500, 1490, ..., 10
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_player,
                dst=npc_id,
                value=heal,
                skill_id=base_skill_a,
                is_nondamage=1,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build=f"2025{int(suffix[:4], 16) % 10000:04d}" if len(suffix) >= 4 else "20250925",
        skills=[(base_skill_a, f"CapHealSkill {suffix}")],
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    events_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()

    assert len(summary["target_healing"]) == n_keep, (
        f"target_healing cap broken: expected {n_keep} rows, got "
        f"{len(summary['target_healing'])} (v0.10.2 hotfix followup #12 regression)"
    )
    heals = [r["total_healing"] for r in summary["target_healing"]]
    assert heals == sorted(heals, reverse=True), (
        f"target_healing rows not in descending order: {heals[:5]}..."
    )
    assert min(heals) == (n_targets - n_keep + 1) * 10
    assert max(heals) == n_targets * 10
    # Negative invariant: the dropped 50 values (heals 10..500 stepping by 10)
    # are NOT in the response.
    dropped = {v * 10 for v in range(1, n_targets - n_keep + 1)}
    leaked = set(heals) & dropped
    assert not leaked, (
        f"cap kept dropped values {sorted(leaked)}; v0.10.2 hotfix followup #12 regression"
    )


def test_target_buff_removal_rollup_capped_at_100_rows() -> None:
    """v0.10.2 hotfix followup #12: ``target_buff_removal`` is capped at 100 rows.

    Uses pure-strip events (``value=0``, ``buff_dmg>0``,
    ``is_nondamage=1``) so each cbtevent yields ONLY a
    :class:`BuffRemovalEvent` (no dual-emit heal). This is the
    canonical "pure strip" path -- the same kind of corrupting /
    confusion skill that strips a boon without healing.
    """
    suffix = _uuid.uuid4().hex[:8]
    n_targets = 150
    n_keep = 100
    base_id_player = 200_002 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    npc_ids = list(range(1_000_000_000, 1_000_000_000 + n_targets))
    base_skill_a = 2_000_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_player, 2, 18, f"CapStripTester {suffix}", True),
    ]
    for npc_id in npc_ids:
        agents.append((npc_id, 0, 0, f"NPC_{npc_id}", False))

    # 150 pure-strip events. ``value=0`` skips the heal
    # accumulator; ``buff_dmg>0`` is the only thing that
    # produces a :class:`BuffRemovalEvent` in the parser.
    events: list[bytes] = []
    for i, npc_id in enumerate(npc_ids):
        strip = (n_targets - i) * 5  # 750, 745, ..., 5
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_player,
                dst=npc_id,
                value=0,
                buff_dmg=strip,
                skill_id=base_skill_a,
                is_nondamage=1,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build=f"2025{int(suffix[:4], 16) % 10000:04d}" if len(suffix) >= 4 else "20250925",
        skills=[(base_skill_a, f"CapStripSkill {suffix}")],
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    events_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()

    assert len(summary["target_buff_removal"]) == n_keep, (
        f"target_buff_removal cap broken: expected {n_keep} rows, got "
        f"{len(summary['target_buff_removal'])} "
        f"(v0.10.2 hotfix followup #12 regression)"
    )
    strips = [r["total_buff_removal"] for r in summary["target_buff_removal"]]
    assert strips == sorted(strips, reverse=True)
    assert min(strips) == (n_targets - n_keep + 1) * 5
    assert max(strips) == n_targets * 5
    # Negative invariant: the dropped 50 values (strips 5..250 stepping by 5)
    # are NOT in the response.
    dropped = {v * 5 for v in range(1, n_targets - n_keep + 1)}
    leaked = set(strips) & dropped
    assert not leaked, (
        f"cap kept dropped values {sorted(leaked)}; v0.10.2 hotfix followup #12 regression"
    )


def test_skills_rollup_capped_at_100_rows() -> None:
    """v0.10.2 hotfix followup #12: ``/fights/{id}/skills`` per-skill list is capped at 100 rows.

    The per-skill rollup groups by ``skill_id`` (NOT
    ``target_agent_id``), so the v0.10.3 parser bug affects it
    via a DIFFERENT field -- the parser's skill-table read can
    misread ``skill_id`` bytes under the same conditions that
    misread ``source_agent_id``, producing hundreds of thousands
    of unique garbage skill_ids. The cap on the
    ``/fights/{id}/skills`` endpoint is the symmetric mitigation
    (the comment in ``routes/fights.py::get_fight_skills`` calls
    it out explicitly).

    Seeds 2 player agents + 150 unique skill_ids + 150 damage
    events (each using a different skill_id) and asserts the
    response has exactly 100 skill rows, ordered by
    ``total_damage`` descending.
    """
    suffix = _uuid.uuid4().hex[:8]
    n_skills = 150
    n_keep = 100
    base_id_a = 200_003 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    skill_ids = list(range(3_000_000_000, 3_000_000_000 + n_skills))

    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_a, 2, 18, f"CapSkillA {suffix}", True),
        (base_id_b, 1, 27, f"CapSkillB {suffix}", True),
    ]

    skills = [(sid, f"Skill_{sid}") for sid in skill_ids]

    # 150 damage events, each using a different skill_id.
    # The per-skill rollup groups by skill_id across all
    # events; with 150 unique skill_ids and 1 event per skill,
    # the rollup yields 150 rows.
    events: list[bytes] = []
    for i, sid in enumerate(skill_ids):
        damage = n_skills - i  # 150, 149, ..., 1
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_a,
                dst=base_id_b,
                value=damage,
                skill_id=sid,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build=f"2025{int(suffix[:4], 16) % 10000:04d}" if len(suffix) >= 4 else "20250925",
        skills=skills,
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    skills_resp = client.get(f"/api/v1/fights/{fight_id}/skills")
    assert skills_resp.status_code == 200, skills_resp.text
    payload = skills_resp.json()

    assert len(payload["skills"]) == n_keep, (
        f"skills cap broken: expected {n_keep} rows, got "
        f"{len(payload['skills'])} (v0.10.2 hotfix followup #12 regression)"
    )
    damages = [r["total_damage"] for r in payload["skills"]]
    assert damages == sorted(damages, reverse=True)
    assert min(damages) == n_skills - n_keep + 1
    assert max(damages) == n_skills
    # Negative invariant: the dropped 50 values (damages 1..50) are
    # NOT in the response.
    dropped = set(range(1, n_skills - n_keep + 1))
    leaked = set(damages) & dropped
    assert not leaked, (
        f"cap kept dropped values {sorted(leaked)}; v0.10.2 hotfix followup #12 regression"
    )
