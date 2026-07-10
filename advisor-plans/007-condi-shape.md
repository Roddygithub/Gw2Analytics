# 007-condi-shape.md

**Status**: proposed (decision pending — Option (a) is the
recommended path; the alternative trade-offs are documented below
for the v0.10.6 followup reviewer).

**Cycle**: v0.10.5 → v0.10.6 followup.

## Prerequisites

This plan is **NOT implementable until `008-parser-yyyymmdd-gate.md` (pending)**
lands the parser-side `buff_dmg` population from `cbtevent` onto
`DamageEvent.buff_dmg` for post-20240501 arcdps builds.

Critical sequencing. Until the parser drops `cbtevent.buff_dmg` onto
`DamageEvent`, the v2 event model is `buff_dmg=None` on every ingested
fight — both pre- and post-20240501. Implementing the Option (a)
**wiring** (Commit 4 in this plan) before the parser-side commit
yields:

- **Pre-20240501 ingests**: `KNOWN_CONDI_NAMES` lookup continues to
  correctly partition (post-20240501 `buff_dmg` field is absent on
  these fights; `damage_event.buff_dmg is None` falls through to the
  skill-name lookup). Same behaviour as v0.10.5.
- **Post-20240501 ingests**: `damage_event.buff_dmg is None` for
  every event — the parser hasn't been updated. The skill-name
  fallback still runs but is incomplete (post-20240501 condi skills
  are not all in `KNOWN_CONDI_NAMES`). The post-20240501 ingests
  land as 100% power (silent accuracy loss — same as v0.10.5).

Per-commit dependency:

| Step | Scope | Required by |
|------|-------|-------------|
| Parser-side `buff_dmg` population | `libs/gw2_evtc_parser/` | Commit 3 / Commit 4 |
| `DamageEvent.buff_dmg` model field | `libs/gw2_core/` (Option (a)) | Commit 4 wiring |
| Route-layer wiring | `apps/api/src/.../routes/players.py` + `apps/api/src/.../services.py` | Depends on parser-side |
| Tests for the partitioned path | `libs/gw2_analytics/tests/test_condi_power_split.py` | Commit 4 |

The model-side field (Commit 2) **CAN land before parser-side** (it
is backward-compatible: `buff_dmg: int | None = None` default covers
all existing JSONL blobs). The **WIRING (Commit 4) MUST NOT land
before parser-side** — implementing wiring without parser-side yields
no observable behaviour change and gives a false sense of progress.

A future implementer who walks this plan top-to-bottom MUST validate
parser-side landing before Commit 4.

**Why this plan exists**: v0.10.5 plan `135-v0105-condi-power-split.md`
wired the per-(fight, account) condi/power split into the slow-path
blob walk + the ingestion path (`services.py::_persist_player_summaries`).
The current implementation uses a **skill-name lookup** against
`KNOWN_CONDI_NAMES` (`libs/gw2_analytics/src/gw2_analytics/condi_power_split.py`)
to partition `DamageEvent.damage` into `condi_damage` +
`power_damage`. Pre-20240501 arcdps encodes the condi portion
implicitly via the skill name (a clean convention — every condi
skill the parser knows about is a known name). Post-20240501
arcdps added a **`buff_dmg` field on the raw `cbtevent` struct**
that encodes the condi portion explicitly. The v2 `DamageEvent`
model (in `libs/gw2_core/src/gw2_core/models.py`) does NOT carry
`buff_dmg` — the parser-side integration landed in the upstream
arcdps, but our parser drop is deferred. As-shipped, post-20240501
fights land as 100% power (silent accuracy loss: a 50% condi
fragment stacks next to a 50% power fragment but the API surfaces
the total as 100% power).

**Goal**: surface `buff_dmg` on the v2 `DamageEvent` so post-20240501
ingests partition correctly, without leaking parser internals into
the route layer AND without fracturing the v2 event-type
discrimination table.

---

## Decision (v0.10.6 implementation target)

**Option (a) — `DamageEvent` extended with an optional `buff_dmg`
field, default `None` for pre-20240501 blobs.**

### Concrete code shape

In `libs/gw2_core/src/gw2_analytics/models.py`:

```python
class DamageEvent(BaseEvent):
    """One outgoing-damage event. ``damage`` is the per-hit
    integer value. ``buff_dmg`` carries the condi portion on
    post-20240501 arcdps builds (``yyyyMMdd >= 20240501``); ``None``
    on pre-20240501 blobs (the upstream arcdps did not encode the
    condi portion explicitly -- the canonical partitioning method
    is the skill-name lookup against ``KNOWN_CONDI_NAMES``).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal[EventType.DAMAGE] = EventType.DAMAGE
    damage: int = Field(..., ge=0)
    buff_dmg: int | None = Field(
        default=None,
        ge=0,
        description="Condi portion on >=20240501 arcdps builds. None on older blobs.",
    )
```

In `libs/gw2_analytics/src/gw2_analytics/condi_power_split.py`:

The `condi_portion_getter` callback becomes optional; the default
reads `event.buff_dmg` directly:

```python
def split_condi_power(
    damage_event: DamageEvent,
    skill_name: str | None,
    *,
    condi_portion_getter: Callable[[DamageEvent], int] | None = None,
) -> tuple[int, int]:
    if condi_portion_getter is not None:
        condi = condi_portion_getter(damage_event)
    elif damage_event.buff_dmg is not None:
        condi = damage_event.buff_dmg
    elif skill_name in KNOWN_CONDI_NAMES:
        condi = damage_event.damage
    else:
        condi = 0
    return condi, damage_event.damage - condi
```

In `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (out of
scope for v0.10.6 plan execution — see "Parser-side fix" below):

The Phase 8 callback that drains `cbtevent` populates
`DamageEvent.buff_dmg` when the build's `yyyyMMdd >= 20240501`.

### Wiring updates (route + services side)

- `apps/api/src/gw2analytics_api/routes/players.py`:
  `_contributions_from_blob_walk` calls `split_condi_power(event,
  skill_name_for_event.get(event.skill_id))` instead of the
  inline `if skill_name in KNOWN_CONDI_NAMES` branch. The skill
  loop + the per-event branch are unchanged in lines/code; the
  indirection improves test-mockability.
- `apps/api/src/gw2analytics_api/services.py`:
  `_persist_player_summaries` calls the same helper.

### Backwards-compat check

- Pre-v0.10.5 JSONL blobs in MinIO carry `DamageEvent` lines
  WITHOUT `buff_dmg`. The `model_validator(mode="before")` in
  `libs/gw2_core/src/gw2_core/models.py` ensures the deserialiser
  fills `buff_dmg=None` on the missing-field case (default value).
  No backfill required.
- Pre-20240501 ingests going forward: parser-side `buff_dmg=None`
  → falls through to `KNOWN_CONDI_NAMES` lookup. Behaviour identical
  to v0.10.5.
- Post-20240501 ingests going forward: parser-side `buff_dmg=N`
  → condi = N, power = `damage - N`. Behaviour correctly partitioned.

### Test coverage

- `libs/gw2_analytics/tests/test_condi_power_split.py`: add 4 NEW
  tests for the `buff_dmg`-set path (`(0, 500) (500, 0)`,
  `(300, 700) (1000, 0)`); the existing 8 tests must still pass
  (the `condi_portion_getter` callback signature is preserved as
  optional, defaulting to the new behaviour).

### Atomic commit shape

The implementation lands in **5 separate atomic commits** — the
reviewer flagged that ``Commit 3`` and ``Commit 4`` in the
v0.10.5-doc draft (which lumped ``condi_power_split`` signature
change + call-site switch + tests together) cannot land atomic
because the call-site switch MUST follow the signature change AND
both MUST follow parser-side (see §Prerequisites).

- **Commit 1** (parser-side, out of scope): `libs/gw2_evtc_parser/`
  populates `buff_dmg` when `yyyymmdd >= 20240501` — this is the
  blocking dependency for Commits 3 + 4.
- **Commit 2** (model-side, in scope for v0.10.6): `DamageEvent`
  gains `buff_dmg: int | None = Field(default=None, ge=0)`. Backward-
  compatible (default fills the missing-field case) — can land
  independently of Commit 1.
- **Commit 3** (form-only, in scope for v0.10.6):
  `condi_power_split.split_condi_power` no longer takes the
  ``condi_portion_getter`` callback — instead reads
  ``damage_event.buff_dmg`` directly when present, else falls through
  to the ``KNOWN_CONDI_NAMES`` lookup. The signature change is
  form-only — the function still accepts `damage_event` + skill_name.
  This commit lands BEFORE Commit 4 (the call-site switch) because
  the call sites cannot be updated until the new signature exists.
- **Commit 4** (call-site switch, in scope for v0.10.6): replace
  the INLINE ``if skill_name in KNOWN_CONDI_NAMES`` branches in
  ``apps/api/src/.../routes/players.py`` + ``services.py`` with a
  single call to ``condi_power_split.split_condi_power(event,
  skill_name)``. This commit is the "call out to the helper" change
  — required to surface the post-20240501 condi portion on the wire.
  **Note**: as shipped in v0.10.5, the call sites still do INLINE
  skill-name lookup; this commit closes that gap.
- **Commit 5** (tests, in scope for v0.10.6): add 4 NEW tests
  for the ``buff_dmg``-set partition path
  (``(0, total)``, ``(condi, total - condi)``, multi-event sums,
  edge case where `damage_event.buff_dmg > damage_event.damage`).
  Existing 8 tests continue to pass. The tests should land AFTER
  Commit 4 (the call-site switch) so they verify the
  end-to-end route/services behaviour, not just the helper.

---

## Alternative (b) — Dedicated `CondiDamageEvent` subclass of `DamageEvent`

### Trade-offs

- **Pro**: zero changes to the pre-existing `DamageEvent` wire format.
  The new variant's discriminator (`event_type="condi_damage"`) is
  additive.
- **Pro**: every downstream aggregation that needs both the total
  damage AND the condi split emits 1 pre-split `DamageEvent` (covers
  the "total_damage" sum) + 1 `CondiDamageEvent` covering the condi
  slice only. The split is on the parser side; the routes/services
  pipelines aggregate both atomically.
- **Con**: BREAKS the `damage = sum(DamageEvent.damage)` invariant
  in `services.py`_persist_player_summaries`. The aggregation logic
  must filter on `event_type` to avoid double-counting (the condi
  event's `damage` overlaps with the parent `DamageEvent.damage`).
- **Con**: halves the events-per-fight count for post-20240501
  fights (each cbtevent now emits 2 events — the parent total +
  the condi slice). The blob size grows ~2x; the route slow-path
  cost grows ~2x. Mitigated by the fast-path (which projects from
  the materialised summary), but the migration path
  (`apps/api/src/gw2analytics_api/backfill.py`) walks every event,
  so the per-event cost matters.

### Why not chosen

The 2x write-path cost on every post-20240501 cbtevent is too
expensive for the read-side benefit of having the split on the
wire. The model-side change in Option (a) gives the same split
without the wire-shape grow.

---

## Alternative (c) — Keep `KNOWN_CONDI_NAMES` callback long-term

### Trade-offs

- **Pro**: zero code change. The callback-based escape hatch
  already exists.
- **Pro**: no schema migration. No model change. Wire format is
  unchanged.
- **Con**: silent accuracy loss on post-20240501 ingests. The
  condi portion is 0 for `UNKNOWN` skills (a not-in-`KNOWN_CONDI_NAMES`
  post-20240501 condi skill — e.g. a new condi skill arcdps adds
  in a future release). The accuracy drift is unbounded.
- **Con**: the callback leaks parser internals into the public
  surface (already cited by previous code reviewers).

### Why not chosen

The unbounded accuracy drift is unacceptable for an analytics
product. A user who uploads a post-20240501 log gets a 100% power
breakdown even when 30-50% of the damage is condition damage.
The downstream frontend (the per-player condi/power bar in the
web UI) would mislead the analyst.

---

## Why Option (a) wins

1. **Schema silent default**: `None` is a clean sentinel for the
   pre-20240501 blobs; no migration needed for the JSONL history.
2. **Route-layer oblivious**: the routes/services pipelines
   already call `split_condi_power(event, skill_name)`; the helper
   becomes smarter on its own without the call sites changing.
3. **Discriminator table quiet**: `DamageEvent|HealingEvent|BuffRemovalEvent`
   is unchanged. Adding `buff_dmg: int | None` is an additive field
   on the existing variant.
4. **Tests minimal-add**: only the 4 NEW tests for `buff_dmg`-set
   branch; the existing 8 callback tests still pass.

---

## Out of scope (explicit non-goals)

- Parser-side fix to populate `buff_dmg` (lives in
  `libs/gw2_evtc_parser/`). Track in `008-parser-yyyymmdd-gate.md`
  (pending followup).
- Backfill CLI for pre-v0.10.6 post-20240501 ingests that landed
  without `buff_dmg`. The silent-100%-power semantic is
  acceptable; the operator runs the backfill from a maintenance
  page if precision matters.
- Per-character condi split (currently per-account). The data is
  cheap to add later (the entity is `(account_name, char_name,
  fight_id)` instead of `(account_name, fight_id)`); out of scope
  for this plan.
