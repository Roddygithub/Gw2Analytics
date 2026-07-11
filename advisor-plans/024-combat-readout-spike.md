# Plan 024 — Combat readout design/spike (direction)

> **Executor instructions**: This is a **design/spike plan**, not a
> build-everything plan. The goal is to produce a concrete API proposal,
> assess feasibility, and list open questions. Do NOT implement the full
> feature — stop after the spike deliverables are produced.
>
> **Drift check (run first)**: `git diff --stat f0249ef..HEAD -- docs/ libs/gw2_core/ libs/gw2_evtc_parser/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P3
- **Effort**: M (spike) / XL (full implementation)
- **Risk**: LOW (spike only)
- **Depends on**: plan 021 (cleaner services.py makes the backend easier to extend)
- **Category**: direction
- **Planned at**: commit `f0249ef`, 2026-07-11

## Why this matters

The `docs/v0.9.0-combat-readout-design.md` is a 330-line complete design spec for 4 AG Grid tables (Damage, Heal, Boons, Defense) — the single highest-analyst-value feature. It was never started. The blocking prerequisites (9 new Event subclasses, statechange parser, skills DB) were never built.

The spike will answer:
- What 9 Event subclasses are actually needed (validate against real .zevtc data)
- Whether the statechange parser work can be split into an intermediate phase
- What the combined endpoint shape looks like
- Whether the skills DB can be a static JSON file (not a full library)

## Current state

- `docs/v0.9.0-combat-readout-design.md` — 330-line design spec for 4-table combat readout
- `docs/statechange-ids.md` — 117-line statechange ID map (parser work never started)
- `libs/gw2_core/src/gw2_core/models.py` — Event discriminated union has 3 subclasses (DamageEvent, HealingEvent, BuffRemovalEvent). 9 more needed (BoonApplyEvent, CCEvent, DownEvent, etc.)
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` — `parse_events` method only extracts cbtevent structs for damage/healing/buff_removal. Statechange events and skill-activation events are parsed but discarded.

## Scope

**In scope**:
- `docs/` (update existing design doc or create new spike doc)
- `libs/gw2_core/src/gw2_core/models.py` (prototype 1-2 new Event subclasses)
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (assess parser changes)

**Out of scope**:
- Full implementation of any route, aggregator, or UI component
- Production skills DB
- Changes to `apps/api/` routes

## Steps

### Step 1: Analyze existing `.zevtc` fixture diversity

Check how many statechange event types actually appear in the `tests/fixtures/` directory. Run the parser against a sample:

```python
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_bytes
import glob
statechanges_seen = set()
for f in glob.glob("apps/api/tests/_fixtures/*.zevtc"):
    raw = read_zevtc_bytes(open(f, "rb").read())
    for fight in PythonEvtcParser().parse(raw):
        for evt in PythonEvtcParser().parse_events(f.read()):
            if hasattr(evt, 'is_statechange'):
                statechanges_seen.add(evt.is_statechange)
print(sorted(statechanges_seen))
```

Document which statechange IDs appear in real data and which Event subclasses would be needed.

**Deliverable**: List of Event subclasses to add to `gw2_core`, grouped by priority (P0 = appears in fixtures, P1 = appears in real logs, P2 = documented but unconfirmed).

### Step 2: Prototype 2 new Event subclasses

Add `BoonApplyEvent` and `CCEvent` (or the 2 highest-priority from Step 1) to `gw2_core/models.py`:

```python
class BoonApplyEvent(Event):
    event_type: Literal["boon_apply"] = "boon_apply"
    skill_id: int
    duration_ms: int
    stacks: int

class CCEvent(Event):
    event_type: Literal["cc"] = "cc"
    skill_id: int
    value: float
```

Just add the models — no parser changes needed yet. Document the design rationale inline.

**Verify**: `uv run mypy libs/gw2_core/src/` → exit 0; `uv run pytest libs/gw2_core/tests/` → all pass.

### Step 3: Propose unified endpoint shape

Write a proposal for `GET /api/v1/fights/{id}/readout` returning:

```json
{
  "damage": [{"agent_id": 1, "target_id": 2, "skill_id": 100, "damage": 5000, "is_condi": false, "time_ms": 1500}, ...],
  "healing": [...],
  "boons": [{"agent_id": 1, "skill_id": 200, "duration_ms": 5000, "stacks": 3, "time_ms": 1500}, ...],
  "defense": [{"agent_id": 2, "incoming_damage": 5000, "incoming_cc": 100, "time_ms": 1500}, ...]
}
```

Document:
- Whether existing aggregators can be reused or new ones needed
- Whether to paginate (per-agent? per-time-bucket?)
- How the statechange parser change impacts the existing `parse_events` output
- Whether the skills DB can be a static JSON file loaded at startup (match `docs/v0.9.0-combat-readout-design.md` §Skill DB)

**Deliverable**: Updated `docs/v0.9.0-combat-readout-design.md` (or new spike doc) with the endpoint proposal.

### Step 4: Assess parser changes needed

Inspect `parser.py::parse_events` and document:
- Where statechange events are currently discarded (exact line numbers)
- Whether skill-activation events contain `skill_id` or just IDs
- Estimated effort: small (weeks) for just the new Event subclasses + statechange pass-through vs large (months) for full combat readout

**Deliverable**: Effort estimate in the design doc.

## Test plan

No production tests. The spike produces documents and prototypes, not shippable code.

## Done criteria

- [ ] Step 1 produces a list of Event subclasses needed, grouped by priority
- [ ] Step 2 adds 2 prototyped Event subclasses to `gw2_core` (new fields, no parser changes)
- [ ] Step 3 produces an updated design doc with unified endpoint proposal
- [ ] Step 4 documents parser change requirements and effort estimate
- [ ] All existing tests still pass
- [ ] `mypy` and `ruff` pass on modified files

## STOP conditions

Stop and report if:
- Statechange events in arcdps format are radically different from the documented IDs (the design doc was written for a different EVTC version).
- The parser cannot yield statechange events without breaking existing `parse_events` output shape.
- A `.zevtc` fixture file is not available for analysis.

## Maintenance notes

The spike design doc becomes the specification for future implementation plans. Mark it clearly as "Spike output — not yet implemented." The 2 prototyped Event subclasses may need adjustment when the full parser work is done.
