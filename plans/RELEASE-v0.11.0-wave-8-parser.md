# Cycle release plan — WAVE-8 v0.11.0 (parser-side + Skills DB catalog)

> **Companion docs:**
> - [WAVE-8 plan](./WAVE-8-parser-side.md) — the 8 §2 Blocker A sub-blocks + 7 §3 Blocker B sub-blocks + cycle topology
> - [Cycle release plan — Tour 6 v0.10.24-pre](./RELEASE-v0.10.24-pre.md) — predecessor cycle (pre-Tour 7)
> - [WAVE-8 unblock note — Tour 6 v0.10.24-pre](./WAVE-8-parser-side.md) — see the v0.10.24-pre unblock block at the top of the WAVE-8 plan
> - [Spike — v0.10.19 combat readout](../docs/v0.10.19-combat-readout-spike.md) — A.1-A.7 + B.1-B.7 sub-blocks source-of-truth
> - [Design doc — v0.9.0 combat readout](../docs/v0.9.0-combat-readout-design.md) §3-§6 — table column contracts

> **Status:** Plan (post-Tour 6 v0.10.24-pre wire-contract stabilisation + post-StunBreakEvent partial Blocker A.3 shipping; pre cycle authorisation).
> **Branch target:** a fresh `feat/wave-8-parser-side` branch on cycle authorisation.
> **Shippable in:** v0.11.0 cycle (2-cycle scope per WAVE-8 §4 sequencing; the cycle authorisation may stack into one cycle if budget allows).

## §1 Cycle thread

WAVE-8 ships the parser-stream extension (Blocker A) + the `libs/gw2_skills` Skills DB catalog (Blocker B) that the F17 frontend rollout (Tour 7 v0.10.25) needs to unlock the 8 SCAFFOLD-zero columns in the readout banner. Per the WAVE-8 §1 column-to-blocker mapping:

| Column | Frontend cell | Unblocked by |
|---|---|---|
| `damage.dps_power` | PlayerReadoutDamage.tsx DPS power cell | Blocker A.4 + Blocker B.5 |
| `damage.dps_condi` | PlayerReadoutDamage.tsx DPS condi cell | Blocker A.4 + Blocker B.5 |
| `heal.barrier_total` | PlayerReadoutHeal.tsx Barrier total cell | Blocker A.4 (parser emits `BarrierEvent`) |
| `heal.barrier_ps` | PlayerReadoutHeal.tsx Barrier/s cell | Blocker A.4 + new barrier-rate aggregator |
| `defense.time_downed_ms` | PlayerReadoutDefense.tsx Time on ground cell | Blocker A.4 (parser emits `DownEvent` with `downtime_ms`) |
| `defense.dodges` | PlayerReadoutDefense.tsx Dodges cell | Blocker A.4 (`StateChangeCount(dodge)`) |
| `defense.blocks` | PlayerReadoutDefense.tsx Blocks cell | Blocker A.4 (`StateChangeCount(block)`) |
| `defense.interrupts` | PlayerReadoutDefense.tsx Interrupts cell | Blocker A.4 (`StateChangeCount(interrupt)`) |

When all 8 are UNLOCKED (5 from Blocker A + 2 from Blocker B), the cycle completes per the WAVE-8 §7 done criterion — the readout banner mutates from the long "SCAFFOLD-zero" footnote to the canonical "Combat readout loaded · N players · duration X.X s." state.

### Carry-over from Tour 6 (per the WAVE-8 v0.10.24-pre unblock note)

Blocker A.3 (the 9 NEW Event subclasses) is now ~11% complete — 1 of 9 (`StunBreakEvent`) shipped end-to-end through Tour 6. The remaining 8 subclasses land in this cycle:

```
NEW libs/gw2_core/src/gw2_core/Event subclasses for v0.11.0:
- BarrierEvent (already partially hydrated via the Phase 6 v2 SCAFFOLD getter)
- ConditionRemoveEvent (cures)
- CCEvent (crowd control applied)
- DownEvent (target enters down state)
- DeathEvent (target dies)
- DodgeEvent (actor dodges)
- BlockEvent (actor blocks)
- InterruptEvent (actor interrupts)
```

Plus `StunBreakEvent` (already shipped — Tour 6 close-out). After Blocker A.3 ships, the parser-statechange decode loop (Blocker A.4) emits the matching subclass for each `cbtevent` statechange kind byte.

## §2 Cycle-execution checklist (operator handoff)

```
[ ] Step 1: Cycle authorisation (operator signs off the budget for v0.11.0)
[ ] Step 2: git checkout -b feat/wave-8-parser-side (fresh branch from main post-5725423)
[ ] Step 3: A.1 — audit arcdps' ~150 statechange kinds reference Elite Insights C# StateChange
            enum. The tour 6 partial-mapping covers ~30% (the BoonApplyEvent REMOVE+APPLY
            channel). The A.1 audit produces the explicit kind→subclass map.
[ ] Step 4: A.2 — finalize the kind→subset mapping for the 8 remaining subclasses
[ ] Step 5: A.3 — add 8 new EventType enum entries + 8 new Pydantic subclasses
            in libs/gw2_core/src/gw2_core/models.py:
            BarrierEvent + ConditionRemoveEvent + CCEvent + DownEvent
            + DeathEvent + DodgeEvent + BlockEvent + InterruptEvent
            (+ verify StunBreakEvent is already in the enum from Tour 6)
[ ] Step 6: A.4 — extend the parser's cbtevent decode loop to read the statechange kind
            byte (currently SKIPPED at libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py:439)
            and emit the matching subclass. The discriminator contract is forward-compat
            (A.7 of the WAVE-8 plan §6 documents the JSONL fallback).
[ ] Step 7: A.5 — 8 hermetic parse_events predicate-boundary tests
            in libs/gw2_evtc_parser/tests/test_parser_emit_statechange.py
            (one per new subclass).
[ ] Step 8: A.6 — real-fixture integration test (extend the F1 calibration pilot).
[ ] Step 9: B.1 — decide the Skills DB source (official GW2 API vs community dataset).
            The decision criteria are maintenance + staleness tolerance per spike §B.1.
[ ] Step 10: B.2 — build libs/gw2_skills/ with SkillMetadata Pydantic class
             (id + name + type: power|condi|hybrid + icon_url + categorisation).
[ ] Step 11: B.3 — bootstrap catalog: one-time script + versioned JSON dataset
             under libs/gw2_skills/src/gw2_skills/data/.
[ ] Step 12: B.4 — cargo-cult into apps/api startup via functools.lru_cache(maxsize=1)
             keyed on the catalog hash. apps/api /healthz exposes the loaded hash +
             a "freshness-days" gauge per Blocker B mitigations.
[ ] Step 13: B.5 — expose gw2_skills.lookup_skill(id) with SkillNotFoundError
             for unknown IDs (defensive against arcdps player builds not in catalog).
[ ] Step 14: B.6 — ship libs/gw2_skills as a workspace member +
             add to pyproject.toml +
             verify cross-library typechecks (gw2_core, gw2_evtc_parser, gw2_analytics, apps/api).
[ ] Step 15: B.7 — 5+ hermetic tests for the catalog fixture (canonical 500-skill subset).
[ ] Step 16: A.7 — update docs/v0.10.11-phase-9-conditions.md + docs/ROADMAP.md §1.1
             cycle shipts (Phase 9 step 4-STEPS).
[ ] Step 17: F17 §5 fan-out (the per-column 3-edit pattern) —
             8 small commits (1 per unlocked column) that prune the SCAFFOLD-zero entries
             in web/src/app/fights/[id]/page.tsx +
             flip valueGetter from () => 0 to (params) => params.data.<path> +
             add Playwright specs.
[ ] Step 18: Ruff + mypy + pytest + vitest + tsc + Playwright all green
[ ] Step 19: git push origin feat/wave-8-parser-side
[ ] Step 20: gh release create v0.11.0 (NOT pre-release — full stable)
            after cycle close-out / merge to main
[ ] Step 21: Update ROADMAP Status to v0.11.0 + remove the v0.10.25 Status line
```

## §3 Topology

```
pre-cycle: feat/wave-8-parser-side branch from main post-5725423
           Parser skip-filter at libs/gw2_evtc_parser/parser.py:439 active (statechange
           kind byte is dropped before REMOVE/APPLY predicates run)
           8 SCAFFOLD-zero columns remain at the SCAFFOLD-zero wire value:
             damage.dps_power + damage.dps_condi (awaiting Blocker A.4 + Blocker B.5)
             heal.barrier_total + heal.barrier_ps (awaiting Blocker A.4)
             defense.time_downed_ms + defense.dodges + defense.blocks
             + defense.interrupts (awaiting Blocker A.4)
post-cycle: Parser skip-filter closed over; the cbtevent decode loop emits
            BarrierEvent + ConditionRemoveEvent + CCEvent + DownEvent + DeathEvent
            + DodgeEvent + BlockEvent + InterruptEvent per the matching statechange
            kind byte.
            Skills DB catalog ships in libs/gw2_skills/ with the canonical 500-skill
            fixture subset bootstrapped.
            All 8 SCAFFOLD-zero columns surface live values in the readout banner.
            The banner mutates to "Combat readout loaded · N players · duration X.X s."
```

ZERO regression on Tour 7 (v0.10.25). ZERO regression on Tour 6 (v0.10.24-pre). ZERO regression on Tour 5 (v0.10.23-pre). ZERO regression on Tour 4 (v0.10.22).

## §4 Risks + mitigations

1. **Skills DB source staleness** (Bl B) — the GW2 API adds new skills per balance patch; the bootstrap script needs a quarterly re-run. *Mitigation:* cache the catalog hash at startup (B.4); apps/api /healthz exposes the loaded hash + a "freshness-days" gauge so stale catalogs surface visibly to the analyst. The Phase 9 §6 risk handbook v1.1.0 documents the maintenance cadence.
2. **Statechange kind unmapped** (Bl A) — uncovered arcdps statechange kinds would silently drop. *Mitigation:* A.2 produces the explicit map; the parser emits `event_type: "unknown_statechange"` as the catch-all so coverage gaps are detectable in the F1 calibration pilot.
3. **Discriminator fallout** (Bl A) — adding 8 new Event subclasses must NOT break the existing JSONL readers' discriminator dispatch. *Mitigation:* A.5 uses the existing `Field(discriminator="event_type")` contract; the spike doc §8 confirms forward-compat for the JSONL write path. The characterise-A.4-discriminator test (WAVE-8 §6 risk #3) is the canonical de-risk probe.
4. **DPS power/condi split semantics** (Bl B) — for hybrid skills (e.g. Soul Reaper on Necromancer), per-event may yield different splits than per-roll-up. *Mitigation:* B.2 + B.5 lock the semantics at the catalog level (`damage_type ∈ {power, condi, hybrid}`); the per-roll-up attribute follows the catalog value, not the per-event split.
5. **time on ground semantics** (cross-ref design §11 Q4) — locked default is `time_downed_ms = sum(time_in_down_state)`. The display cell needs the same units as Heal barrier/s (per ms-derived rate). *Mitigation:* confirmation in A.5 hermetic test that DownEvent emits `downtime_ms` consistent with the ms-derived rate contract.

## §5 Done criteria (closed when ALL of)

- All 8 SCAFFOLD-zero columns in the `readout-tab-status` banner have been removed (replaced by their unlocked aggregated values)
- The F17 frontend ships the 4 tables with NO SCAFFOLD-zero cell anywhere
- The banner paragraph mutates to the canonical short form: "Combat readout loaded · N players · duration X.X s."
- The F17 §5 fan-out commits (17 per-column commits) all green
- libs/gw2_skills is a workspace member; gw2_skills.lookup_skill(id) returns a `SkillMetadata` for all canonical 500 skills
- pytest 350+/350+ (was 327 + ~25-50 NEW hermetic + real-fixture integration tests for WAVE-8)

The Combat-readout reaches **v0.11.0 cycle-end as the canonical "what did each player do in this fight" surface for analysts, per design doc §0**. Out-of-scope (deferred to v0.12.0+): Blocker C role-classifier (a heuristic + threshold-calibration spawn), multi-account comparison view, real-time DPS meter overlay, GraphQL subscription alternative.

## §6 Counterpart documents (TODO, complementary to THIS plan)

- [Tour 7 v0.10.25 release plan](./RELEASE-v0.10.25-tour-7-frontend.md) — the F17 frontend release plan
- [F17 plan](./F17-frontend-rollout.md) — the F17 frontend plan
- [Tour 6 v0.10.24-pre followup audit](./AUDIT-2026-07-15-v0.10.24-pre-followup.md) — wire-contract widening history
- [BLOCKER-C role classifier plan](./BLOCKER-C-role-classifier.md) — the role-classifier follow-up after Blocker C is unblocked by WAVE-8

*Owner sign-off required before cycle authorisation:* (the WAVE-8 cycle assignee, separate role from this plan's author).
