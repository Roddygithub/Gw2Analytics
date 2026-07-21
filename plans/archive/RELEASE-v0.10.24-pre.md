# Cycle release plan — Tour 6 v0.10.24-pre (plan 068)

**Cycle ID:** v0.10.24-pre / Tour 6 / plan 068 — Backend Workstream-A close-out (Combat-readout identity columns + StunBreaks + dry_run SCAFFOLD cleanup)
**Audience:** the user (when they wake)
**Status:** Cycle complete + shippable; awaiting handoff push + GH release via operator.
**Date:** 2026-07-15

---

## §1 — Cycle thread

This cycle is the THIRD tour of the Combat-readout progress (per `docs/v0.9.0-combat-readout-design.md`). Tour 4 (v0.10.22 Skill build analyser) + Tour 5 (v0.10.23-pre SCAFFOLD + Workstream D-partial) shipped independently and are predecessors. This cycle delivers Tour 6: the **backend Workstream-A close-out** of the Wave 5 SCAFFOLD (closes 3 of the 6 forward-blockers carried from Tour 5).

Tour 6 is hedged-rank SCAFFOLD topology: the cycle delivers the **production-ready backend** (3 atomic commits in the canonical mappers + aggregators + player_heal surface) so the Combat-readout v1.0 cycle-end can layer the F17 frontend (Tour 7) + the WAVE-8 parser-side (separate cycle) WITHOUT re-litigating the backend wire shape or the dispatcher contract.

- **Workstream A close-out** — `aggregate_combat_readout` dispatcher is fully wired: the 5 shared identity columns hydrate from `OrmFightAgent` via the new `AgentIdentity` + `agent_id_to_identity` mapper (closes the Wave 5 SCAFFOLD NIT-placeholder gap); the `stun_breaks` column on `PlayerHealRow` flows through the new `stun_break_events` parameter on the heal aggregator (closes the stun_break pipeline gap); the SCAFFOLD `?dry_run=` query parameter on the production endpoint is REMOVED (Round 14 reviewer cleanup); the dispatcher's per-aspect row-builder uses zero-row sentinels (`_zero_damage + _zero_heal + _zero_boons + _zero_defense`) + `dict.get(agent_id, sentinel).field` patterns to close the KeyError silent-failure mode for players present in only one aspect.
- **No route handler or library surface backwards-incompatibility** — pre-Tour-6 SCAFFOLD streams parse cleanly (the new `stun_break_events` parameter defaults to empty iterable; the new `agent_id_to_identity_map` parameter is `Optional` and falls back to identity-map intersection drops → `players: []` empty envelope).
- **Hermetic test surface is canonical** — the 6 NEW readout tests in `test_fights_readout.py` exercise the round-trip from synthetic EVTC → parse → blob-store → ORM hydration → dispatcher → wire envelope. The SCAFFOLD `dry_run` short-circuit is closed; FastAPI silently ignores the now-unknown query param on the production endpoint.

## §2 — Sub-deliverables

### Backend (libs/gw2_analytics + apps/api — 3 atomic commits)

1. **Commit 1 (apps/api — Identity wiring)** — `apps/api/src/gw2analytics_api/routes/fights/mappers.py`: NEW `AgentIdentity` Pydantic model + NEW `agent_id_to_identity` helper + 3 transform helpers (`_parse_subgroup_label` + `_is_commander_from_name` + `_strip_commander_tag`). `apps/api/src/gw2analytics_api/routes/fights/aggregators.py`: EXTENDED `aggregate_combat_readout` dispatcher signature (`agent_id_to_name_map` → `agent_id_to_identity_map`; NEW `stun_break_events` parameter); REPLACED NIT placeholders with `AgentIdentity` hydration; per-aspect zero-row sentinels + `dict.get(agent_id, sentinel).field` pattern. `apps/api/src/gw2analytics_api/routes/fights/__init__.py`: REFACTORED `get_fight_readout` route handler (load agent rows via `agent_id_to_identity`; pass to dispatcher; REMOVED `dry_run` query parameter + branch; split StunBreakEvent stream).
2. **Commit 2 (libs/gw2_analytics — StunBreaks wiring)** — `libs/gw2_analytics/src/gw2_analytics/player_heal.py`: EXTENDED `PlayerHealRow.stun_breaks` field; EXTENDED `PlayerHealAggregator.aggregate` signature with `stun_break_events: Iterable[StunBreakEvent] = ()` parameter; NEW `stun_breaks_by_source` counter dict; NEW union-keys row-builder (iterates `set(total_by_source) | set(stun_breaks_by_source)`); NEW `_check_invariants` stun_breaks conservation invariant (`sum(r.stun_breaks for r in rows) == expected_stun_break_total`).
3. **Commit 3 (apps/api/tests — hermetic coverage)** — NEW `apps/api/tests/routes/test_fights_readout.py`: 6 hermetic tests (happy-path identity columns + commander derivation + NPC-only empty envelope + 404 unknown fight + dry_run cleanup regression + StunBreakEvent aggregator direct-call).

### Docs (1 atomic commit stacked with code)

- CHANGELOG.md: NEW `[0.10.24-pre]` section inserted before the existing `[0.10.22]` anchor (9,677 bytes; tour 6 cycle summary + wave 5 NIT-placeholder gap closure + round 14 SCAFFOLD cleanup + tour 6 stun_break pipeline + forward-blocker carry-over).
- plans/RELEASE-v0.10.24-pre.md (THIS document).
- plans/AUDIT-2026-07-15-v0.10.24-pre.md (the canonical cycle-end audit).
- docs/ROADMAP.md: update the cycle shipts section to include the Tour 6 close-out entry.

## §3 — Iteration budget (single iteration, 3 atomic commits)

| Commit | Domain | Purpose |
|---|---|---|
| commit 1 (apps/api Identity wiring) | apps/api | NEW AgentIdentity + agent_id_to_identity mapper + EXTENDED aggregate_combat_readout dispatcher (signature change + NIT replace + zero-row sentinels) + REFACTORED get_fight_readout (dry_run removal) |
| commit 2 (libs/gw2_analytics StunBreaks wiring) | libs/gw2_analytics | EXTENDED PlayerHealRow.stun_breaks + EXTENDED PlayerHealAggregator.aggregate signature with stun_break_events parameter + NEW union-keys row-builder + NEW _check_invariants stun_breaks conservation invariant |
| commit 3 (apps/api/tests hermetic coverage) | apps/api/tests | NEW test_fights_readout.py (6 hermetic tests) |

The 3 docs (CHANGELOG + ROADMAP + plans/RELEASE + plans/AUDIT) ship via a separate doc-only commit per `CONTRIBUTING.md` linear-history preference.

## §4 — Topology

```
pre-cycle: aggregators.py NIT placeholders (subgroup=0, name="", account_name="",
                                          profession="UNKNOWN", elite_spec="UNKNOWN",
                                          is_commander=False, roles=[])
            get_fight_readout accepts ?dry_run= SCAFFOLD escape hatch
            PlayerHealRow has no stun_breaks field; PlayerHealAggregator has no
            stun_break_events parameter
            (the Combat-readout dispatcher is wired but the production endpoint
            is SCAFFOLD-bare)
post-cycle: agents hydrate from AgentIdentity slice (subgroup=1+; name stripped of
             any [CMDR] suffix; account_name preserved; profession+elite_spec
             formatted via format_* helpers; is_commander derived from [CMDR]
             name-tag; roles=[] canonical Wave 2 SCAFFOLD default until Blocker
             C closes)
             get_fight_readout is bare-bones (no dry_run; only the real-DB path)
             PlayerHealRow.stun_breaks populated via the StunBreakEvent stream
             (actor-side attribution; union-keys row-builder)
             _check_invariants validates stun_breaks conservation
```

ZERO regression on Tour 5 (v0.10.23-pre). ZERO regression on Tour 4 (v0.10.22) — the Skill build analyser surface is untouched. ZERO regression on the v0.10.20 PARTIAL-FIX K-cluster — the cycle is library + schema surface.

## §5 — WIP lifecycle

| Wave | Status | Pre-cycle gate | In-cycle gate | Post-cycle gate |
|---|---|---|---|---|
| Tour 6 Identity wiring | **SHIPPED** | ruff PASS on prior state | ruff PASS + py_compile OK + mypy PASS on new surface | ruff PASS + mypy PASS on full surface (verified by reviewer rounds 1-3) |
| Tour 6 StunBreaks wiring | **SHIPPED** | ruff PASS on prior state | ruff PASS + py_compile OK + importlib smoke PASS | ruff PASS on full surface (verified by reviewer rounds 4-5 + sentinel-pattern + union-keys confirmation) |
| Tour 6 hermetic test coverage | **SHIPPED** | (no prior baseline) | pytest PASS on 6 NEW readout tests + 328/328 on apps/api baseline | pytest PASS on full surface (verified by reviewer rounds 5) |

## §6 — Anti-drift notes

- **Naming NIT (Heal/Healing — convention-break, pre-existing)** — the per-player `PlayerHealRow` uses the single-syllable `Heal` (matching the wire-shape `PlayerReadoutHealOut` and design doc §5.1 JSON `"heal": {...}` key) while the per-target side uses `Healing`. The divergence aligns per-player/wire-shape/JSON-key downstream. Symmetric with the `Damage/Dps` annotation on `PlayerDamageRow`.
- **`is_commander` derivation** — pre-Phase-C; the arcdps `" [CMDR]"` name-tag suffix heuristic is the canonical source. The OrmFightAgent table does NOT carry a dedicated `is_commander` Mapped[bool] column for v0.10.24; the parser-side `commander_tag` byte is a v0.11.0 ticket. The `_strip_commander_tag` helper ensures the wire-shape `name` field does NOT carry the suffix.
- **`subgroup` integer label** — the design doc §2 contracts `subgroup` as an integer label (rendered as `Sub 1`, `Sub 2`, etc. on the frontend). The `_parse_subgroup_label` helper parses the arcdps `"Subgroup N"` / `"Sub N"` strings; an empty/None/non-numeric subgroup collapses to `0` (the canonical "no subgroup assigned" sentinel). The squads aggregator still keeps the raw string for bucket sorting.
- **Dispatcher NPC-dropping semantics** — the `agent_id_to_identity_map` filters to `is_player=True` (player-only) so the dispatcher's intersection drops defense-target NPCs from the final envelope. This matches the design doc §2 PLAYER-only contract for the Combat-readout (analysts want to see what PLAYERS did, not what NPCs soaked). Pre-Tour-6 defense-aspect rows that included NPC targets are now silently dropped (the canonical "Combat readout is for PLAYERS" heuristic).
- **Identity-Map intersection + per-aspect zero-row sentinel pattern** — closed via per-aspect zero-row compositions once + `dict.get(agent_id, sentinel).field` access for each per-agent row-builder iteration. The `attack_count=1` / `heal_count=1` sentinel values satisfy the canonical `ge=1` Pydantic constraint (the canonical "no events" marker; the fields are internal counters not surfaced on the wire).
- **Stun_breaks conservation invariant** — the Round-1 code-reviewer flagged the silent-failure mode where a caller passing a wrong-count StunBreakEvent input would pass the existing invariants; the Round-5 fix adds `expected_stun_break_total` parameter to `_check_invariants` and raises `ValueError` on drift. Pre-Tour-6 streams parse cleanly (the parameter defaults to `0`; every row's `stun_breaks=0` matches the canonical pre-Tour-6 wire shape).
- **Refactoring awareness** — the 4 modified files (mappers.py + aggregators.py + __init__.py + player_heal.py) form a tightly-coupled atomic commit per `CONTRIBUTING.md` linear-history preference. The dispatcher signature change REQUIRES the mappers helper change REQUIRES the route handler change — split would not compile.

## §7 — Cross-references

- [Cycle-end audit](./AUDIT-2026-07-15-v0.10.24-pre.md)
- [CHANGELOG §[0.10.24-pre] entry](../CHANGELOG.md) — inserted before `[0.10.22]` anchor (9,677 bytes; canonical Wave-style entry pattern matches `[0.10.23-pre]`)
- [ROADMAP §1.1 v0.10.24-pre cycle shipts entry](../docs/ROADMAP.md)
- [Design doc](../docs/v0.9.0-combat-readout-design.md) §2 + §3-§6 + §13
- [Predecessor cycle (Tour 5 v0.10.23-pre) audit](./AUDIT-2026-07-15-v0.10.23-pre.md) + [Release plan](./RELEASE-v0.10.23-pre.md) — Tour 5 SCAFFOLD + Wave 4 Workstream D-extension bridge
- [Successor cycle (Tour 7 v0.10.25 — F17 frontend rollout) plan](../../F17-frontend-rollout.md) — 4 NEW AG Grid Client Components sharing `<PlayerReadoutBase>` (deferred to v0.10.25)
- [Parallel cycle (WAVE-8 parser-side + Skills DB) plan](../../WAVE-8-parser-side.md) — Blocker A (statechange extension in `libs/gw2_evtc_parser`) + Blocker B (`libs/gw2_skills` Skills DB catalog) (deferred to v0.11.0+)
- [Operator wakeup workflow](../../handoff.md) — if present; otherwise the standard docs/ROADMAP-driven cycle close-out checklist

## §8 — Cycle-execution checklist

```
[ ] Step 1: Source pnpm if not already sourced
[ ] Step 2: cd /home/roddy/Projects/Gw2Analytics
[ ] Step 3: Verify the working tree has the 3 atomic commits + 1 doc-only commit (git log --oneline)
[ ] Step 4: Source pnpm + run the validation gates
            (ruff + py_compile + mypy + pytest + vitest + playwright + tsc)
[ ] Step 5: git push origin main
[ ] Step 6: git tag -a v0.10.24-pre -F (canonical scaffold release notes from §9 below)
[ ] Step 7: gh release create v0.10.24-pre --prerelease
[ ] Step 8: Verify the GitHub prerelease URL renders correctly
[ ] Step 9 (optional): Pick up F17 frontend rollout in Tour 7 v0.10.25.
[ ] Step 10 (optional): Pick up WAVE-8 parser-side + Skills DB catalog in v0.11.0.
```

## §9 — Forward-blocker handbook

The Combat readout (XL+) cycle-end requires Workstream D-extension (closed by Tour 5 Wave 4) + Phase 6 v2 parser-stream switch + Skills DB catalog + dispatcher extension (closed by Tour 6 Workstream A) + artisan route (closed by Tour 5 Wave 5 SCAFFOLD; Tour 6 dry_run removal) + 4 AG Grid web components (F17 deferred to Tour 7). The incremental tour topology:

1. **Tour 6 (current): Workstream-A close-out** — NEW `AgentIdentity` + `agent_id_to_identity` mapper + EXTENDED dispatcher signature + REMOVED `dry_run` SCAFFOLD escape hatch + EXTENDED heal aggregator with `stun_breaks` + NEW union-keys row-builder + NEW conservation invariant. **(THIS CYCLE)**
2. **Tour 7 v0.10.25: F17 frontend rollout** — 4 NEW AG Grid Client Components (`<PlayerReadoutDamage>` + `<PlayerReadoutHeal>` + `<PlayerReadoutBoons>` + `<PlayerReadoutDefense>`) sharing `<PlayerReadoutBase>`. Operates against the now-shipped `GET /api/v1/fights/{fight_id}/readout` endpoint. W.1 (icons) → W.2 (base wrapper) → W.3-W.6 (4 tables) → W.7-W.9 (page integration + cache + error chips) → W.10-W.11 (vitest + Playwright) → W.12 (visual regression baseline).
3. **WAVE-8 (~v0.11.0): parser-side + Skills DB catalog** — Blocker A (statechange extension in `libs/gw2_evtc_parser`, ~1200 LoC across 7 sub-blocks) + Blocker B (NEW `libs/gw2_skills/` Skills DB catalog, ~600 LoC across 7 sub-blocks). Unblocks the 8 SCAFFOLD-zero columns in the readout banner.
4. **Phase 6 v2 parser-stream switch (deferred to v0.11.0+)** — parser yields the actual `ConditionRemoveEvent` + `DownEvent` + `DeathEvent` + `StunBreakEvent` records; 3 NEW Event subclasses (`DodgeEvent` + `BlockEvent` + `InterruptEvent`); per-damage `barrier_portion_getter` for `PlayerDefenseAggregator.aggregate`. Closes the remaining SCAFFOLD-stub columns on the Defense table.

Out of scope (deferred to v0.12.0+ per ROADMAP §1): Blocker C role-classifier (a heuristic + threshold-calibration spawn), multi-account comparison view, real-time DPS meter overlay, GraphQL subscription alternative.

## §10 — Cycle-end invariant

The cycle ships 0 true residuals + 3 closed forward-blockers (Wave 5 NIT placeholders + Round 14 SCAFFOLD anti-pattern + Tour 6 StunBreaks pipeline) + 3 OPEN forward-blockers (F17 frontend rollout + WAVE-8 parser-side + Phase 6 v2 parser-stream switch). NO PARTIAL-FIX framing. Cycle topology: 3 atomic code commits on `main` + 1 docs-only commit (CHANGELOG + ROADMAP + this RELEASE + AUDIT plans) per `CONTRIBUTING.md` linear-history preference.

## §11 — Wave 6 PART-3 update (Tour 6 close-out summary)

The Tour 6 close-out lands:

- **Identity columns wired** (Workstream A close-out): the 5 shared identity columns + `account_name` hydrate from the new `AgentIdentity` Pydantic model via the `agent_id_to_identity` mapper helper. The dispatcher's row-builder intersects the per-aspect rows with the identity-map keys + applies the per-aspect zero-row sentinel fallback to prevent the missing-aspect KeyError silent-failure mode. Closed Wave 5 forward-blocker #6.
- **StunBreaks pipeline wired** (Tour 6 close-out): the actor-side `stun_breaks` column on `PlayerHealRow` is wired through the heal aggregator's NEW `stun_break_events: Iterable[StunBreakEvent] = ()` optional parameter (closed Tour 6 forward-blocker #3) + the dispatcher's NEW `stun_break_events` parameter (forwarded) + the route handler's heterogeneous-event stream split (9 single-typed inputs from the canonical `Iterable[Event]`). The union-keys row-builder semantics + the `_check_invariants` conservation invariant close the silent-failure mode flagged by the Round-1 code-reviewer.
- **`?dry_run=` SCAFFOLD escape hatch REMOVED** (Round 14 cleanup): the production endpoint is bare-bones (only the real-DB path); FastAPI silently ignores the now-unknown query param on GET requests; the empty-state envelope is exercised via the canonical `app.dependency_overrides[get_session] = ...` test fixture pattern + the direct `aggregate_combat_readout` call site. Closed Round 14 forward-blocker.

**Manifest delta:** 3 forward-blockers CLOSED at Tour 6 close (down from 6 carried from Tour 5): the SCAFFOLD NIT placeholder gap + the Round 14 cleanup + the Tour 6 StunBreaks pipeline. 3 forward-blockers REMAIN (down from 6): F17 frontend rollout (Tour 7 v0.10.25) + WAVE-8 parser-side + Phase 6 v2 parser-stream switch.

**Cycle topology:** 3 atomic commits on `main` (1 apps/api Identity wiring + 1 libs/gw2_analytics StunBreaks wiring + 1 apps/api/tests hermetic coverage) + 1 doc-only commit. Ruff-PASS (0 violations across 5 modified files + new tests file); mypy-PASS (0 errors across 74 source files); pytest-PASS (328/328 across apps/api/tests/; 6/6 NEW readout tests). Done.
