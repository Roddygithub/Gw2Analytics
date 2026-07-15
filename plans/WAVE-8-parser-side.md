# WAVE-8 SCAFFOLD-zero unlock plan (parser-side + skills DB)

> **Companion docs:**
> - **Spike:** [`docs/v0.10.19-combat-readout-spike.md`](../docs/v0.10.19-combat-readout-spike.md) — XL+ scope, 8 sub-blocks for Blocker A (A.1-A.7) + 7 sub-blocks for Blocker B (B.1-B.7) + cycle topology (v0.10.21 / v0.10.22 / v0.10.23).
> - **Design:** [`docs/v0.9.0-combat-readout-design.md`](../docs/v0.9.0-combat-readout-design.md) — the 4 readout tables (`PlayerReadout{Damage,Heal,Boons,Defense}`) + 5 shared columns + 10 §3.1 role vocabulary.

> **Privacy caveat (companion promote commit):** this plan was authored alongside a separate commit that promotes `docs/v0.10.22-night-mode.md` from a gitignored root artefact into a tracked project asset. If the operator-private material in that file is sensitive, BOTH commits must be reverted: `git revert HEAD --no-edit && git revert HEAD~1 --no-edit && git push --force-with-lease origin feat/integrate-zevtc-fixture` (assumes the promote is the second-newest commit on the branch).

> **Status:** Plan (post-v0.10.19 spike; post Tour 6 v0.10.24-pre StunBreaks landing; pre v0.11.0 cycle authorisation).
> **Branch target:** a fresh `feat/wave-8-parser-side` branch on cycle authorisation.

> **Tour 6 v0.10.24-pre unblock event (2026-07-15):** the `GET /api/v1/fights/{fight_id}/readout` endpoint is now wired end-to-end with the new `AgentIdentity` mapper + the `stun_break_events: Iterable[StunBreakEvent] = ()` parameter on `PlayerHealAggregator`. Blocker A.3 (9 new Event subclasses in `libs/gw2_core/src/gw2_core/models.py`) is now ~11% complete -- 1 of 9 (`StunBreakEvent`) shipped through to the wire (the heal aggregator's `stun_breaks` column is LIVE end-to-end via the union-keys row-builder + the `_check_invariants` conservation invariant). The §1 SCAFFOLD-zero column -> upstream blocker mapping gained a new LIVE cell (`heal.stun_breaks` -- no longer SCAFFOLD-zero; readiness indicator for the Blocker A.4 path). Priority shifts: Blocker A.4 (parser statechange REMOVE decode extension) + Blocker A.3 (remaining 8 Event subclasses: `BarrierEvent + ConditionRemoveEvent + CCEvent + DownEvent + DeathEvent + DodgeEvent + BlockEvent + InterruptEvent`) -- the cbtevent decode-loop scaffolding per spike doc §A.4 is now established. Blocker B (Skills DB catalog) remains M-L scope from §3; the v0.11.0 cycle authorisation can now move in parallel with Blocker A.3.

## §0 Scope + ownership

> **Cross-references:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) (F17 cycle topology + the SHIP-cycle topology that Wave 8 cascades into) + the downstream consumer [`plans/F17-frontend-rollout.md`](F17-frontend-rollout.md) (the AG Grid W.2-W.12 implementation plan; TODO if absent).

Wave 8 unlocks the **8 SCAFFOLD-zero readout columns** rendered in the status banner of the readout tab (per `web/src/app/fights/[id]/page.tsx`'s `readout-tab-status` element). They stay at 0 by design today because:

- **6 columns** (`defense.time_downed_ms` + `defense.dodges` + `defense.blocks` + `defense.interrupts` + `heal.barrier_total` + `heal.barrier_ps`) await **Blocker A** — the parser's `if is_statechange != 0: continue` filter at `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py:439` SKIPS the statechange records before the REMOVE/APPLY predicates run.
- **2 columns** (`damage.dps_power` + `damage.dps_condi`) await **Blocker B** — the Skills DB catalog with per-skill `damage_type ∈ {power, condi, hybrid}`.

Owners / effort:
- **Blocker A** → `libs/gw2_evtc_parser` + `libs/gw2_core` (parser statechange extension). Effort: **XL** (~1200 LoC across parser + gw2_core models + hermetic tests + real-fixture integration + docs).
- **Blocker B** → `libs/gw2_skills` (NEW library). Effort: **M-L** (~600 LoC across new library + bootstrap script + apps/api startup cache wiring + cross-library typechecks + hermetic tests).

## §1 SCAFFOLD-zero column → upstream blocker mapping

Each of the 8 SCAFFOLD-zero columns maps to one upstream blocker. The mapping drives §5's migration impact (which frontend files change per column-unlock).

| Column | Frontend cell | Unblocked by |
|---|---|---|
| `damage.dps_power` | `PlayerReadoutDamage.tsx` DPS power cell | Blocker A.4 + Blocker B.5 |
| `damage.dps_condi` | `PlayerReadoutDamage.tsx` DPS condi cell | Blocker A.4 + Blocker B.5 |
| `heal.barrier_total` | `PlayerReadoutHeal.tsx` Barrier total cell | Blocker A.4 (parser emits `BarrierEvent`) |
| `heal.barrier_ps` | `PlayerReadoutHeal.tsx` Barrier/s cell | Blocker A.4 + new barrier-rate aggregator |
| `defense.time_downed_ms` | `PlayerReadoutDefense.tsx` Time on ground cell | Blocker A.4 (parser emits `DownEvent` with `downtime_ms`) |
| `defense.dodges` | `PlayerReadoutDefense.tsx` Dodges cell | Blocker A.4 (`StateChangeCount(dodge)`) |
| `defense.blocks` | `PlayerReadoutDefense.tsx` Blocks cell | Blocker A.4 (`StateChangeCount(block)`) |
| `defense.interrupts` | `PlayerReadoutDefense.tsx` Interrupts cell | Blocker A.4 (`StateChangeCount(interrupt)`) |

## §2 Blocker A — parser-side statechange extension (XL, ~1200 LoC)

Eight sub-blocks from the spike doc §2 Blocker A:

1. **A.1** Audit arcdps' ~150 statechange kinds (reference: Elite Insights C# `StateChange` enum). Effort: **S**.
2. **A.2** Map each kind → matching `Event` subclass. Already-covered: `BoonApplyEvent` REMOVE + APPLY channels (~30% of kinds). To-add: 9 new subclasses for the remaining ~70%. Effort: **M**.
3. **A.3** Add 9 new `EventType` enum entries + 9 new Pydantic subclasses in `libs/gw2_core/src/gw2_core/models.py`: `BarrierEvent`, `ConditionRemoveEvent`, `CCEvent`, `DownEvent`, `DeathEvent`, `DodgeEvent`, `BlockEvent`, `InterruptEvent`, `StunBreakEvent`. Effort: **M**.
4. **A.4** Extend the parser's `cbtevent` decode loop to read the statechange kind byte (currently SKIPPED at line 439) and emit the matching subclass. The discriminator `event_type` contract is forward-compat — the existing JSONL readers dispatch on the new types without code changes. Effort: **XL**.
5. **A.5** 8 hermetic `parse_events` predicate-boundary tests in `libs/gw2_evtc_parser/tests/test_parser_emit_statechange.py` (one per new subclass). Effort: **M**.
6. **A.6** Real-fixture integration test via `test_parser_applive_realfixture.py` (extends the F1 calibration pilot to the new statechange kinds). Effort: **M**.
7. **A.7** Update `docs/v0.10.11-phase-9-conditions.md` + `docs/ROADMAP.md` §1.1 cycle shipts (Phase 9 step 4-STEPS). Effort: **S**.

**Done when:** `parse_events` emits the 9 new subclasses from a real-fixture input; the F1 calibration pilot passes; the `is_statechange != 0` skip at line 439 no longer hides statechange records upstream of the REMOVE/APPLY predicates.

## §3 Blocker B — Skills DB catalog bootstrap (M-L, ~600 LoC, NEW `libs/gw2_skills/` library)

Seven sub-blocks from the spike doc §2 Blocker B:

1. **B.1** Decide source (per [`docs/v0.9.0-combat-readout-design.md` §11 Q1](../docs/v0.9.0-combat-readout-design.md#11-open-questions-for-the-implementation-cycle)): official GW2 API `/v2/skills` (no `type` field) + manual mapping OR community dataset (gw2efficiency / discretize). Maintenance profile + staleness tolerance are the deciding factors. Effort: **S**.
2. **B.2** Build `libs/gw2_skills/` with `SkillMetadata` Pydantic class (`id + name + type: power|condi|hybrid + icon_url + categorisation: boon|utility|elite|heal|CC`). Effort: **M**.
3. **B.3** Bootstrap catalog: one-time script + versioned JSON dataset under `libs/gw2_skills/src/gw2_skills/data/`. Effort: **M**.
4. **B.4** Cargo-cult into `apps/api` startup via `functools.lru_cache(maxsize=1)` keyed on the catalog hash. Effort: **S**.
5. **B.5** Expose `gw2_skills.lookup_skill(id)` with `SkillNotFoundError` for unknown IDs (defensive — guard against arcdps player builds not in catalog). Effort: **S**.
6. **B.6** Ship as workspace member + add to `pyproject.toml` + verify cross-library typechecks (`gw2_core`, `gw2_evtc_parser`, `gw2_analytics`, `apps/api`). Effort: **S**.
7. **B.7** 5+ hermetic tests for the catalog fixture (canonical 500-skill subset). Effort: **S**.

**Done when:** `gw2_skills.lookup_skill(<per-skill-id>)` returns a `SkillMetadata` with `damage_type ∈ {power, condi, hybrid}`; the bootstrap catalog covers ~1000 skills; cross-library imports typecheck.

## §4 Sequencing (proposed)

Wave 8 ships in 2 cycles per the spike §4 estimates:

- **v0.10.21** (or whenever budget authorised): ship **Blocker A** (XL) + **Blocker B part 1** (M). ~1800 LoC, **backend-only**.
- **v0.10.22**: ship **Blocker B part 2** + **Blocker C** (role classifier per spike §2) + **R.1-R.4** (rollers) + **Rt.1-Rt.4** (routes). ~2050 LoC, **backend + frontend scaffolding**.

The 8 SCAFFOLD-zero columns light up incrementally:

1. After Blocker A ships: `defense.time_downed_ms` + `dodges` + `blocks` + `interrupts` + `heal.barrier_*` go live (**5 of 8**).
2. After Blocker B ships: `damage.dps_power` + `damage.dps_condi` go live (**2 of 8**, completing Wave 8).
3. After Blocker C calibrates + R.1-R.4 ship: the `roles: list[str]` column unlocks (downstream of Wave 8 — see `plans/F17-frontend-rollout.md` for the AG Grid components).

## §5 Migration impact in `web/`

When a column's Blocker reaches DONE, the following files change (the **§5 contract** for any wave-pruning commit):

1. **`web/src/app/fights/[id]/page.tsx`** — the `readout-tab-status` banner paragraph prunes the column from the inline `SCAFFOLD-zero` list (the `<code>` mentions).
2. **`web/src/components/PlayerReadout{Damage,Heal,Defense}.tsx`** — the AG Grid column def for the unlocked column flips from `valueGetter: () => 0` (SCAFFOLD-zero stub) to a real `valueGetter: (params) => params.data.<path>` (the aggregation already wired by R.1-R.4).
3. **`web/tests/e2e/fights.spec.ts`** — add a Playwright spec that asserts the unlocked cell renders a non-zero value for a known fixture fight (the readout payload fixture in `tests/e2e/mock-server.mjs` must also be updated to include non-zero wire values for the column).

Net migration: each Blocker-DONE column unlock is **3 small edits** (page.tsx +1/-1 line; PlayerReadout*.tsx ~3 line swap; Playwright spec ~5 line add). **~5 LOC per column × 8 columns = ~40 LOC total** web-side spread across 8 incremental PRs.

## §6 Risks + open questions

1. **Skills DB source staleness** (Bl B) — the GW2 API adds new skills per balance patch; the bootstrap script needs a quarterly re-run. *Mitigation:* cache the catalog hash at startup; `apps/api`'s `/healthz` exposes the loaded hash + a "freshness-days" gauge so stale catalogs surface visibly to the analyst.
2. **Statechange kind unmapped** (Bl A) — uncovered arcdps statechange kinds would silently drop. *Mitigation:* A.2 produces the explicit map; the parser emits `event_type: "unknown_statechange"` as the catch-all so coverage gaps are detectable in the F1 calibration pilot.
3. **Discriminator fallout** (Bl A) — adding 9 new Event subclasses must NOT break the existing JSONL readers' discriminator dispatch. *Mitigation:* A.3 uses the existing `Field(discriminator="event_type")` contract; the spike doc §8 confirms forward-compat for the JSONL write path. Probe: write a single Pydantic test that confirms `TypeAdapter(Event).validate_json(line)` dispatches the new subclass without code changes (a 30-min probe that DE-RISKS A.4 before A.4 ships).
4. **DPS power/condi split semantics** (Bl B) — for `hybrid` skills (e.g. Soul Reaper on Necromancer), per-event may yield different splits than per-roll-up. *Mitigation:* B.2 + B.5 lock the semantics at the catalog level (`damage_type ∈ {power, condi, hybrid}`); the per-roll-up attribute follows the catalog value, not the per-event split.
5. **« time on ground » semantics** (cross-ref design §11 Q4) — locked default is `time_downed_ms = sum(time_in_down_state)`. The display cell needs the same units as Heal barrier/s (per ms-derived rate). Confirmation required before the frontend display logic lands.

## §7 Done criteria

Wave 8 is DONE when **all 8 SCAFFOLD-zero columns** in the `readout-tab-status` banner have been removed (replaced by their unlocked aggregated values) AND the F17 frontend ships the 4 tables with **no SCAFFOLD-zero cell anywhere**. The banner paragraph mutates from the current long footnote into:

> Combat readout loaded · N players · duration X.X s.

with no column-pruning footnote (the SCAFFOLD-zero contract is satisfied because no cell needs the inline note).

---

*Counterpart documents (TODO, complementary to THIS plan):*
- `plans/F17-frontend-rollout.md` — scopes W.2-W.12 AG Grid components per the spike doc §3.4 (separate cycle).
- `plans/BLOCKER-C-role-classifier.md` — scopes the role classifier implementation per the spike doc §2 Blocker C (calibration phase, after R.1-R.4 are stable).

*Owner sign-off required before cycle authorisation:* (the Wave 8 cycle assignee, separate role from this plan's author).
