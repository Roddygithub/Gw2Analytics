"""arcdps_healing_stats sidecar loader (v0.10.5 plan 136).

The arcdps_healing_stats addon emits a sibling JSON next to the
.zevtc containing per-skill heal/barrier breakdowns not carried in
the binary event stream. This module probes for that sidecar in
three places:

1. Inline JSON inside the .zevtc archive.
2. Sibling file alongside the .zevtc.
3. None (addon is opt-in).

The merge contract updates summary.healing_by_skill only; it does
NOT touch summary.healing totals (native CBTR_HEAL events are the
canonical heal totals).
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

#: Suffixes probed for the sidecar, in priority order.
SIDECAR_SUFFIXES = (".healing.json", "_healing.json", ".json")

#: Diagnostic counters used by calibration runs.
_sidecar_load_attempts = 0
_sidecar_load_failures = 0
_skipped_unresolvable_heals = 0


def _reset_counters() -> None:
    """Reset all diagnostic counters. Exposed for test isolation."""
    global _sidecar_load_attempts, _sidecar_load_failures, _skipped_unresolvable_heals  # noqa: PLW0603
    _sidecar_load_attempts = 0
    _sidecar_load_failures = 0
    _skipped_unresolvable_heals = 0


def probe(zevtc_path: Path | str) -> dict[str, Any] | None:
    """Probe for an arcdps_healing_stats sidecar for the given .zevtc.

    Parameters
    ----------
    zevtc_path:
        Path to the .zevtc file.

    Returns
    -------
    The parsed sidecar JSON as a dict, or None if no sidecar is found.
    """
    global _sidecar_load_attempts, _sidecar_load_failures  # noqa: PLW0603
    _sidecar_load_attempts += 1

    path = Path(zevtc_path)
    sidecar = _probe_inline(path) or _probe_sibling(path)

    if sidecar is None:
        return None

    try:
        _validate_sidecar(sidecar)
    except (ValueError, TypeError) as exc:
        _sidecar_load_failures += 1
        logger.warning("sidecar validation failed for %s: %s", path, exc)
        return None

    return sidecar


def _probe_inline(path: Path) -> dict[str, Any] | None:
    """Probe inside the .zevtc zip archive for a JSON sidecar."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.lower().endswith(".json"):
                    try:
                        data = zf.read(name)
                        return cast("dict[str, Any] | None", json.loads(data))
                    except (json.JSONDecodeError, OSError, ValueError):
                        continue
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def _probe_sibling(path: Path) -> dict[str, Any] | None:
    """Probe for a sibling sidecar file next to the .zevtc."""
    base = path.stem
    parent = path.parent
    for suffix in SIDECAR_SUFFIXES:
        candidate = parent / f"{base}{suffix}"
        try:
            with candidate.open("rb") as fh:
                data = fh.read()
            return cast("dict[str, Any] | None", json.loads(data))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return None


def _validate_sidecar(sidecar: dict[str, Any]) -> None:
    """Validate the top-level shape of the sidecar JSON.

    Raises ValueError if the sidecar is not a dict or lacks the
    expected players key.
    """
    if not isinstance(sidecar, dict):
        raise ValueError("sidecar must be a JSON object")
    if "players" not in sidecar:
        raise ValueError("sidecar missing 'players' key")


def _lookup_player(players: dict[str, Any], account: str) -> Any | None:
    """Find player data by account name, case-insensitively."""
    if account in players:
        return players[account]
    account_lower = account.lower()
    for key, value in players.items():
        if key.lower() == account_lower:
            return value
    return None


def _merge_skill_map(
    summary: Any,
    attr: str,
    player_data: dict[str, Any],
    key_name: str,
) -> None:
    """Merge one sidecar per-skill map into a summary attribute.

    Updates ``summary.<attr>`` for entries matching ``player_data[key_name]``.
    Values are accumulated by stringified skill id.
    """
    global _skipped_unresolvable_heals  # noqa: PLW0603
    skill_map = player_data.get(key_name, {})
    if not isinstance(skill_map, dict):
        _skipped_unresolvable_heals += 1
        return

    existing = getattr(summary, attr, None) or {}
    if not isinstance(existing, dict):
        existing = {}

    updated: dict[str, int] = {str(k): int(v) for k, v in existing.items()}
    for skill_id, amount in skill_map.items():
        try:
            amount_int = int(amount)
        except (TypeError, ValueError):
            _skipped_unresolvable_heals += 1
            continue
        key = str(skill_id)
        updated[key] = updated.get(key, 0) + amount_int

    setattr(summary, attr, updated)


def merge_sidecar_into_summary(
    summary: Any,
    sidecar: dict[str, Any],
) -> None:
    """Merge sidecar per-skill heal/barrier data into a summary row.

    Updates ``summary.healing_by_skill`` and ``summary.barrier_by_skill``
    for entries matching ``summary.account_name`` (case-insensitive).
    Does NOT touch ``summary.healing`` totals.
    """
    global _skipped_unresolvable_heals  # noqa: PLW0603
    account = getattr(summary, "account_name", None)
    if account is None:
        _skipped_unresolvable_heals += 1
        return

    players = sidecar.get("players", {})
    if not isinstance(players, dict):
        _skipped_unresolvable_heals += 1
        return

    player_data = _lookup_player(players, account)
    if player_data is None:
        _skipped_unresolvable_heals += 1
        return

    _merge_skill_map(summary, "healing_by_skill", player_data, "healingBySkill")
    _merge_skill_map(summary, "barrier_by_skill", player_data, "barrierBySkill")


__all__ = [
    "SIDECAR_SUFFIXES",
    "merge_sidecar_into_summary",
    "probe",
]
