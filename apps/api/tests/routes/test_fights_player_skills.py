"""Route-level tests for ``GET /api/v1/fights/{id}/players/{account_name}/skills``.

Tour 4 v0.10.13 plan 044: Skill build analyser (per-player skill
roll-up + loadout attribution per docs/v0.8.0-web-design.md §6).

The pattern mirrors :file:`test_fights_skills.py`: every test
posts a synthetic ``.zevtc`` blob (built via the shared
:func:`make_minimal_zevtc` helper) + waits for the upload + parse
+ persist lifecycle to complete, then issues the ``GET`` against
the freshly-populated DB + MinIO state.

The :data:`client` fixture (function-scoped + lifespan-aware per
the conftest) is declared as a pytest parameter so each test
sees its own lifespan (the lifespan is what populates Redis +
arq_pool + schema-drift guards at startup; the module-level
``client = TestClient(app)`` pattern in the older
``test_fights_skills.py`` skipped the per-test lifespan and
broke as soon as the lifespan started touching the redis pool).

The synthetic account-name convention is ``"synth.{aid}"`` (the
:mod:`_evtc_builder` exposes this for every is-player=True agent --
see :func:`make_minimal_zevtc`'s ``account = f":synth.{aid}"``
encoding). The endpoint's :func:`lstrip(\":\")` defensive strip
plus the ORM's ``:``-stripped canonical form make the lookup
key exactly ``"synth.{aid}"``.
"""

from __future__ import annotations

import uuid as _uuid

from fastapi.testclient import TestClient

from ._evtc_builder import make_cbtevent, make_minimal_zevtc, post_upload


def test_player_skills_200_with_damage_attribution(
    client: TestClient,
) -> None:
    """Player ``a`` (who issued 2 outgoing damage hits) sees the skill in their per-player rollup.

    Validates the source-side attribution contract:
    - the endpoint's pre-filter is keyed on
      ``events.source_agent_id == player_agent.agent_id`` (B2
      strategy from Tour 4's design matrix),
    - and the existing ``SkillUsageAggregator`` correctly
      rolls up damage events under the player's ``synth.{a}``
      account-name lookup.
    """
    suffix = _uuid.uuid4().hex[:8]
    a = 200_000 + int(suffix[:4], 16)
    b = a + 1
    sk = 2_000_000 + int(suffix[:4], 16)

    blob = make_minimal_zevtc(
        [
            (a, 2, 18, f"W {suffix}", True),
            (b, 1, 27, f"G {suffix}", True),
        ],
        build=f"2025{suffix[:4]}",
        skills=[(sk, "TestSkill")],
        events=[
            make_cbtevent(1_000, src=a, dst=b, value=1000, skill_id=sk),
            make_cbtevent(2_000, src=a, dst=b, value=2000, skill_id=sk),
        ],
    )
    fight_id = post_upload(client, blob)

    resp = client.get(f"/api/v1/fights/{fight_id}/players/synth.{a}/skills")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    # Wire-shape contract: ``PlayerSkillsOut`` schema.
    assert payload["fight_id"] == fight_id
    assert payload["account_name"] == f"synth.{a}"
    assert payload["agent_id"] == a
    # The ``loadout`` block mirrors the ``AgentOut`` wire shape
    # (``profession`` + ``elite_spec`` are the formatted strings
    # from :func:`format_profession` / :func:`format_elite_spec`).
    # Don't assert the EXACT string -- the project intent is the
    # ``format_*`` helpers convert int -> label; we'd rather
    # verify the helpers exist and produce a non-empty string
    # than lock tests to specific enum labels. Matches the
    # minimal assertion style of :file:`test_fights_skills.py`
    # (which keeps the per-row assertions non-brittle).
    assert isinstance(payload["loadout"]["profession"], str)
    assert len(payload["loadout"]["profession"]) > 0
    assert isinstance(payload["loadout"]["elite_spec"], str)
    assert len(payload["loadout"]["elite_spec"]) > 0
    # The equipped-skill V1 stub: present + empty list (NOT
    # `null` -- the field is intentionally an empty list so the
    # frontend renders the empty-state panel without a conditional
    # branch).
    assert payload["loadout"]["equipped_skill_ids"] == []
    # ``skills`` is the per-player per-skill rollup (empty key-by-`
    # skill_id` aggregation after the B2 pre-filter). The 2 outgoing
    # damage hits from ``a`` collapse into ONE row (single ``sk``)
    # with ``hit_count == 2``.
    assert isinstance(payload["skills"], list)
    assert len(payload["skills"]) == 1
    assert payload["skills"][0]["skill_id"] == sk
    assert payload["skills"][0]["skill_name"] == "TestSkill"
    assert payload["skills"][0]["hit_count"] == 2
    assert payload["skills"][0]["total_damage"] == 3000


def test_player_skills_200_idle_player_empty_skills(
    client: TestClient,
) -> None:
    """Player ``b`` (target-only, no outgoing events) returns 200 with empty skills.

    Validates the 0-skills + idle-player edge case contract (the
    agent row resolves but no events with ``source_agent_id ==
    player_agent.agent_id`` exist): returns ``200 OK`` with
    ``skills: []``. Distinguishable from "player not found in
    fight" which returns 404.
    """
    suffix = _uuid.uuid4().hex[:8]
    a = 210_000 + int(suffix[:4], 16)
    b = a + 1
    sk = 2_100_000 + int(suffix[:4], 16)

    blob = make_minimal_zevtc(
        [
            (a, 2, 18, f"W {suffix}", True),
            (b, 1, 27, f"G {suffix}", True),
        ],
        build=f"2025{suffix[:4]}",
        skills=[(sk, "TestSkill")],
        events=[
            # Only ``a`` issues damage; ``b`` is only the target.
            make_cbtevent(1_000, src=a, dst=b, value=1000, skill_id=sk),
        ],
    )
    fight_id = post_upload(client, blob)

    resp = client.get(f"/api/v1/fights/{fight_id}/players/synth.{b}/skills")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["account_name"] == f"synth.{b}"
    assert payload["agent_id"] == b
    assert payload["skills"] == []  # empty list, NOT 404


def test_player_skills_404_unknown_account(
    client: TestClient,
) -> None:
    """Account name that does NOT match any agent in the fight returns 404.

    The route raises ``HTTPException(404, "player not found in
    fight")`` on the ``OrmFightAgent`` lookup returning None --
    the canonical "agent not registered" contract.
    """
    suffix = _uuid.uuid4().hex[:8]
    a = 220_000 + int(suffix[:4], 16)
    b = a + 1

    blob = make_minimal_zevtc(
        [
            (a, 2, 18, f"W {suffix}", True),
            (b, 1, 27, f"G {suffix}", True),
        ],
        build=f"2025{suffix[:4]}",
    )
    fight_id = post_upload(client, blob)

    resp = client.get(f"/api/v1/fights/{fight_id}/players/UnknownAccount.0000/skills")
    assert resp.status_code == 404


def test_player_skills_404_unknown_fight(
    client: TestClient,
) -> None:
    """Unknown ``fight_id`` returns 404 from the shared blob loader.

    The :func:`_load_fight_events` helper raises the canonical
    404 contract (``HTTPException(404, "fight not found")``)
    BEFORE the agent lookup is attempted, so the URL contract
    surfaces the 404 from the shared helper -- NOT from the
    explicit ``player_agent is None`` branch (which would mask
    the shared helper's 404 message).
    """
    resp = client.get("/api/v1/fights/nonexistent-fight-id/players/synth.1/skills")
    assert resp.status_code == 404
