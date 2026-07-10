"""Shared base for the 3 per-target roll-up aggregators (DPS / HPS / BPS).

Why this module exists
======================

:mod:`gw2_analytics.target_dps`, :mod:`gw2_analytics.target_healing` and
:mod:`gw2_analytics.target_buff_removal` were byte-for-byte near-clones:
the accumulate-by-target loop, the per-second rate factor, the row
construction, the deterministic sort, and the cross-field invariant
checks were identical across the three files -- only four field-name
slugs differed (the event's value attribute, the row's total field, the
row's count field, and the row's rate field). Plan 084 factors that
shared body into one generic :class:`PerTargetRollupBase` and reduces the
three modules to their public row schema + a thin config-injecting
subclass.

The refactor is INTERNAL: the three public ``Target*Aggregator`` classes
keep their names and the ``aggregate(events, duration_s, name_map=None)``
signature, and the three public ``Target*Row`` schemas keep their field
names, so the wire contract consumed by
``apps/api/src/gw2analytics_api`` and the generated web client is
unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

from pydantic import BaseModel

# Every per-target row is keyed on ``target_agent_id``. Kept as a
# module constant so the base reads it via variable ``getattr`` (uniform
# with the spec-driven field access; avoids the ruff B009 literal-getattr
# rule and the mypy "BaseModel has no attribute" error that direct
# attribute access on the generic ``TRow`` would trip).
_TARGET_FIELD = "target_agent_id"

# Rate sentinel when ``duration_s <= 0``: an invalid (zero/negative)
# duration collapses the per-second rate to 0.0 rather than raising. The
# canonical event stream from the parser always pairs with a known fight
# duration, so the zero path is purely defensive (mirrors the historical
# ``_DEFAULT_DPS`` / ``_DEFAULT_HPS`` / ``_DEFAULT_BPS`` sentinels).
_DEFAULT_RATE = 0.0


@dataclass(frozen=True, slots=True)
class PerTargetRollupSpec:
    """The four field-name slugs that distinguish the 3 per-target rollups.

    Every other part of the aggregation (accumulate-by-target, rate
    factor, sort, invariants) is identical across DPS / HPS / BPS, so the
    spec is the whole per-subclass surface.
    """

    event_attr: str
    """Event value attribute: ``damage`` / ``healing`` / ``buff_removal``."""
    total_field: str
    """Row total field: ``total_damage`` / ``total_healing`` / ``total_buff_removal``."""
    count_field: str
    """Row event-count field: ``attack_count`` / ``heal_count`` / ``strip_count``."""
    rate_field: str
    """Row per-second rate field: ``dps`` / ``hps`` / ``bps``."""


class PerTargetRollupBase[TEvent, TRow: BaseModel]:
    """Stateless per-target roll-up aggregator, parameterised by config.

    Not instantiated directly: each concrete aggregator subclass passes a
    :class:`PerTargetRollupSpec` + its row class to ``super().__init__``.
    Instances hold no per-call state and are safe to reuse.
    """

    def __init__(self, spec: PerTargetRollupSpec, row_cls: type[TRow]) -> None:
        # Fail loud at construction if a spec slug does not name a real
        # field on ``row_cls``. Row construction is dynamic
        # (``row_cls(**{spec.total_field: ...})``), so mypy no longer
        # catches a typo'd slug; without this guard a broken spec would
        # only surface on the first NON-empty aggregate (empty input
        # constructs zero rows and never exercises the slugs). Checking
        # here restores the author-time guarantee for any input size.
        # ``event_attr`` lives on the event, not the row, so it is
        # verified at first use (``AttributeError``) rather than here.
        required_row_fields = {
            _TARGET_FIELD,
            "name",
            spec.total_field,
            spec.count_field,
            spec.rate_field,
        }
        missing = required_row_fields - set(row_cls.model_fields)
        if missing:
            msg = (
                f"{row_cls.__name__} is missing spec field(s) "
                f"{sorted(missing)}; check the PerTargetRollupSpec slugs"
            )
            raise ValueError(msg)
        self._spec = spec
        self._row_cls = row_cls

    def aggregate(
        self,
        events: Iterable[TEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
    ) -> list[TRow]:
        """Compute the per-target roll-up from a stream of events.

        ``duration_s`` is the fight duration the per-second rate is
        measured against (passed by the caller so the aggregator stays
        free of cross-source metadata). ``name_map`` is an OPTIONAL
        ``{agent_id: name}`` lookup for player-name denormalisation;
        ``None`` (the default) or an empty dict leaves every row's
        ``name`` as ``None``. Agents absent from the map resolve to
        ``None`` (NPCs without a registered arcdps char-name), which the
        route surfaces as ``null`` on the wire.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        total_by_target: dict[int, int] = defaultdict(int)
        count_by_target: dict[int, int] = defaultdict(int)
        grand_total = 0
        for e in events:
            value: int = getattr(e, self._spec.event_attr)
            target_agent_id: int = getattr(e, _TARGET_FIELD)
            total_by_target[target_agent_id] += value
            count_by_target[target_agent_id] += 1
            grand_total += value

        rate_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_RATE
        # ``(name_map or {}).get(target)`` returns ``None`` for missing
        # keys AND for explicit ``None`` values -- both surface as the
        # ``name=None`` "unresolved" sentinel on the row.
        resolved = name_map or {}
        rows: list[TRow] = [
            self._row_cls(
                **{
                    "target_agent_id": target,
                    self._spec.total_field: total_by_target[target],
                    self._spec.count_field: count_by_target[target],
                    self._spec.rate_field: total_by_target[target] * rate_factor,
                    "name": resolved.get(target),
                }
            )
            for target in total_by_target
        ]
        # Sort: highest total first; ties broken by ascending target_agent_id.
        rows.sort(
            key=lambda r: (
                -getattr(r, self._spec.total_field),
                getattr(r, _TARGET_FIELD),
            )
        )

        self._check_invariants(rows, grand_total)
        return rows

    def _check_invariants(self, rows: list[TRow], expected_sum: int) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        Reads the total/count field names from the injected spec so the
        checks are identical across the three subclasses:

        - Sum of ``row.<total_field>`` == sum of the event value attribute
          (no event dropped, no double-counting).
        - Every row's ``<count_field>`` is ``>= 1``.
        - Rows are monotonically non-increasing by ``<total_field>``;
          ties broken by ascending ``target_agent_id``.
        """
        total_field = self._spec.total_field
        count_field = self._spec.count_field

        actual_sum = sum(getattr(r, total_field) for r in rows)
        if actual_sum != expected_sum:
            msg = (
                f"sum of row.{total_field} ({actual_sum}) != "
                f"sum of event.{self._spec.event_attr} ({expected_sum})"
            )
            raise ValueError(msg)
        for r in rows:
            if getattr(r, count_field) < 1:
                msg = (
                    f"{self._row_cls.__name__}({getattr(r, _TARGET_FIELD)})."
                    f"{count_field} ({getattr(r, count_field)}) must be >= 1"
                )
                raise ValueError(msg)
        # Pydantic field constraints already guarantee ``ge=0`` for the
        # total; the cross-row ordering invariant is the only ordering
        # contract. ``pairwise`` pairs each row with its immediate
        # successor (canonical adjacent-pair idiom, ruff RUF007).
        for prev, curr in pairwise(rows):
            prev_total = getattr(prev, total_field)
            curr_total = getattr(curr, total_field)
            if prev_total < curr_total:
                msg = (
                    f"rows not ordered by ({total_field} DESC, "
                    f"target_agent_id ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if prev_total == curr_total and (
                getattr(prev, _TARGET_FIELD) >= getattr(curr, _TARGET_FIELD)
            ):
                msg = (
                    f"tie on {total_field} not broken by "
                    f"target_agent_id ASC: {prev!r} then {curr!r}"
                )
                raise ValueError(msg)


__all__ = ["PerTargetRollupBase", "PerTargetRollupSpec"]
