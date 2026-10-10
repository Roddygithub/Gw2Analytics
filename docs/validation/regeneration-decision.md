# Regeneration / buff-state decision — **B**

The reconciliation record originally said "Decision: **adopt** (3) — the
committed, tested, EI-3.26-tagged lineage." That wording implied the code from
`reconcile/uptime-semantics` and `rework/wave6-uptime-f7e73e5` had been
integrated into the candidate. **It has not been, and it should not be.** This
record fixes the wording and states the actual decision.

## Decision

**B — preserve the regeneration/uptime/ownership semantics as
implementation-independent certification knowledge. Do not integrate the code.**

## Evidence

1. **The branches change the parts of the product that are being removed.** Both
   branches touch `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`,
   `statechange_dispatch.py` and the analytics that consume its event stream
   (`buff_state.py`, `rotation.py`, `temporal_identity.py`, `ei_compare.py`).
   The refoundation's whole point is that the custom parser is replaced by
   Elite Insights, so integrating these commits is work on a path slated for
   deletion.
2. **The executed field-coverage gate shows the target is not ready.** The raw
   buff event stream (apply / remove / extension) is `MISSING` from the EI
   export and requires an EI export change. Re-deriving uptime semantics against
   the parser's event stream is therefore not the shape the migration needs;
   the semantics have to be restated against whatever source replaces it.
3. **The deltas are already captured in an implementation-independent form.**
   `scripts/ei-parity/corpus-baseline.json` records, per product path, how many
   EI values differ from the product's own recomputation across the 35-log
   corpus — e.g. `players.buffUptimes.uptime: 190`, `players.rotation: 15`,
   `players.statsAll.downContribution: 6`, `players.statsAll.appliedCrowdControl:
   1`. That is a durable, parser-agnostic acceptance baseline, which is exactly
   what decision B asks for.
4. **Integrating them would change product semantics without EI
   re-certification** — the precise hazard the reconciliation record itself
   warns about for proposals (1) and (2).

## Preserved: the semantic expectations

Extracted from the branch commit subjects and the 2026-09-14 certification
checkpoint. These are the acceptance criteria any future buff-uptime
implementation (EI-backed or otherwise) must satisfy. They are stated in terms
of observable behaviour, not of either implementation.

| # | Expectation | Source commit |
| --- | --- | --- |
| 1 | Regeneration healing is modelled as a queue; the queue semantics must match EI 3.26's ordering and consumption. | `fix(uptime): align Regeneration healing queue semantics with EI 3.26` |
| 2 | Intensity-stacking buffs extend by re-adding duration; extension and removal rules must match EI's. | `fix(uptime): match EI intensity extension and removal rules` |
| 3 | Override ordering is preserved across extensions. | `fix(uptime): preserve override ordering after extensions` |
| 4 | Stack lifecycle (activation, stack decay) follows EI's intensity model. | `fix(uptime): align stack lifecycle with EI 3.26` |
| 5 | Regeneration and buff removal use EI's dispatch rules. | `fix(uptime): match EI regeneration and removal dispatch` |
| 6 | Buff **capacities** come from buff metadata, not a hard-coded table. | `fix(uptime): honor EI buff capacities from metadata` |
| 7 | Recycled agent segments (a despawned instance id reused by another agent) are preserved rather than merged or dropped. | `fix(uptime): preserve recycled agent segments` |
| 8 | Anonymous awareness slices are merged rather than double-counted. | `fix(uptime): merge anonymous awareness slices` |
| 9 | Uptime is computed over an entity model that matches EI's (one entity per accounted actor per slice). | `fix(ei-parity): correct uptime entity model per EI 3.26 semantics` |
| 10 | Ownership attribution and the "final master" resolution match EI 3.26. | `fix(ei-parity): align ownership and final-master semantics with EI 3.26` |
| 11 | The ownership scanner's arcdps lifecycle statechange constants are the correct ones. | `fix(parser): correct ownership scanner statechange constants (Spawn=6, Despawn=7)` |

## Open item this decision exposes

**Item 11 contradicts the code that ships today.** The branch asserts the
ownership scanner should use spawn/despawn statechange constants `6` / `7`, but
`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` currently defines
`_SPAWN_STATECHANGE = 0` / `_DESPAWN_STATECHANGE = 1` and uses them in
`scan_ownership_intervals`. Under decision B this is not patched in place, but
it must not be lost: `gw2_core.OwnershipInterval` is consumed by the product
(`temporal_identity`), so whichever source produces ownership intervals next
must resolve the constants against a real log before the ownership row of the
coverage gate can be considered closed.

## What must NOT happen

- Mechanically merging the ~14-commit chain into the candidate. It rewrites a
  parser that is being deleted and changes product semantics with no EI
  re-certification.
- Deleting the branches. They are the certification knowledge; they stay
  preserved (see the recovery root) until the reviewer approves their disposal.

## Related

- `docs/validation/ei-field-coverage-gate.md` — the gate that forces this framing.
- `docs/audits/REFOUNDATION_RECONCILIATION_2026-10-10.md` — corrected wording.
- `scripts/ei-parity/corpus-baseline.json` — the parser-agnostic delta baseline.
