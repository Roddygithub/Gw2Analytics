"""Position analysis: stack distance and distance to center of mass.

v0.11.0 Phase C: computes ``stack_dist`` (average distance from one
player to all other players at synchronised time points) and
``dist_to_com`` (distance from one player to the group's center of
mass). These metrics help analysts evaluate squad positioning
cohesion and identify overextended players.

Input
=====
A dict mapping ``account_name`` to a list of ``[time_ms, x, y]``
samples. The samples are already downsampled to 1 per 500ms (max
2000 per player) by the persistence layer.

Algorithm
=========
1. Collect the union of all time points across all players (the
   ``time_ms`` values from every sample).
2. At each unique time point, interpolate each player's position
   using the nearest-sample-before-time rule (no extrapolation).
3. At each time point, compute the center of mass (mean x, mean y)
   of all players who have a position at that time.
4. For each player:
   - ``stack_dist`` = average Euclidean distance to all OTHER
     players at synchronised time points.
   - ``dist_to_com`` = average Euclidean distance to the center of
     mass over all time points where the player has a position.

Edge cases
==========
- Single-player data: ``stack_dist`` is undefined (distance to
  oneself is 0). We return ``stack_dist=None``.
- No data: both metrics are ``None``.
- Sparse time alignment: a player with very few samples relative
  to the group's total time points has fewer distance measurements;
  the metric is still the average over its own time points.
"""

from __future__ import annotations

import math

PositionMap = dict[float, tuple[float, float]]


def _build_position_map(
    samples: list[list[float]],
    sorted_times: list[float],
) -> PositionMap:
    """Build a per-player position lookup using nearest-sample-before-time.

    For each time point in ``sorted_times``, finds the position sample
    with the largest ``time_ms`` <= ``t`` (no extrapolation). Returns an
    empty dict when no samples precede any time point.
    """
    pos_map: PositionMap = {}
    sorted_s = sorted(samples, key=lambda s: s[0])
    sample_idx = 0
    for t in sorted_times:
        while sample_idx < len(sorted_s) - 1 and sorted_s[sample_idx + 1][0] <= t:
            sample_idx += 1
        if sample_idx < len(sorted_s) and sorted_s[sample_idx][0] <= t:
            pos_map[t] = (sorted_s[sample_idx][1], sorted_s[sample_idx][2])
    return pos_map


def _collect_union_times(
    player_samples: dict[str, list[list[float]]],
) -> set[float]:
    """Collect the union of all ``time_ms`` values across all players."""
    all_times: set[float] = set()
    for samples in player_samples.values():
        for s in samples:
            all_times.add(s[0])
    return all_times


def _compute_metrics_at_time(
    t: float,
    player_positions: dict[str, PositionMap],
    player_stack_dists: dict[str, list[float]],
    player_com_dists: dict[str, list[float]],
) -> None:
    """At one time point, compute the center of mass and per-player distances.

    Updates ``player_stack_dists`` and ``player_com_dists`` in-place.
    Skips time points with fewer than 2 active players (stack_dist needs
    at least 2 players).
    """
    active: dict[str, tuple[float, float]] = {
        name: pos_map[t] for name, pos_map in player_positions.items() if t in pos_map
    }
    if len(active) < 2:
        return

    com_x = sum(x for x, _ in active.values()) / len(active)
    com_y = sum(y for _, y in active.values()) / len(active)

    for name, (px, py) in active.items():
        player_com_dists[name].append(math.hypot(px - com_x, py - com_y))
        other_dists = [
            math.hypot(px - ox, py - oy)
            for other_name, (ox, oy) in active.items()
            if other_name != name
        ]
        if other_dists:
            player_stack_dists[name].append(sum(other_dists) / len(other_dists))


def compute_position_metrics(
    player_samples: dict[str, list[list[float]]],
) -> dict[str, dict[str, float | None]]:
    """Compute ``stack_dist`` and ``dist_to_com`` for each player.

    Args:
        player_samples: ``{account_name: [[time_ms, x, y], ...]}``.

    Returns:
        ``{account_name: {"stack_dist": float | None, "dist_to_com": float | None}}``.
        ``stack_dist`` is ``None`` for single-player data (distance to
        oneself is meaningless). ``dist_to_com`` is ``None`` when the
        player has no position data.
    """
    if not player_samples:
        return {}

    all_times = _collect_union_times(player_samples)
    if not all_times:
        return {name: {"stack_dist": None, "dist_to_com": None} for name in player_samples}

    sorted_times = sorted(all_times)

    player_positions: dict[str, PositionMap] = {
        name: _build_position_map(samples, sorted_times) for name, samples in player_samples.items()
    }

    player_stack_dists: dict[str, list[float]] = {name: [] for name in player_samples}
    player_com_dists: dict[str, list[float]] = {name: [] for name in player_samples}

    for t in sorted_times:
        _compute_metrics_at_time(t, player_positions, player_stack_dists, player_com_dists)

    return {
        name: {
            "stack_dist": (sum(player_stack_dists[name]) / len(player_stack_dists[name]))
            if player_stack_dists[name]
            else None,
            "dist_to_com": (sum(player_com_dists[name]) / len(player_com_dists[name]))
            if player_com_dists[name]
            else None,
        }
        for name in player_samples
    }


__all__ = ["compute_position_metrics"]
