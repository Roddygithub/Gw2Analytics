# Plan 002 — Fix `typing.Any` leak in `cross_account_timeline.py`

- **Slug:** `002-fix-typing-any-leakage-analytics`
- **Priority:** P2
- **Effort:** XS (~5 minutes)
- **Risk:** Low (single-function signature tightening)
- **Confidence:** 1.0
- **Status:** open

## Why

`libs/gw2_analytics/src/gw2_analytics/cross_account_timeline.py:276` declares:

```python
def _combine_day_midnight(started_at: Any, tz: ZoneInfo) -> Any:
    ...
```

In a codebase governed by `mypy.ini --strict` + a workspace-aware pre-commit mypy hook (per `.pre-commit-config.yaml`), this `Any` annotation is a silent bypass of the strict-mode contract. The function's actual behaviour receives a timezone-aware `datetime` and returns a timezone-aware `datetime` (midnight in the requested tz, then serialised back to UTC on the wire).

The annotation pretends either argument could be anything, undermining the per-fight-bucket `started_at` invariant the analytics layer relies on for day-bucketing correctness.

## Scope

**In scope:** `libs/gw2_analytics/src/gw2_analytics/cross_account_timeline.py` line 276 (function signature) + the 2–3 in-file call-sites of `_combine_day_midnight`.

**Out of scope:** Other analytics modules (`event_window.py`, `per_fight_timeline.py`, `per_player_timeline.py`, `role_detection.py`, etc.). This is a contained, fixable-in-isolation 1-function change.

## Files to reference

- `libs/gw2_analytics/src/gw2_analytics/cross_account_timeline.py` — the file under edit.
- `libs/gw2_analytics/tests/test_cross_account_timeline.py` — existing 7 hermetic cases (must continue to pass).
- `mypy.ini` — project strict-mode policy.

## Steps

1. Read `cross_account_timeline.py` lines 270–290 (the function + its 2–3 call-sites). Confirm all call-sites pass `OrmFight.started_at` (which is `Mapped[datetime | None]`) — if a call-site passes `None`, that call-site needs a `None`-guard, not a wider type.

2. Add `from datetime import datetime` to the module imports (if not already present).

3. Replace `Any` with `datetime` on both the parameter and return annotation:

   ```python
   def _combine_day_midnight(started_at: datetime, tz: ZoneInfo) -> datetime:
       ...
   ```

4. Run the strict mypy + the cross-account test suite. Confirm no regression.

## Done criteria

```bash
# 1. Any leak removed from the function signature
grep -n 'Any' libs/gw2_analytics/src/gw2_analytics/cross_account_timeline.py  # no `Any` left in the function signature

# 2. Tests still pass
uv run pytest libs/gw2_analytics/tests/test_cross_account_timeline.py -v   # 7 passed

# 3. Strict mypy clean
uv run mypy --no-incremental libs/gw2_analytics/                            # MYPY=0

# 4. Public re-exports unchanged
git diff -- libs/gw2_analytics/src/gw2_analytics/__init__.py                # empty diff
```

## Maintenance note

If a future aggregates ever needs a `date`-only bucket, use `datetime` + `time.min` rather than re-introducing `Any`. Document the choice in a one-line inline comment.

## Escape hatch

If other `Any` leaks appear in the same module (verifiable by `grep -n 'Any' libs/gw2_analytics/src/gw2_analytics/cross_account_timeline.py`), STOP and plan a scope expansion rather than fixing them inline in this commit.
