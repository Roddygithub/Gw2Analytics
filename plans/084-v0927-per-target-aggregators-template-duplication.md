# Plan 084 — v0.9.27 — `target_dps.py` + `target_healing.py` + `target_buff_removal.py` template duplication → shared `_PerTargetRollupBase` abstract class

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (MED DX + perf):** The 3 per-target aggregators (`target_dps.py` + `target_healing.py` + `target_buff_removal.py`) are byte-for-byte near-clones that differ only in 4 field names:

| Module | Input event | Row schema | 3 totals fields | Rate field | Sentinel |
|---|---|---|---|---|---|
| `target_dps.py` | `DamageEvent` | `TargetDpsRow` | `total_damage` + `attack_count` | `dps` | `_DEFAULT_DPS` |
| `target_healing.py` | `HealingEvent` | `TargetHealingRow` | `total_healing` + `heal_count` | `hps` | `_DEFAULT_HPS` |
| `target_buff_removal.py` | `BuffRemovalEvent` | `TargetBuffRemovalRow` | `total_buff_removal` + `strip_count` | `bps` | `_DEFAULT_BPS` |

The duplicated parts (across all 3 files):

1. **Aggregator method body** — `if duration_s < 0: raise ValueError(...)` + the `total_by_target: dict[int, int] = defaultdict(int)` + `count_by_target: dict[int, int] = defaultdict(int)` + `grand_total = 0` accumulator pattern + the per-event `total_by_target[e.target_agent_id] += ...` accumulation + the `dps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_DPS` + the row-construction loop + the `rows.sort(key=lambda r: (-r.total_X, r.target_agent_id))` (60+ lines ×3 = 180 lines duplicated).
2. **`_check_invariants` static method** — `actual_sum = sum(r.total_X for r in rows)` + `if actual_sum != expected_sum: raise ValueError(...)` + the `attack_count`/`heal_count`/`strip_count >= 1` check + the `pairwise` ordering invariant (25+ lines ×3 = 75 lines duplicated).
3. **The `name_map or {}` pattern** + the `rows.sort(...)` line + the `pairwise` loop — every adjacent line is identical across the 3 files.

The 3 modules collectively contain ~500 lines of which ~350 are duplication. The plan factors the duplicated parts into:

- **`libs/gw2_analytics/src/gw2_analytics/_per_target_base.py`** (NEW module): abstract `PerTargetRollupBase(Generic[TEvent, TRow])` class with abstract methods `_make_row(target, total, count, name)` (the 1 line that differs per module) + `_total_attribute(event)` (the field name `.damage` / `.healing` / `.buff_removal` per event type) + `_count_label()` (the per-row count-field name `attack_count` / `heal_count` / `strip_count` — needed for the `_check_invariants` count >= 1 check) + `_ordering_attr()` + `_rate_attr()`. The base class implements `aggregate()` + `_check_invariants()` once.
- **Each per-target module** (3 files edited): each retains its public `TargetXxxRow` Pydantic model + its public `TargetXxxAggregator(PerTargetRollupBase[...])` subclass that supplies the 4 abstract methods.

Net diff: **~350 lines deleted across the 3 files** (the duplicated bodies) + **~150 lines added in the new base module** = ~200 lines net removed. The 3 modules each shrink to ~50 lines (model + aggregator subclass).

The refactor is INTERNAL (no public API change): the 3 public schemas keep their name + field names; the 3 public aggregator classes keep their name + `aggregate()` signature (events, duration_s, name_map=None). The `_check_invariants` static methods lose their public-class reference (they become private on the base).

## File changes

### 1 NEW module + 3 file edits + 1 NEW test file

**`libs/gw2_analytics/src/gw2_analytics/_per_target_base.py`** (NEW ~150 lines):

```python
"""Private base class for the 3 per-target rollup aggregators.

The 3 per-target rollups (DPS + HPS + BPS) are strict parallels
that differ only in the row field names + the event's value
attribute name. ``PerTargetRollupBase`` factorises the duplicated
~180 lines per file into a single generic aggregate() +
_check_invariants() that the 3 subclasses parameterise via 4
abstract methods (1-line each).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise
from typing import Generic, TypeVar

from pydantic import BaseModel

TEvent = TypeVar("TEvent")
TRow = TypeVar("TRow", bound=BaseModel)


class PerTargetRollupBase(Generic[TEvent, TRow], ABC):
    """Stateless per-target roll-up aggregator. Subclasses are pure
    row-config + field-name plumbing."""

    @abstractmethod
    def _total_attribute(self, event: TEvent) -> int:
        """Return the event-attribute that contributes to the row's total."""
        # ``target_dps`` returns ``event.damage``; ``target_healing``
        # returns ``event.healing``; ``target_buff_removal`` returns
        # ``event.buff_removal``.

    @abstractmethod
    def _make_row(
        self,
        target: int,
        total: int,
        count: int,
        name: str | None,
        rate: float,
    ) -> TRow:
        """Construct the row model from the per-target accumulators + the
        precomputed rate. Subclass is responsible for the
        field-name mapping (total_X / rate_field / count_field)."""

    @abstractmethod
    def _rate_factor(self) -> float:
        """Return the per-second rate factor for the row's rate field.

        ``dps`` for ``target_dps``; ``hps`` for ``target_healing``;
        ``bps`` for ``target_buff_removal``.

    def aggregate(
        self,
        events: Iterable[TEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
    ) -> list[TRow]:
        """Compute the per-target rollup. Implementation is identical
        across the 3 subclasses; only the field names differ."""
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        total_by_target: dict[int, int] = defaultdict(int)
        count_by_target: dict[int, int] = defaultdict(int)
        grand_total = 0
        for e in events:
            total_by_target[e.target_agent_id] += self._total_attribute(e)
            count_by_target[e.target_agent_id] += 1
            grand_total += self._total_attribute(e)

        rate_factor = self._rate_factor() if duration_s > 0 else 0.0
        rows = [
            self._make_row(
                target=target,
                total=total_by_target[target],
                count=count_by_target[target],
                name=(name_map or {}).get(target),
                rate=total_by_target[target] * rate_factor,
            )
            for target in total_by_target
        ]
        # Sort: highest total first; ties broken by ascending target_agent_id.
        # The ordering_-attribute name is canonical across the 3 subclasses
        # so the sort key is uniform.
        rows.sort(key=lambda r: (-self._ordering_attr(r), r.target_agent_id))
        self._check_invariants(rows, grand_total)
        return rows

    @abstractmethod
    def _ordering_attr(self, row: TRow) -> int:
        """Return the row's primary ordering attribute (the total that
        drives the descending sort)."""

    @staticmethod
    def _check_invariants(rows: list[TRow], expected_sum: int) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Implementation reads the Pydantic ``model_fields`` to discover
        the ordering-attribute name + count-attribute name; the schema's
        Pydantic-driven introspection is the canonical "single source of
        truth" for the field names (no subclass plumbing needed for
        the invariant name-resolve).
        """
        row_cls = rows[0].__class__
        fields_meta = row_cls.model_fields
        # The ordering_attr is the largest non-negative int field that is
        # not the rate field. The count field is the int field with
        # ``ge=1`` (the only >=1 constraint in the 3 subclasses).
        ordering_attr_name = None
        count_attr_name = None
        for name, f in fields_meta.items():
            if f.annotation is int and name != "target_agent_id":
                if ordering_attr_name is None:
                    ordering_attr_name = name
                # Pydantic v2 stores ge/le in metadata; the count field
                # has the unique ``ge=1`` constraint.
                for entry in f.metadata:
                    ge = getattr(entry, "ge", None)
                    if ge == 1:
                        count_attr_name = name
                        break
        if ordering_attr_name is None or count_attr_name is None:
            return  # Not a per-target rollup schema; skip
        actual_sum = sum(getattr(r, ordering_attr_name) for r in rows)
        if actual_sum != expected_sum:
            msg = (
                f"sum of row.{ordering_attr_name} ({actual_sum}) "
                f"!= sum of event attribute ({expected_sum})"
            )
            raise ValueError(msg)
        for r in rows:
            if getattr(r, count_attr_name) < 1:
                msg = (
                    f"{row_cls.__name__}({r.target_agent_id}).{count_attr_name} "
                    f"({getattr(r, count_attr_name)}) must be >= 1"
                )
                raise ValueError(msg)
        # Ordering invariant
        prev_ordering = None
        prev_target = None
        for curr in rows:
            ordering = getattr(curr, ordering_attr_name)
            if prev_ordering is not None and prev_ordering < ordering:
                msg = f"rows not ordered by (ordering DESC, target_agent_id ASC)"
                raise ValueError(msg)
            if (
                prev_ordering is not None
                and prev_ordering == ordering
                and prev_target >= curr.target_agent_id
            ):
                msg = f"tie not broken by target_agent_id ASC"
                raise ValueError(msg)
            prev_ordering = ordering
            prev_target = curr.target_agent_id
```

Wait — the `ordering_attr` abstract method handles the descending sort key. The invariants resolution via Pydantic `model_fields` introspection is the cleaner approach since we always have the schema in hand.

Actually the simpler design: each subclass passes a `_FieldNames` frozen dataclass to the base class with `total_name` + `count_name` + `rate_name` + `ordering_name` + `default_rate` + `event_attr_name`. The base class then uses these strings. 4-string config vs 4-method abstract — config is simpler.

The plan will use the dataclass-config approach:

```python
@dataclass(frozen=True, slots=True)
class PerTargetFields:
    """Per-subclass configuration for PerTargetRollupBase."""
    event_attr_name: str        # ``"damage"`` / ``"healing"`` / ``"buff_removal"``
    total_attr_name: str        # ``"total_damage"`` / ``"total_healing"`` / ``"total_buff_removal"``
    count_attr_name: str        # ``"attack_count"`` / ``"heal_count"`` / ``"strip_count"``
    rate_attr_name: str         # ``"dps"`` / ``"hps"`` / ``"bps"``
    default_rate: float = 0.0   # The sentinel for ``duration_s <= 0``
```

And the subclasses become:

```python
@dataclass(frozen=True, slots=True)
class _TargetDpsFields:
    event_attr_name = "damage"
    total_attr_name = "total_damage"
    count_attr_name = "attack_count"
    rate_attr_name = "dps"
    default_rate = 0.0

class TargetDpsAggregator(PerTargetRollupBase[DamageEvent, TargetDpsRow, _TargetDpsFields]):
    def __init__(self):
        super().__init__(_TargetDpsFields())
```

The body of `aggregate()` + `_check_invariants()` lives in the base class; the 3 subclasses are pure config.

### `libs/gw2_analytics/src/gw2_analytics/target_dps.py`** — shrinks from ~130 lines to ~50 lines:
- Keep the `TargetDpsRow` Pydantic model (unchanged)
- Add `_TargetDpsFields = PerTargetFields(event_attr_name="damage", total_attr_name="total_damage", count_attr_name="attack_count", rate_attr_name="dps")` module-level constant
- Rewrite `TargetDpsAggregator` to subclass `PerTargetRollupBase[DamageEvent, TargetDpsRow, _TargetDpsFields]` with no body overrides (the base class handles `aggregate()` + `_check_invariants()`)

### `libs/gw2_analytics/src/gw2_analytics/target_healing.py`** — analogously shrinks to ~50 lines.

### `libs/gw2_analytics/src/gw2_analytics/target_buff_removal.py`** — analogously shrinks to ~50 lines.

### NEW `libs/gw2_analytics/tests/test_per_target_rollup_base.py` — 8 hermetic tests

| # | Test | Asserts |
|---|---|---|
| 1 | `PerTargetRollupBase._check_invariants([])` does NOT raise | Empty input short-circuits the sum check |
| 2 | Construct a synthetic subclass with 1 row, `_check_invariants([row])` passes when sum matches | Single-row happy path |
| 3 | Construct a synthetic subclass with 2 rows in correct order, passes | Multi-row ordering invariant holds |
| 4 | Construct a synthetic subclass with 2 rows in WRONG order (ascending instead of descending), raises ValueError | The descending-sort invariant fires |
| 5 | Construct a synthetic subclass with 2 rows tied at the ordering_attr but wrong target_agent_id order, raises | The tie-break invariant fires |
| 6 | `TargetDpsAggregator().aggregate([], duration_s=10.0)` returns `[]` | The 3 existing per-target subclasses still work after refactor |
| 7 | `TargetDpsAggregator().aggregate([DamageEvent(...)], duration_s=2.0)` returns 1 row with `dps = damage/2.0` | The DPS math is unchanged |
| 8 | `TargetHealingAggregator` and `TargetBuffRemovalAggregator` round-trip same fixtures | The 3 subclasses share identical behavior on identical inputs (modulo field names) |

The plan re-exercises the existing 3 test files (`test_target_dps.py` + `test_target_healing.py` + `test_target_buff_removal.py`) unchanged — they verify the post-refactor output is identical to the pre-refactor output (regression contract).

## Considered and rejected

- **Alternative: extract a `_per_target_base.py` module-level function `aggregate_per_target(events, duration_s, name_map, *, event_attr, total_attr, ...)`** — 8+ keyword arguments; the dataclass-config approach is more type-safe + self-documenting.
- **Alternative: use a generic `Protocol` instead of `ABC`** — the base class is concrete (not a duck-typed Protocol); `ABC` is the canonical Python approach for "subclass must override these methods".
- **Alternative: keep the 3 files as-is + add a `_shared_invariants` helper module** that the 3 files call — the helper approach preserves the duplication; the dataclass-config + base class approach is the canonical OO refactor.
- **Alternative: leave the duplication alone + add a "DO NOT EDIT" comment at the top of each file** — the comment doesn't change the maintenance burden; the 3 files still diverge over time.
- **Alternative: switch the 3 schemas to a generic `PerTargetRow` + Pydantic v2 generics** — the 3 row types (`TargetDpsRow` + `TargetHealingRow` + `TargetBuffRemovalRow`) have IDENTICAL wire shape (`target_agent_id` + `total_X` + `count_X` + `rate` + `name`); the wire-format difference is purely the field-name slug (DPS / Healing / BuffRemoval). Pydantic v2 generics (`Generic[TTotal, TRate]`) might consolidate the schemas too — but the schemas are PUBLIC API (consumed by `apps/api/src/gw2analytics_api/schemas.py`'s Pydantic mirror + by the frontend's TypeScript client via `pnpm generate:api`). Changing the schema names breaks the wire contract. The plan keeps the 3 PUBLIC row types unchanged.

## Effort

`S` — 1 NEW base module + 3 file edits (~120 lines deleted from each of 3 files, ~50 lines added back per file = ~210 lines net removed across the 3 files) + 1 NEW test file (8 hermetic tests). The refactor is INTERNAL (no public API change); the 3 existing test files (`test_target_dps.py` + `test_target_healing.py` + `test_target_buff_removal.py`) unchanged — the post-refactor output is identical to the pre-refactor output. Independent of plans 083 + 085.
