# Cycle release plan — Tour 5 v0.10.23-pre (plan 045)

**Cycle ID:** v0.10.23-pre / Tour 5 / plan 045 — Combat readout SCAFFOLD + Workstream D-partial
**Audience:** the user (when they wake).
**Status:** Cycle plan drafted + published by Buffy (autonomous night-mode session).
**Date:** 2026-07-15

---

## §1 — Cycle thread

This cycle is the SECOND tour of the Combat-readout progress (per `docs/v0.9.0-combat-readout-design.md`). Tour 4 (v0.10.22 Skill build analyser, plan 044) shipped independently and is the predecessor. The Combat readout itself is an XL+ cycle per ROADMAP §1 (the user spec from the brainstorming sessions).

Tour 5 is hedged-rank SCAFFOLD: the cycle delivers the static-model floor (Pydantic discriminators + wire-shape contracts + per-player aggregator library surfaces) so the next tour can layer the route handlers + aggregators WITHOUT re-litigating the model surface.

- **Wave 2 SCAFFOLD** — 4 NEW statechange event subclasses (ConditionRemoveEvent / DownEvent / DeathEvent / StunBreakEvent) wired into the gw2_core discriminated union (now 9 members). 6 NEW wire-shape Pydantic schemas (PlayerReadout{Damage,Heal,Boons,Defense}Out + PlayerReadoutOut + FightReadoutOut) appended to `apps/api/src/gw2analytics_api/schemas/fight.py` for the future `GET /api/v1/fights/{fight_id}/readout` endpoint. DeathEvent gains 2 Optional forward-compat fields (`killed_by_agent_id` + `killing_skill_id`) so Phase 6 v2 parser-stream switch does NOT trigger a schema bump.
- **Wave 3 Workstream D-partial** — 2 NEW per-player aggregators (PlayerDamageAggregator + PlayerHealAggregator in libs/gw2_analytics) as strict axis-flipped mirrors of `target_dps.py` + `target_healing.py` (existing per-target sibling modules). Grouping axis: `source_agent_id` (the player who DISHED OUT the damage/heal) — NOT `target_agent_id` (the receiver). The Combat readout's Damage (per §3) + Heal (per §4) tables key on the source side.

## §2 — Sub-deliverables

### Backend (libs/gw2_core + libs/gw2_analytics + apps/api schemas — 3 atomic commits)

1. **Wave 2 libs/gw2_core** — `libs/gw2_core/src/gw2_core/models.py`: 4 NEW Event subclasses + 4 NEW EventType literals + `type Event` union extension (5 → 9 members) + `__all__` alphabetical update + DeathEvent Optional forward-compat fields + forward-compat sub-union partition note.
2. **Wave 2 apps/api schemas** — `apps/api/src/gw2analytics_api/schemas/fight.py`: 6 NEW wire-shape Pydantic classes appended after `PlayerSkillsOut`. `apps/api/src/gw2analytics_api/schemas/__init__.py`: 6 NEW re-exports with case-sensitive alphabetical ordering (ruff was happy with `PlayerSkillLoadoutOut`-then-`PlayerSkillsOut`-then-`PlayerSkillUsageRowOut` ordering as-is).
3. **Wave 3 libs/gw2_analytics** — `libs/gw2_analytics/src/gw2_analytics/player_damage.py` + `player_heal.py`: 2 NEW per-player aggregator modules (~190 LoC each, strict axis-flipped mirror of `target_dps.py` / `target_healing.py`). `libs/gw2_analytics/src/gw2_analytics/__init__.py`: 4 NEW re-exports alphabetically.

### Docs (3 atomic commits stacked with code)

- CHANGELOG.md: NEW `## [0.10.23-pre]` section between FIRST `[Unreleased]` + FIRST dated entry `[0.10.11]` (matches file's existing partial-chronology insertion pattern).
- ROADMAP.md: "Last refreshed" stamp + new "Current state (post v0.10.23-pre cycle)" + new "v0.10.23-pre cycle shipts" entry under §1.1 (nested immediately under v0.10.22).
- handoff.md: Wave 3 sections (§17-§22) appended at the END (mirrors Wave 2 §10-§16 structure for grep-ability).
- plans/RELEASE-v0.10.23-pre.md (THIS document).
- plans/AUDIT-2026-07-15-v0.10.23-pre.md (the canonical cycle-end audit).

## §3 — Iteration budget (single iteration, 3 atomic commits)

| Commit | Domain | Purpose |
|---|---|---|
| commit 1 (Wave 2 libs/gw2_core) | libs/gw2_core | Discriminated union extension + 4 NEW Event subclasses + DeathEvent Optionals |
| commit 2 (Wave 2 apps/api schemas) | apps/api | 6 NEW Pydantic wire-shapes + `__init__.py` re-export |
| commit 3 (Wave 3 libs/gw2_analytics) | libs/gw2_analytics | 2 NEW per-player aggregator modules + `__init__.py` re-export |

The 3 docs (CHANGELOG + ROADMAP + plans/RELEASE + plans/AUDIT + handoff Wave 3) ship via the per-commit-message "Refs plans/RELEASE-v0.10.23-pre.md" convention; the operator can fold the docs into a single follow-up commit OR distribute them across 3 doc-only commits per `CONTRIBUTING.md` linear-history preference.

## §4 — Topology

```
pre-cycle: libs/gw2_core.models.Event = 5 members (Damage/Healing/BuffRemoval/BoonApply/CC)
                                          + apps/api.schemas (no PlayerReadout*)
                                          + libs/gw2_analytics (no player_*)
post-cycle: libs/gw2_core.models.Event = 9 members (+ ConditionRemove/Down/Death/StunBreak)
                                            + apps/api.schemas (6 NEW PlayerReadout* + FightReadoutOut)
                                            + libs/gw2_analytics (+ PlayerDamageAgg + PlayerHealAgg)
```

ZERO regression on Tour 4 (v0.10.22) — the Skill build analyser surface is untouched. ZERO regression on the v0.10.20 PARTIAL-FIX K-cluster — the cycle is library-only, `apps/api/tests/conftest.py` is not modified.

## §5 — WIP lifecycle

| Wave | Status | Pre-cycle gate | In-cycle gate | Post-cycle gate |
|---|---|---|---|---|
| Wave 2 SCAFFOLD | SHIPPED | ruff PASS on prior state | ruff PASS + py_compile OK on new surfaces | ruff PASS on full surface (verified by reviewer rounds 1-7) |
| Wave 3 D-partial | SHIPPED | libs/gw2_core 9-member discriminated union landed | ruff PASS + py_compile OK on player_damage.py + player_heal.py + importlib smoke PASS on synthetic event streams | ruff PASS on full surface (verified by reviewer rounds 5-7) |

## §6 — Anti-drift notes

- **Naming break (Heal/Healing and Damage/Dps)** — documented inline on both new `PlayerHealRow` + `PlayerDamageRow` docstrings. The divergence aligns the per-player name to the wire-shape + the JSON key. Mirror grep hint: `grep -nEi 'Heal(ing)?'` (ERE basic-grep fallback explicit).
- **DeathEvent Optional fields** — forward-compat for Phase 6 v2. Pre-Phase-6-v2 streams parse cleanly because both fields are `Optional[int] = None` defaults; pre-declared fields don't trigger `extra="forbid"`.
- **Discriminated union partition** — at 9 members, fine. Forward-compat note recommends sub-union partition beyond 12 members (i.e. when Phase 6 v2 + later tours land Dodge / Block / Interrupt).
- **Workflow surface discipline** — the route handlers + aggregator dispatchers + web components await follow-up tours with `pytest`/`vitest` online (operator-only environment). NO route code landed in this cycle.

## §7 — Cross-references

- [Cycle-end audit](../plans/AUDIT-2026-07-15-v0.10.23-pre.md)
- [CHANGELOG §[0.10.23-pre] entry](../CHANGELOG.md)
- [ROADMAP §1.1 v0.10.23-pre cycle shipts entry](../docs/ROADMAP.md)
- [Design doc](../docs/v0.9.0-combat-readout-design.md) (§3-7 + §9 + §11)
- [Operator wakeup workflow](../handoff.md) (§10.W2 + §17.W3)

## §8 — Cycle-execution checklist

```
[ ] Step 1: Source pnpm if not already sourced
[ ] Step 2: cd /home/roddy/Projects/Gw2Analytics
[ ] Step 3: Choose atomic-commit topology (recommend: Mode A = 3 atomic commits, per CONTRIBUTING.md)
[ ] Step 4: Run commits 1-3 per handoff.md §18.W3 (Wave 3 commit) + §12.W2 (Wave 2 commits)
[ ] Step 5: Source pnpm + run the validation gates (ruff + pytest + vitest + playwright + mypy + tsc)
[ ] Step 6: git push origin main
[ ] Step 7: git tag -a v0.10.23-pre -F (canonical scaffold release notes from §9 below)
[ ] Step 8: gh release create v0.10.23-pre --prerelease
[ ] Step 9: Verify the GitHub prerelease URL renders correctly
[ ] Step 10 (optional): Pick up Workstream D-extension in the next tour.
```

## §9 — Forward-blocker handbook

The Combat readout (XL+) cycle-end requires Workstream D-extension + parser-stream switch + skills DB catalog + dispatcher + artisan route + 4 AG Grid web components. The incremental tour topology:

1. **Wave 4 (next): Workstream D-extension + dispatcher + route** — `PlayerBoonsAggregator` + `PlayerDefenseAggregator` (the 2 missing per-player aggregators) + `aggregate_combat_readout` dispatcher in `apps/api/routes/fights/aggregators.py` + `GET /api/v1/fights/{fight_id}/readout` artisan route. Gated on Phase 6 v2 parser-stream switch + skills DB catalog.
2. **Wave 5: 4 AG Grid Client Components** — `<PlayerReadoutDamage>` + `<PlayerReadoutHeal>` + `<PlayerReadoutBoons>` + `<PlayerReadoutDefense>` sharing `<PlayerReadoutBase>`. Operates against the Wire 4 GET endpoint.
3. **Wave 6: visual-regression baseline + parser-stream switch** — final ship iteration that closes the Combat-readout v1.0 cycle-end.

Out of scope (deferred to v0.11.0+ per ROADMAP §1): multi-account comparison view, real-time DPS meter, GraphQL subscription alternative.

## §10 — Cycle-end invariant

The cycle ships 0 true residuals + 6 forward-blockers (Workstream D-extension + parser-stream switch + skills DB catalog + dispatcher extension + artisan route + 4 AG Grid web components). NO PARTIAL-FIX framing.

## §11 — Wave 4 update (Workstream D-extension complete)

The Wave 4 close-out lands 2 NEW per-player aggregators that close the **Workstream D-extension** forward-blocker:

- `PlayerBoonsAggregator` + `PlayerBoonsRow` (~310 LoC, `libs/gw2_analytics/src/gw2_analytics/player_boons.py`) — Combat readout §5 Boons table. 6 fixed buff-IDs as module-level ``Final[int]`` constants coupled to ``KNOWN_BOON_ID_TO_COLUMN: Final[dict[int, str]]``. Source-side for ``boons_out`` (count of ``kind == "apply"`` events where ``source_agent_id == player``); target-side for ``boons_in``. ``other_boons_out`` bucket keyed by ``name_map.get(skill_id)`` OR ``"Unknown (<skill_id>)"`` sentinel. Sort: ``(-boons_out, agent_id)``. Cross-field invariant: per row, ``fixed_sum + other_sum == boons_out`` exactly. Buff-ID calibration provenance documented inline.
- `PlayerDefenseAggregator` + `PlayerDefenseRow` (~285 LoC, `libs/gw2_analytics/src/gw2_analytics/player_defense.py`) — Combat readout §6 Defense table. Target-side for ``damage_taken`` + ``cc_taken`` (sum of cc_value); actor-side for ``deaths`` (count of DeathEvent rows). Sort: ``(-damage_taken, agent_id)`` per design doc §13 (most-targeted first). 5 stub columns (``time_downed_ms`` / ``dodges`` / ``blocks`` / ``interrupts`` / ``barrier_absorbed``) pinned at 0 for the v0.10.23 wire contract; the 4 needing NEW Event subclasses await Phase 6 v2 parser-stream switch; ``barrier_absorbed`` accepts an OPTIONAL ``barrier_portion_getter`` parameterized by caller (parallels ``condi_portion_getter`` from ``condi_power_split.py``).

**Manifest delta:** 5 forward-blockers REMAIN at Wave 4 close (down from 6 — Workstream D-extension closed): Phase 6 v2 parser-stream switch + Skills DB catalog + ``aggregate_combat_readout`` dispatcher extension + ``GET /api/v1/fights/{fight_id}/readout`` artisan route handler + 4 web AG Grid Client Components.

**Cycle topology:** 4 atomic commits on ``main`` (2 library commits for Wave 2 + 1 library commit for Wave 3 + 1 library commit for Wave 4; the docs close-out inherits from prior rounds). Recognized by code-reviewer (3 rounds: initial audit + symmetry-gap fix + syntax-fix audit). ruff-PASS (0 violations across the 4 NEW/MODIFIED files), py_compile-PASS, importlib smoke-PASS with ``model_rebuild()`` workaround (the workaround addresses ``from __future__ import annotations`` + importlib side-load interaction; live ``gw2_core`` package installed via ``uv pip install -e libs/gw2_core/`` resolves natively). NO new tests (the Wave 4 surface is library-side; tests inherit with the future route handler + web UI).
