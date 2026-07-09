# Plan 110 (v0.9.36) — Test fixtures DRY consolidation: `_player` + `_npc` + `_fight` extraction to `tests/_fixtures.py`

## Files touched
- NEW `libs/gw2_analytics/tests/_fixtures.py` (NEW public module — `synthetic_player(...)`, `synthetic_npc(...)`, `synthetic_fight(...)`, `synthetic_fight_id(...)`, `SYNTHETIC_BUILD_VERSION`)
- `libs/gw2_analytics/tests/test_aggregate.py` (replace local `_player`/`_npc`/`_fight`/`_FIXED_FIGHT_ID` with `from tests._fixtures import ...`)
- `libs/gw2_analytics/tests/test_multi_fight.py` (same swap)
- `libs/gw2_analytics/tests/test_player_profile.py` (no local `_fight` helper, but the helper style for `_player` is structurally similar — adopt via a thin local wrapper for backward-compat, recommend migrating in a follow-up audit pass)
- `libs/gw2_analytics/tests/test_squad_rollup.py` (same)
- `libs/gw2_analytics/tests/test_per_fight_timeline.py` (same)
- `libs/gw2_analytics/tests/test_target_dps.py` + `test_target_healing.py` + `test_target_buff_removal.py` + `test_event_window.py` + `test_skill_usage.py` (no agent/fight builders today; their event builders are consolidated under plan 111)

## Findings (audit)

- `libs/gw2_analytics/tests/test_aggregate.py::synthetic fixture` block (lines ~50-90) defines `_player(aid, *, account_name, name, subgroup, profession, elite) -> Agent`, `_npc(aid, name) -> Agent`, `_fight(agents, skills=None, *, encounter_id=0) -> Fight`, and the module-level `_FIXED_FIGHT_ID: Final[str] = "deadbeef" * 8`.
- `libs/gw2_analytics/tests/test_multi_fight.py::synthetic fixture` block (lines ~30-65) defines `_player(aid, *, account_name, name="X", subgroup="", profession=Profession.WARRIOR, elite=EliteSpec.BERSERKER) -> Agent`, `_npc(aid, name="Mob") -> Agent`, `_fight(fight_id, agents, skills=None, *, encounter_id=0) -> Fight`.
- The 2 helper blocks are NEARLY byte-identical:
  - `_player`: same `Agent(...)` constructor call; multi_fight supplies defaults for `name` / `subgroup` / `profession` / `elite`, test_aggregate does not. Subset/superset difference.
  - `_npc`: structurally identical (only `id` + `name` differ).
  - `_fight`: structurally identical except the `id` argument is positional in test_multi_fight + passed-through to `Fight(...)`; in test_aggregate the `id` is the module-level `_FIXED_FIGHT_ID`.
- The `EvtcHeader` build inside `_fight` is also near-identical:
  - test_aggregate: `EvtcHeader(build_version="20250925", encounter_id=encounter_id, agent_count=len(agents), skill_count=len(skills))`
  - test_multi_fight: same shape but `encounter_id=encounter_id` + `agent_count=len(agents)` + `skill_count=len(skills)`.
- The `aggregate.py::_check_invariants` SHA-256-shaped sentinel `_FIXED_FIGHT_ID = "deadbeef" * 8` is also used at the same field; both test files use the same sentinel. Drift hazard: a future plan that decides to keep this internal-vs-fixup affinity could be lost in 2 copies.
- The duplication is a real DRY violation: future maintenance (e.g. adding a per-test override of `EvtcHeader.build_version` for v0.5.0 fallback tests; or adding a `default_squad_position=` arg) requires editing 2+ files in parallel + keeps the parameters in lock-step manually. The historical pattern (3 v0.9.27 plans 083-085 consolidated per-target aggregator template via `_per_target_base.py::PerTargetRollupBase`) shows this kind of consolidation pays off.

## Fix

1. NEW `libs/gw2_analytics/tests/_fixtures.py`:

   ```python
   """Shared synthetic fixtures for :mod:`gw2_analytics` tests.

   The :class:`~gw2_core.Agent` + :class:`~gw2_core.Fight` builders
   were duplicated across ``test_aggregate.py`` and
   ``test_multi_fight.py`` (near-byte-identical helpers). This
   module is the canonical single source; the 2 test files
   import from here. Other test files (test_squad_rollup,
   test_per_fight_timeline, etc.) migrate via a thin local
   wrapper that re-exports the canonical helpers with a
   domain-specific prefix (recommended as a follow-up
   audit pass; not blocking for this plan).

   The synthetic fixture pattern keeps the unit tests independent
   of the EVTC binary parser's edge-case coverage -- the
   :class:`~gw2_analytics.aggregate.SingleFightAggregator` is
   fed synthetic ``Agent`` / ``Skill`` / ``EvtcHeader`` ``Fight``
   inputs that match the realistic field shapes without needing
   a real `.zevtc` fixture.
   """
   from __future__ import annotations

   from datetime import UTC, datetime
   from typing import Final

   from gw2_core import (
       Agent,
       EliteSpec,
       EvtcHeader,
       Fight,
       GameType,
       Profession,
       Skill,
   )

   # Canonical SHA-256-shaped sentinel for synthetic test fights.
   # Matches the dimension of a real SHA-256 hex digest (64 chars)
   # so ``Fight.id`` post-conditions (``min_length=1`` + the
   # invariant ``fight_id == input fight.id``) exercise the
   # realistic length without requiring a real blob.
   SYNTHETIC_FIGHT_ID: Final[str] = "deadbeef" * 8

   # Canonical "modern" arcdps build date used by every test
   # fixture. Centralised here so a future plan that adds
   # v0.5.0-fallback tests can pass ``build_version="20240115"``
   # explicitly without affecting the default.
   SYNTHETIC_BUILD_VERSION: Final[str] = "20250925"


   def synthetic_player(
       aid: int,
       *,
       account_name: str,
       name: str = "X",
       subgroup: str = "",
       profession: Profession = Profession.WARRIOR,
       elite: EliteSpec = EliteSpec.BERSERKER,
   ) -> Agent:
       """Build a player :class:`Agent` for in-place ``Fight`` construction.

       Defaults align with the ``test_multi_fight.py`` shape
       (most-used variant); the ``test_aggregate.py`` callers
       pass ``name``, ``subgroup``, ``profession``, ``elite``
       explicitly because their test fixtures require specific
       values that aren't captured by the defaults. Use either
       style -- the result is the same ``Agent``.
       """
       return Agent(
           id=aid,
           name=name,
           profession=profession,
           elite=elite,
           is_player=True,
           account_name=account_name,
           subgroup=subgroup,
       )


   def synthetic_npc(aid: int, name: str = "Mob") -> Agent:
       """Build an NPC :class:`Agent` for in-place ``Fight`` construction."""
       return Agent(id=aid, name=name, profession=Profession.UNKNOWN, is_player=False)


   def synthetic_fight(
       fight_id: str = SYNTHETIC_FIGHT_ID,
       *,
       agents: list[Agent] | None = None,
       skills: list[Skill] | None = None,
       encounter_id: int = 0,
       build_version: str = SYNTHETIC_BUILD_VERSION,
   ) -> Fight:
       """Build a fully-formed :class:`Fight` for an aggregator test.

       ``agents`` and ``skills`` default to ``None`` (empty
       list); ``fight_id`` defaults to the canonical sentinel;
       ``build_version`` defaults to the modern arcdps date.
       The resulting ``Fight`` has a fully-populated
       :class:`EvtcHeader` (mirrors the parser's
       V1.3-minimum-surface contract).
       """
       if agents is None:
           agents = []
       if skills is None:
           skills = []
       started_at = datetime(1970, 1, 1, tzinfo=UTC)
       return Fight(
           id=fight_id,
           agents=agents,
           skills=skills,
           started_at=started_at,
           game_type=GameType.WVW,
           header=EvtcHeader(
               build_version=build_version,
               encounter_id=encounter_id,
               agent_count=len(agents),
               skill_count=len(skills),
           ),
       )
   ```

2. `libs/gw2_analytics/tests/test_aggregate.py` — drop the 3 helpers + the `_FIXED_FIGHT_ID` constant; import from `_fixtures`:

   ```python
   from tests._fixtures import (
       SYNTHETIC_FIGHT_ID as _FIXED_FIGHT_ID,
       synthetic_player as _player,
       synthetic_npc as _npc,
       synthetic_fight as _fight,
   )
   ```

   The aliases preserve the existing call sites (`_player(...)`, `_npc(...)`, `_fight(...)`, `_FIXED_FIGHT_ID`) without forcing a bulk rename across the 12 existing tests in this file. Pure imports-only refactor; runtime behaviour byte-identical.

3. `libs/gw2_analytics/tests/test_multi_fight.py` — same swap:

   ```python
   from tests._fixtures import (
       synthetic_player as _player,
       synthetic_npc as _npc,
       synthetic_fight as _fight,
   )
   ```

   Note: test_multi_fight calls `_fight("fid-1", [...])` positionally — the canonical helper accepts `fight_id` as the first positional arg so the call sites remain compatible. Plus the `_player`'s default args align with the multi_fight style (no explicit name/profession/elite needed for most tests).

## Tests (4, NEW file `libs/gw2_analytics/tests/test__fixtures.py`)

- `test_synthetic_fight_id_has_sha256_hex_length` — `len(SYNTHETIC_FIGHT_ID) == 64`. Defensive: catches a future regression where the sentinel is shortened (which would shift the `min_length=1` invariant coverage).
- `test_synthetic_build_version_is_eight_chars` — `len(SYNTHETIC_BUILD_VERSION) == 8` and parses as `int(SYNTHETIC_BUILD_VERSION)` for date semantics.
- `test_synthetic_fight_empty_inputs_yields_a_valid_fight` — invoke `synthetic_fight()` with no args; assert the result is a valid ``Fight``: `fight.id == SYNTHETIC_FIGHT_ID`, `fight.header.encounter_id == 0`, `fight.header.build_version == SYNTHETIC_BUILD_VERSION`, `fight.agents == []`, `fight.skills == []`, `fight.game_type == GameType.WVW`.
- `test_synthetic_player_default_args_match_multi_fight_style` — invoke `synthetic_player(1, account_name=":a")` with no other args; assert `agent.name == "X"`, `agent.subgroup == ""`, `agent.profession == Profession.WARRIOR`, `agent.elite == EliteSpec.BERSERKER`. Confirms the multi_fight compatibility.

## Rejected alternatives

- **Inline the helpers directly into `aggregate.py` / `multi_fight.py` as module-level test fixtures** — coupling test helpers to production code is a code-smell; tests should consume a separate inventory. REJECTED.
- **Drop the `_player` / `_npc` / `_fight` aliases and rename every call site** — invasive (12-15 test call sites per file). The aliases preserve the call sites; the import block is the single change. REJECTED.
- **Use `pytest.fixture` decorators for the synthetic builders** — pytest fixtures are per-test (decorator-based); module-level helpers are cleaner for builder patterns (no fixture-loop overhead). The canonical pattern across the workspace is module-level factories (the ``_contrib(...)`` builder in `test_player_profile.py` is the precedent). REJECTED.
- **Hoist `_fixtures.py` to `libs/gw2_analytics/tests/conftest.py`** — `conftest.py` is for pytest fixtures (auto-discovered); a separate module is the conventional shape for builder helpers that aren't pytest-fixtures. REJECTED.
- **Add a `_aggregator` or `_marker` file naming convention** — the `_` prefix marks PRIVATE modules (the underscore-prefix is the canonical Python convention for "not part of the public package API"). `tests/_fixtures.py` is "internal to the tests package". REJECTED.

## Dependency graph

- Independent: NEW `tests/_fixtures.py` + 2 test files import the shared helpers. The 2 modified files are untouched at the runtime layer.
- Parallel-safe with plans 111 / 112.
- Recommended pattern alignment with the `libs/gw2_analytics/_per_target_base.py` (per plan 084 v0.9.27): the workspace pattern for "extract shared test surfaces" is a single NEW `_*` (private) module adjacent to the consumers.
- Other test files (test_squad_rollup, test_per_fight_timeline, test_target_dps, test_target_healing, test_target_buff_removal, test_event_window, test_skill_usage) can adopt the same shared factory in a follow-up audit pass; not blocking for this plan (each has its own domain-specific event builders per plan 111).
