"""Micro-benchmark: Pydantic __init__ vs model_construct.

Run with ``uv run python libs/gw2_analytics/scripts/bench_model_construct.py``.
"""

from __future__ import annotations

import timeit
from collections.abc import Callable
from typing import Any

from gw2_analytics.per_fight_timeline import PerFightTimelineRow
from gw2_analytics.per_player_timeline import PerPlayerTimelinePoint


def _bench(name: str, stmt: Callable[[], Any], *, number: int = 100) -> float:
    total = timeit.timeit(stmt, number=number)
    best = total / number * 1000.0
    print(f"  {name}: {best:.3f} ms (best of {number})")
    return best


def main() -> None:
    count = 100_000

    print(f"\n=== PerFightTimelineRow x {count} ===")
    _bench(
        "__init__",
        lambda: [
            PerFightTimelineRow(
                window_start_ms=i * 5000,
                window_end_ms=(i + 1) * 5000,
                total_damage=i,
                total_healing=i,
                total_buff_removal=i,
            )
            for i in range(count)
        ],
    )
    _bench(
        "model_construct",
        lambda: [
            PerFightTimelineRow.model_construct(
                window_start_ms=i * 5000,
                window_end_ms=(i + 1) * 5000,
                total_damage=i,
                total_healing=i,
                total_buff_removal=i,
            )
            for i in range(count)
        ],
    )

    print(f"\n=== PerPlayerTimelinePoint x {count} ===")
    _bench(
        "__init__",
        lambda: [
            PerPlayerTimelinePoint(
                window_start_ms=i * 5000,
                window_end_ms=(i + 1) * 5000,
                total_damage=i,
                total_healing=i,
                total_buff_removal=i,
            )
            for i in range(count)
        ],
    )
    _bench(
        "model_construct",
        lambda: [
            PerPlayerTimelinePoint.model_construct(
                window_start_ms=i * 5000,
                window_end_ms=(i + 1) * 5000,
                total_damage=i,
                total_healing=i,
                total_buff_removal=i,
            )
            for i in range(count)
        ],
    )


if __name__ == "__main__":
    main()
