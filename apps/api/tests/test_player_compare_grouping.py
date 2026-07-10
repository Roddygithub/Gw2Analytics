"""Plan 144 hermetic tests for ``_group_contributions_by_account``.

The helper backs ``GET /api/v1/players/compare/timeline``. It replaces the
v0.10.0 plan 032 defect where a plain ``dict[...] = {}`` + unconditional
``d[account].append(c)`` raised ``KeyError`` on the first contribution of
every account (crashing the endpoint on any non-empty dataset). These
tests pin the corrected contract WITHOUT Postgres; the DB-backed
``test_player_compare.py`` validates the end-to-end route on CI.
"""

from __future__ import annotations

import pytest

from gw2_analytics.player_profile import FightContribution
from gw2analytics_api.routes.player_compare import _group_contributions_by_account


@pytest.fixture(autouse=True)
def _isolate_test_state() -> None:
    """No-op shadow of the conftest's DB-cleanup autouse.

    These tests are pure-unit (no Postgres); the module-scoped shadow
    disables only the conftest's DB-cleanup autouse for this file (same
    idiom as ``test_event_dispatch.py``). If a future test here needs a
    DB, remove this shadow.
    """


def _contribution(account: str, fight_id: str = "fight-1", damage: int = 100) -> FightContribution:
    return FightContribution(fight_id=fight_id, account_name=account, total_damage=damage)


def test_empty_contributions_preseed_all_requested_accounts() -> None:
    # The old code crashed here (KeyError); the new code returns one
    # empty list per requested account so each still gets a series.
    grouped = _group_contributions_by_account([], [":a.1", ":b.2"])
    assert grouped == {":a.1": [], ":b.2": []}


def test_contributions_routed_to_requested_accounts() -> None:
    contributions = [
        _contribution(":a.1", "f1", 100),
        _contribution(":a.1", "f2", 50),
        _contribution(":b.2", "f1", 200),
    ]
    grouped = _group_contributions_by_account(contributions, [":a.1", ":b.2"])
    assert [c.fight_id for c in grouped[":a.1"]] == ["f1", "f2"]
    assert [c.total_damage for c in grouped[":a.1"]] == [100, 50]
    assert [c.fight_id for c in grouped[":b.2"]] == ["f1"]


def test_non_requested_account_contributions_are_dropped() -> None:
    # _compute_contributions rolls up ALL accounts in the DB; only the
    # requested ones must appear in the result.
    contributions = [_contribution(":a.1"), _contribution(":other.9")]
    grouped = _group_contributions_by_account(contributions, [":a.1", ":b.2"])
    assert set(grouped) == {":a.1", ":b.2"}  # :other.9 excluded
    assert len(grouped[":a.1"]) == 1
    assert grouped[":b.2"] == []


def test_unknown_requested_account_gets_empty_list() -> None:
    # An account requested but present in no fight still gets a key
    # (-> an empty-points series downstream, not a 404).
    grouped = _group_contributions_by_account([_contribution(":a.1")], [":a.1", ":unknown.0"])
    assert grouped[":unknown.0"] == []
    assert len(grouped[":a.1"]) == 1
