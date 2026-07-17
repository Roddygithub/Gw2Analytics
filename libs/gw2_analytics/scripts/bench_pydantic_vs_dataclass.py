"""Benchmark: Pydantic vs dataclass vs dict for timeline row shapes.

Run with ``uv run python libs/gw2_analytics/scripts/bench_pydantic_vs_dataclass.py``.

This script is a proof-of-concept to quantify whether replacing
Pydantic models with dataclasses (or plain dicts) in the hot path
of timeline aggregators is worth the migration cost.
"""

from __future__ import annotations

import timeit
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PydanticRow(BaseModel):
    """Mirror of PerFightTimelineRow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start_ms: int = Field(..., ge=0)
    window_end_ms: int = Field(..., ge=0)
    total_damage: int = Field(default=0, ge=0)
    total_healing: int = Field(default=0, ge=0)
    total_buff_removal: int = Field(default=0, ge=0)


@dataclass(frozen=True, slots=True)
class DataclassRow:
    """Dataclass equivalent of PydanticRow."""

    window_start_ms: int
    window_end_ms: int
    total_damage: int = 0
    total_healing: int = 0
    total_buff_removal: int = 0


def _bench(name: str, stmt: Callable[[], Any], *, number: int = 10) -> float:
    total = timeit.timeit(stmt, number=number)
    best = total / number * 1000.0
    print(f"  {name}: {best:.3f} ms (best of {number})")
    return best


def _convert_dataclass_to_pydantic(rows: list[DataclassRow]) -> list[PydanticRow]:
    """Simulate the boundary conversion dataclass -> Pydantic schema."""
    return [
        PydanticRow(
            window_start_ms=r.window_start_ms,
            window_end_ms=r.window_end_ms,
            total_damage=r.total_damage,
            total_healing=r.total_healing,
            total_buff_removal=r.total_buff_removal,
        )
        for r in rows
    ]


def main() -> None:
    counts = [1_000, 10_000, 100_000]
    for count in counts:
        print(f"\n=== {count} rows ===")

        def _pydantic_rows(c: int = count) -> list[PydanticRow]:
            return [
                PydanticRow(
                    window_start_ms=i * 5000,
                    window_end_ms=(i + 1) * 5000,
                    total_damage=i,
                    total_healing=i,
                    total_buff_removal=i,
                )
                for i in range(c)
            ]

        def _dataclass_rows(c: int = count) -> list[DataclassRow]:
            return [
                DataclassRow(
                    window_start_ms=i * 5000,
                    window_end_ms=(i + 1) * 5000,
                    total_damage=i,
                    total_healing=i,
                    total_buff_removal=i,
                )
                for i in range(c)
            ]

        def _dict_rows(c: int = count) -> list[dict[str, int]]:
            return [
                {
                    "window_start_ms": i * 5000,
                    "window_end_ms": (i + 1) * 5000,
                    "total_damage": i,
                    "total_healing": i,
                    "total_buff_removal": i,
                }
                for i in range(c)
            ]

        _bench("Pydantic __init__", _pydantic_rows)
        _bench("dataclass", _dataclass_rows)
        _bench("plain dict", _dict_rows)

        # Pipeline: dataclass creation + conversion to Pydantic.
        # This is the realistic cost if we keep Pydantic at the API boundary.
        def _dataclass_pipeline(c: int = count) -> list[PydanticRow]:
            return _convert_dataclass_to_pydantic(_dataclass_rows(c))

        _bench("dataclass + convert to Pydantic", _dataclass_pipeline)


if __name__ == "__main__":
    main()
