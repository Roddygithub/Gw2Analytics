# Plan 003 — Bootstrap unit tests for `libs/gw2_core/tests/`

- **Slug:** `003-bootstrap-core-domain-tests`
- **Priority:** P3
- **Effort:** M (4–6 hours)
- **Risk:** Low
- **Confidence:** 0.9
- **Status:** open

## Why

`libs/gw2_core/src/gw2_core/` is the lowest layer of the dependency stack: Pydantic-only domain models (`Event` discriminated union, `EliteSpec`, `Profession`, `Population`, `WorldInfo`, etc.) consumed by every layer above. The directory `libs/gw2_core/tests/` is **empty** (verified via `ls -la libs/gw2_core/tests/`).

Downstream coverage exists in `libs/gw2_evtc_parser/tests/` and `libs/gw2_analytics/tests/` but it tests INTEGRATION (mappings, aggregations), not the invariant properties of the domain shapes themselves. Without a base layer of core-shape tests:

- Adding a new `Event` subtype to the discriminated union can silently break the `EventWindowAggregator` / `per_fight_timeline` / `CrossAccountTimelineAggregator` consumers.
- Renaming a `Profession` / `EliteSpec` enum value (e.g. the recent Janthir Wilds expansion) can go undetected at the type boundary.
- Refactors of `extra="forbid"` / `frozen=True` / `Field(ge=0)` invariants can drift without anyone noticing.

## Scope

**In scope:**
- `libs/gw2_core/tests/conftest.py` (NEW — shared test fixtures + reusable Pydantic round-trip helpers).
- `libs/gw2_core/tests/test_models.py` (NEW — hermetic tests for the core domain shapes).
- `libs/gw2_core/pyproject.toml` (add a `[tool.pytest.ini_options]` block if absent, ensure collection picks up the new dir).

**Out of scope:**
- The domain models themselves (no schema changes in this plan).
- Downstream libs (`gw2_analytics`, `gw2_api_client`, `gw2_evtc_parser`, `apps/api`).

## Files to reference (exemplar)

- `libs/gw2_analytics/tests/conftest.py` (the existing pattern in this monorepo, if present).
- `libs/gw2_evtc_parser/tests/test_parser.py` (pytest test pattern; uses python-only assertions, no DB).
- `libs/gw2_core/src/gw2_core/__init__.py` (the canonical list of public shapes to cover).

## Steps

1. Read `libs/gw2_core/src/gw2_core/__init__.py` to enumerate the public shapes: `Event`, `DamageEvent`, `HealingEvent`, `BuffRemovalEvent`, `EliteSpec`, `Profession`, `Population`, `WorldInfo`, `AccountInfo`, etc.

2. Read `libs/gw2_core/src/gw2_core/models.py` (about 200 LoC; already confirmed by Phase 1 recon) to identify the critical invariants on each shape:
   - `Event` discrimination: round-trip via `TypeAdapter(Event).validate_json(...)` correctly dispatches by `event_type` literal.
   - `EliteSpec`: every Janthir-Wilds enum value (canonical 3 newly added, total check).
   - `AccountInfo`: `extra="ignore"` strips unknown v2 fields (forward-compat for the GW2 API).
   - `WorldInfo`: `Population` enum accepts capitalised API value.
   - `frozen=True` on aggregations: `model.model_copy(update={...})` works; direct mutation raises.
   - `extra="forbid"` rejects unknown fields with a `ValidationError`.

3. Write `libs/gw2_core/tests/conftest.py` with shared fixtures (`make_damage_event(time_ms=1500, src=1, dst=2, value=1000, skill_id=42)`, `make_account_info_json(id="X", name="Y", world=1)`, etc.).

4. Write `libs/gw2_core/tests/test_models.py` with hermetic cases (12+):
   - `test_event_discriminated_union_round_trip` (DamageEvent / HealingEvent / BuffRemovalEvent / unknown event_type → ValidationError).
   - `test_elite_spec_janthir_wilds_values_present` (canonical 3 names covered).
   - `test_account_info_extra_ignore_strips_unknown`.
   - `test_world_info_population_capitalised_or_lowercase_not_ok`.
   - `test_frozen_aggregation_blocks_direct_mutation` (raises `ValidationError`).
   - `test_extra_forbid_rejects_unknown_field` (raises `ValidationError`).
   - 6+ more covering round-trip stability + boundary values.

5. CI gating: add `uv run pytest libs/gw2_core/tests/ --collect-only` to `.github/workflows/ci.yml` if not already covered.

## Done criteria

```bash
test -f libs/gw2_core/tests/conftest.py                                                          # exit 0
test -f libs/gw2_core/tests/test_models.py                                                       # exit 0

uv run pytest --collect-only -q libs/gw2_core/tests/                                             # 12+ tests collected
uv run pytest libs/gw2_core/tests/                                                               # PYTEST=0
uv run ruff check libs/gw2_core/tests/                                                           # RUFF=0
uv run mypy --no-incremental libs/gw2_core/tests/ libs/gw2_core/src/                             # MYPY=0
uv run pytest libs/gw2_core/tests/ 2>&1 | grep -c 'passed'                                        # ≥12
```

## Maintenance note

Every new `Event` subtype added to `gw2_core/models.py` MUST add a round-trip test to `test_models.py::test_event_discriminated_union_round_trip` (or equivalent). Adding a Janthir-Wilds-era elite spec MUST add a `test_elite_spec_*` assertion.

## Escape hatch

If the Pydantic round-trip machinery needs richer fixture builders (e.g. `make_buff_removal_dual_emit(...)` for the v0.6.0 dual-emit path), put the helpers in `libs/gw2_core/tests/conftest.py` and re-export from `libs/gw2_analytics/tests/conftest.py` if needed. Do NOT add business logic to the core fixtures.
