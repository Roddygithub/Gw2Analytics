"""Shared invariant helpers for gw2_analytics aggregators.

These helpers are intentionally small and focused: they encode
contracts that appear in multiple aggregator modules (ordering,
sum conservation, etc.) without pulling in domain-specific types.
Keeping them in a private module (``_`` prefix) signals that they
are internal implementation details, not public API.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise


def check_desc_asc_ordering[T](
    rows: list[T],
    *,
    primary_key: Callable[[T], int | float],
    secondary_key: Callable[[T], int],
    primary_label: str,
    secondary_label: str,
) -> None:
    """Raise ``ValueError`` if ``rows`` is not sorted by ``(-primary, secondary)``.

    The canonical aggregator ordering is:

    - ``primary_key`` descending (highest first)
    - ``secondary_key`` ascending (ties broken by lowest ID)

    The labels are used only to build a human-readable error
    message when the invariant is violated.
    """
    for prev, curr in pairwise(rows):
        prev_primary = primary_key(prev)
        curr_primary = primary_key(curr)
        if prev_primary < curr_primary:
            msg = (
                f"rows not ordered by ({primary_label} DESC, "
                f"{secondary_label} ASC): {prev!r} then {curr!r}"
            )
            raise ValueError(msg)
        if prev_primary == curr_primary:
            prev_secondary = secondary_key(prev)
            curr_secondary = secondary_key(curr)
            if prev_secondary >= curr_secondary:
                msg = (
                    f"tie on {primary_label} not broken by "
                    f"{secondary_label} ASC: {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
