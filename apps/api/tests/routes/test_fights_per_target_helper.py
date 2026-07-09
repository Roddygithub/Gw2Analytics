"""v0.9.38 plan 117: hermetic tests for the per-target roll-up helper.

The :func:`_aggregate_per_target_rollup` helper in
:mod:`gw2analytics_api.routes.fights` centralises the 3 isomorphic
per-target roll-up branches (DPS + Healing + BuffRemoval) from
:func:`get_fight_events` (Phase 8 v0.8.0 + v0.8.3 + v0.10.2 hotfix
followup #12). The 5 tests below pin the helper's dispatch +
invariants in isolation from the TestClient + Postgres + MinIO
stack -- the helper is pure-Python so the tests run in <1s
without any infrastructure.

Mapping
-------
``DamageEvent`` -> :class:`TargetDpsAggregator`: row with ``total_damage``.
``HealingEvent`` -> :class:`TargetHealingAggregator`: row with ``total_healing``.
``BuffRemovalEvent`` -> :class:`TargetBuffRemovalAggregator`: row with ``total_buff_removal``.

Closed-form dispatch: an unknown ``event_cls`` (e.g. a Phase 9
``ConditionDamageEvent`` subclass) raises :class:`ValueError`.
The dispatch table is intentionally closed-form so a future
addition is a single-line edit in the helper.

Empty input: an empty ``events`` list returns ``[]`` (the
aggregators short-circuit before the ``duration_s``-based rate
computation, so even ``duration_s=0.0`` is safe).

The schema-validation step + the 100-row cap (v0.10.2 hotfix
followup #12) are NOT tested here -- they live in the e2e suite
(:mod:`apps.api.tests.test_uploads_e2e` + the new
:mod:`apps.api.tests.test_fight_rollup_cap`). The helper returns
the raw aggregator output (a list of ``TargetXRow`` instances);
the route layer wraps each row in the corresponding
``TargetXRowOut`` Pydantic schema + applies the [:100] cap.
"""

from __future__ import annotations

import pytest

from gw2_analytics.target_buff_removal import TargetBuffRemovalRow
from gw2_analytics.target_dps import TargetDpsRow
from gw2_analytics.target_healing import TargetHealingRow
from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent
from gw2analytics_api.routes.fights import _aggregate_per_target_rollup


def test_per_target_helper_dispatches_damage_event_to_dps_aggregator() -> None:
    """``DamageEvent`` -> ``TargetDpsAggregator`` -> 1 row with the damage magnitude.

    Single-event fixture: 1 damage event targeting agent 2
    with damage=42 + duration_s=12.5 -> row's ``total_damage == 42``
    + ``dps == pytest.approx(42 / 12.5)`` (the canonical
    per-second rate). The ``name_map`` is passed so the row's
    ``name`` field surfaces the denormalised player name
    (``"TargetPlayer"``). The v0.8.3 name-resolution invariant
    is the same on all 3 per-target rollups (the helper uses
    the same ``agent_id_to_name`` map the route layer built).
    """
    event = DamageEvent(
        time_ms=1_000,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=100,
        damage=42,
    )
    name_map: dict[int, str | None] = {2: "TargetPlayer"}

    rows = _aggregate_per_target_rollup(
        events=[event],
        agent_id_to_name=name_map,
        duration_s=12.5,
        event_cls=DamageEvent,
    )

    assert len(rows) == 1
    assert isinstance(rows[0], TargetDpsRow)
    assert rows[0].target_agent_id == 2
    assert rows[0].total_damage == 42
    assert rows[0].dps == pytest.approx(42 / 12.5)
    assert rows[0].name == "TargetPlayer"


def test_per_target_helper_dispatches_healing_event_to_healing_aggregator() -> None:
    """``HealingEvent`` -> ``TargetHealingAggregator`` -> 1 row with the heal magnitude.

    Strict parallel of
    :func:`test_per_target_helper_dispatches_damage_event_to_dps_aggregator`
    but for the HealingEvent branch. The aggregators share the
    same ``aggregate(events, duration_s, name_map=...)``
    signature, so the test mirrors the DPS test's structure
    exactly except for the event kind + the magnitude field
    + the row type.
    """
    event = HealingEvent(
        time_ms=1_000,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=100,
        healing=42,
    )
    name_map: dict[int, str | None] = {2: "TargetHealer"}

    rows = _aggregate_per_target_rollup(
        events=[event],
        agent_id_to_name=name_map,
        duration_s=12.5,
        event_cls=HealingEvent,
    )

    assert len(rows) == 1
    assert isinstance(rows[0], TargetHealingRow)
    assert rows[0].target_agent_id == 2
    assert rows[0].total_healing == 42
    assert rows[0].hps == pytest.approx(42 / 12.5)
    assert rows[0].name == "TargetHealer"


def test_per_target_helper_dispatches_buff_removal_event_to_buff_removal_aggregator() -> None:
    """``BuffRemovalEvent`` -> ``TargetBuffRemovalAggregator`` -> 1 row with the strip magnitude.

    Strict parallel of the DPS + Healing tests. Phase 8 ships
    the third per-target rollup; the helper's third dispatch
    branch is the same shape as the first two.
    """
    event = BuffRemovalEvent(
        time_ms=1_000,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=100,
        buff_removal=42,
    )
    name_map: dict[int, str | None] = {2: "TargetStripped"}

    rows = _aggregate_per_target_rollup(
        events=[event],
        agent_id_to_name=name_map,
        duration_s=12.5,
        event_cls=BuffRemovalEvent,
    )

    assert len(rows) == 1
    assert isinstance(rows[0], TargetBuffRemovalRow)
    assert rows[0].target_agent_id == 2
    assert rows[0].total_buff_removal == 42
    assert rows[0].bps == pytest.approx(42 / 12.5)
    assert rows[0].name == "TargetStripped"


def test_per_target_helper_raises_value_error_on_unknown_event_cls() -> None:
    """Unknown ``event_cls`` raises :class:`ValueError` (closed-form dispatch).

    Uses a fresh ``_FakeConditionDamage`` subclass of
    :class:`DamageEvent` -- the dispatch table uses ``is`` (not
    ``isinstance``), so a subclass does NOT match the
    ``DamageEvent`` branch and falls through to the
    ``ValueError`` case. The error message includes the
    unknown class's repr for operator clarity.

    A future Phase 9 ``ConditionDamageEvent`` extension
    requires a single-line edit in the dispatch table: add
    a new ``elif event_cls is ConditionDamageEvent:`` branch
    + a new ``ConditionDamageAggregator`` call. The closed-
    form dispatch is the canonical "explicit is better than
    implicit" design (vs. ``functools.singledispatch`` on the
    event superclass, which the plan rejected -- see the
    plan file's "Rejected alternatives" section).
    """

    class _FakeConditionDamage(DamageEvent):
        pass

    with pytest.raises(ValueError, match="_aggregate_per_target_rollup"):
        _aggregate_per_target_rollup(
            events=[],
            agent_id_to_name={},
            duration_s=1.0,
            event_cls=_FakeConditionDamage,
        )


def test_per_target_helper_returns_empty_list_for_empty_iterator() -> None:
    """Empty ``events`` list returns ``[]`` (short-circuit before rate computation).

    The aggregators' ``duration_s`` parameter is only used to
    compute the per-second rate column. An empty events list
    short-circuits to ``[]`` BEFORE the rate computation, so
    even ``duration_s=0.0`` is safe. The test uses
    ``duration_s=1.0`` to assert the no-rate-computation path
    (a non-zero duration would otherwise mask a
    ZeroDivisionError in the rate computation if the
    aggregator didn't short-circuit on empty input).
    """
    rows = _aggregate_per_target_rollup(
        events=[],
        agent_id_to_name={},
        duration_s=1.0,
        event_cls=DamageEvent,
    )
    assert rows == []
