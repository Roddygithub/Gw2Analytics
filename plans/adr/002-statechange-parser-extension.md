# ADR 002 — statechange parser extension (Phase 9 Step 4)

**Status:** Accepted; locked at byte offset for forward-deferred F17 muster (target implementation: v0.10.21+).
**Deciders:** @GW2Analytics-maintainer (the user).
**Date:** 2026-07-12.
**Cycle context:** v0.10.20 plan-landing cycle (`plans/RELEASE-v0.10.20.md`).
**Forward-blocker for:** F17 combat readout (4 tables: Damage / Heal / Boons / Defense per `docs/v0.9.0-combat-readout-design.md`).

---

## §1 — Context

The arcdps combat-log protocol encodes buff APPLY/REMOVE events in TWO
distinct cbtevent record paths:

| Marker | Byte flags | Path |
|---|---|---|
| `CBTS_BUFFAPPLY` | `is_statechange=1, is_buffremove=0` | statechange path (currently filtered upstream) |
| `CBTS_BUFFREMOVE` (non-statechange) | `is_statechange=0, is_nondamage > 0, value == 0, buff_dmg > 0` | non-statechange path (REMOVE channel) — already emitted as `BuffRemovalEvent` |
| `CBTS_BUFFAPPLY` (non-statechange APPLY burst) | `is_statechange=0, is_nondamage > 0, value > 0, buff == 0` | non-statechange path (HEALING channel as a `HealingEvent` side-effect) — already emitted |

The upstream parser filter `if is_statechange != 0: continue` (in
`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`) is single-shot
and conservative: it drops ALL statechange records, including the
`CBTS_BUFFAPPLY` markers. This means the parser NEVER emits
`BuffApplyEvent` records — only `BuffRemovalEvent` + `HealingEvent` for
the non-statechange paths.

The F17 muster's "Boons" table requires both apply-count and remove-count
per profession-spec pair to derive "boons uptime over the fight
duration." Without `BuffApplyEvent`, F17's "Boons" table cannot compute
uptime; the muster falls back to "removal volume only," which the
analyst already flagged as a 50%+ information loss.

---

## §2 — Decision

**Decision D.1**: Extend the upstream `if is_statechange != 0: continue`
filter to a pass-through sub-branch that explicitly allows
`CBTS_BUFFAPPLY` (`is_statechange=1, is_buffremove=0`) markers.

**Decision D.2**: The sub-branch dispatches to a new `BuffApplyEvent`
emit path (parallel to the existing `HealingEvent` + `BuffRemovalEvent`
dual-channel emit contract). No re-engineering of the upstream filter
— surgical structural change ONLY at the byte-offset dispatching layer.

**Decision D.3**: Lock the structural change at byte offset + dispatch
predicate EXCLUSIVELY. Future parser refactors that touch the upstream
filter MUST preserve the `CBTS_BUFFAPPLY` pass-through contract as a
regression-tested invariant (test_parser_emit_buff_apply_statechange_marker).

---

## §3 — Alternatives considered

### A.1 — Full statechange acceptance (pass-through ALL `is_statechange != 0`)
**Rejected.** Statechange records include non-buff events (combat state
transitions, agent-spawn, area-transition, etc.) that the parser does
not have dual-channel emit contracts for. Accepting all would require
designing new Event subclasses for each statechange type, doubling the
parser's surface area + doubling the test matrix. Effort: XL+. Out of
scope for v0.10.20's 1-iteration budget.

### A.2 — Pass-through `CBTS_BUFFAPPLY` only (the chosen decision)
**Adopted.** Surgical change at the byte-offset dispatching layer. Single
new Event subclass (`BuffApplyEvent`). Test matrix grows by ~3 cases
(`test_parser_emit_buff_apply_statechange_marker` extends to cover the
non-applicability boundaries: `is_statechange=1, is_buffremove > 0`,
`is_statechange=1, is_nondamage > 0`, etc.). Effort: M. 1-iteration
budget within v0.10.21.

### A.3 — Out-of-band apply tracking (lazy scan in post-parse aggregator)
**Rejected.** Buff APPLY events are emitted by arcdps with per-frame
idempotent semantics (one APPLY per boon per agent per fight). Lazily
scanning the event blob for "missing applies" would require heuristic
matching (`a REMOVE without prior APPLY = chest APPLY by default`),
which corrupts the analyst's boons-uptime computation when
profession-spec pair changes mid-fight (e.g., a Druid entering Celestial
form which strips most boons). Effort for heuristic design + testing:
L. Out of scope.

---

## §4 — Impact analysis

### I.1 — Parser dual-channel emit contract (PRESERVED)

The chosen decision adds a THIRD Event subclass to the discriminated
union but does NOT modify the existing dual-channel emit contract for
`DamageEvent` / `HealingEvent` / `BuffRemovalEvent`. The downstream
aggregator surface area grows by 1 (BuffApplyEvent requires an
analogous aggregator per `docs/v0.9.0-combat-readout-design.md`).

### I.2 — K-cluster test-substrate surface (ZERO impact)

The M8 K-cluster (forward-deferred from v0.10.19 close-out; closed at
v0.10.20) is in the WEBHOOKS + ARQ + DNS TESTS, NOT in the
gw2_evtc_parser surface. ADR 002's implementation at v0.10.21+
will not regress K-cluster closure progress.

### I.3 — F17 muster (UNBLOCKED at v0.10.21+)

F17 currently relies on `BuffRemovalEvent` only (50% information loss
per §1). ADR 002 implementation adds `BuffApplyEvent`, which
unblocks F17's "Boons" table to compute "apply count" + boons uptime.

### I.4 — gw2_analytics surface (NEW aggregator required)

The analytics aggregator surface area for F17 grows by 1:
- `libs/gw2_analytics/src/gw2_analytics/boons_apply.py` (new module;
  mirrors `target_buff_removal.py` shape).
- `libs/gw2_analytics/src/gw2_analytics/__init__.py` re-export
  granularity.

### I.5 — Schema persistence (NO ORM change)

`OrmFightPlayerSummary` does NOT need columns for boons-apply because
F17 derives boons-uptime per-fight as an aggregator output (not as a
per-fight-row column). No alembic migration needed.

### I.6 — API surface (NO schema change)

`/api/v1/fights/{id}/events` does not need a new `target_buff_apply`
enum because boons-apply is GROUP-LEVEL (entire team boon-uptime per
profession-spec pair), not TARGET-LEVEL. F17's API surface stays
3-rollup (DPS / Healing / BuffRemoval) + 1-group-rollup (Squad /
Subgroup). No schema change to `FightEventsSummaryOut`.

---

## §5 — Implementation scope (v0.10.21+ execution)

The implementation is OUT OF SCOPE for v0.10.20 (which is M8 PRIMARY).
The v0.10.21+ cycle that executes this ADR MUST include:

1. **gw2_evtc_parser**: extend `if is_statechange != 0: continue` to
   add the `CBTS_BUFFAPPLY` pass-through sub-branch at
   `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`. Add
   `BuffApplyEvent` to `libs/gw2_core/src/gw2_core/models.py`
   (Pydantic discriminated union).

2. **gw2_core**: extend the `Event` discriminated union
   `libs/gw2_core/src/gw2_core/models.py` with `BuffApplyEvent`
   (mirrors `BuffRemovalEvent` shape minus the `target_agent_id`
   -> `source_agent_id` redirect).

3. **gw2_analytics**: author `boons_apply.py` aggregator +
   `target_buff_apply.py` aggregator (new sibling to
   `target_buff_removal.py`).

4. **Parser tests**: extend
   `libs/gw2_evtc_parser/tests/test_parser_emit_buff.py` with:
   - `test_parse_events_emit_buff_apply_statechange_marker` (already
     exists as a regression-padding test per
     `plans/AUDIT-2026-07-12-cd6e9ad.md` §2; now promotes from
     regression-padding to full assertion).
   - 2 NEW tests:
     - `test_is_statechange_other_markers_still_filter_upstream`
       (locks that `is_statechange=1, is_buffremove > 0` STILL drops).
     - `test_buff_apply_byte_offset_49_empirical_lock` (locks the
       dispatch predicate at byte offset 49).

5. **apps/api F17 muster endpoint**: extend
   `apps/api/src/gw2analytics_api/routes/fights.py` `_load_fight_events`
   to handle the `BuffApplyEvent` discriminator in the TypeAdapter
   (auto-handled by Pydantic v2 via discriminated-union inheritance).

---

## §6 — Cross-references

- **F17 sizing spike** (locked at v0.10.19 plan-landing):
  `docs/v0.10.19-combat-readout-spike.md`.
- **F17 design** (XL+ effort): `docs/v0.9.0-combat-readout-design.md`.
- **Parser upstream filter**: `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` line ~`if is_statechange != 0: continue`.
- **Pydantic Event discriminated union**:
  `libs/gw2_core/src/gw2_core/models.py`.
- **Existing parser tests**:
  `libs/gw2_evtc_parser/tests/test_parser_emit_buff.py`.
- **Cycle thread retrospective (v0.10.17 → v0.10.18 → v0.10.18.1)**:
  `plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md`.
- **v0.10.20 mimo-half cycle plan** (M8 PRIMARY execution, NOT F17):
  `plans/RELEASE-v0.10.20.md`.
- **v0.10.20 plan-landing cycle-start audit**:
  `plans/AUDIT-2026-07-12-v01020-plan-landing.md`.

---

## §7 — Re-evaluation conditions

This ADR MUST be re-evaluated if:

1. arcdps introduces a NEW `CBTS_*` marker with byte-offset ambiguity
   (lock pattern: arcdps adds marker → this ADR is stale).
2. The Pydantic v2 discriminated-union inheritance model changes
   (lock pattern: pydantic releases 2.x minor → this ADR's §5
   implementation scope must be verified against the new Pydantic
   release).
3. F17's "Boons" table re-designs away from "boons-uptime" metric
   (lock pattern: analyst feedback changes the metric → this ADR's
   §4 impact analysis is stale).
