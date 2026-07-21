# Plan 106 (v0.9.34) — `health_gate.py` baseline-shape validation + `MAX_DRIFT_DELTA` CLI flag

## Files touched
- `apps/api/src/gw2analytics_api/scripts/health_gate.py` (1 NEW helper `_validate_drift_shape(data, source=...) -> None` raising on shape mismatch + argparse update for `--max-drift-delta` + replacement of hardcoded constant with the CLI arg)
- `apps/api/tests/scripts/test_health_gate.py` (NEW — 5 hermetic tests covering the baseline-shape validation + the new CLI flag)

## Findings (audit)

- `apps/api/src/gw2analytics_api/scripts/health_gate.py::_check_delta` reads `baseline["drift_count"]` directly (line ~92) without validating the baseline file shape. If a future schema change to `SummaryDrift` renames or removes `drift_count`, the gate fails with an opaque `KeyError` or `TypeError` at CI time — no clear "baseline format is stale" message.
- The script is operational-CI critical (per the docstring at line 14: "**CI gate** that closes the loop"). An opaque Python traceback in the CI workflow log is hard to triage; an explicit "baseline file does not contain required field `drift_count`; please re-capture with `{script_name} --save-baseline PATH` after upgrading" message would surface the failure cleanly.
- A second finding: `MAX_DRIFT_DELTA = 2` is a hardcoded module-level `Final[int]` constant. The inline comment explains the rationale (e2e suite legitimately adds up to 2 fights of drift). But the budget is operator-specific: a different test corpus, a different staging pipeline, or a future expansion of the e2e suite could legitimately produce drift count > 2 without indicating a regression. The operator has NO way to tune the budget without editing the source — not a CLI option. The source-edit path is incompatible with CI workflows that pin the script via `python -m` without edits.
- Today's default-2 budget failure surface: an operator sees `CI gate FAILED: drift_count delta=3 >= max=2` and MUST edit the source to tune. The CI workflow's only fix path is to fork the script. Adding a `--max-drift-delta N` CLI flag is the canonical fix (the budget moves from "constant in source" to "flag in invocation").

## Fix

1. `apps/api/src/gw2analytics_api/scripts/health_gate.py` — replace `_check_delta(path)` signature:

   ```python
   def _validate_drift_shape(data: object, *, source: str) -> None:
       """Raise :class:`ValueError` if ``data`` is not the canonical :class:`SummaryDrift` shape.

       ``source`` is the label printed in the error message (e.g.
       ``"baseline file"`` vs ``"live probe response"``) so a
       failed shape lookup is traceable to its origin without
       pdb debugging.
       """
       if not isinstance(data, dict):
           raise ValueError(
               f"{source}: expected a JSON object (the canonical "
               f"SumaryDrift shape), got {type(data).__name__}"
           )
       # ``drift_count`` is the canonical sentinel for shape
       # regressions (a rename or removal of THIS field is
       # what triggered the v2.x reshape documented in design
       # doc §6.3). Future reshapes that add NEW fields
       # (``drift_pct_v2`` / ``drift_count_v2``) would NOT
       # fail this check (the new fields would simply be
       # ignored downstream).
       required = ("drift_count",)
       for key in required:
           if key not in data:
               raise ValueError(
                   f"{source}: required field {key!r} missing. "
                   f"Re-capture with `python -m "
                   f"gw2analytics_api.scripts.health_gate "
                   f"--save-baseline {source}` after upgrading."
               )
           if not isinstance(data[key], int):
               raise ValueError(
                   f"{source}: required field {key!r} must be "
                   f"an integer, got {type(data[key]).__name__}"
               )
   ```

2. Replace `_check_delta(path)` body to call the validator:

   ```python
   def _check_delta(path: str, max_drift_delta: int = MAX_DRIFT_DELTA) -> int:
       """Compare the current probe response to the baseline at ``path``.

       The :func:`_validate_drift_shape` guard catches baseline
       files written to the WRONG shape (e.g. a stale schema
       or a CORRUPT save) before the arithmetic would otherwise
       crash with a bare :class:`KeyError`.

       Returns 0 on pass, 1 on fail.
       """
       data = _fetch_drift()
       print(f"Health probe post-e2e: {data}")
       _validate_drift_shape(data, source="live probe response")

       with Path(path).open() as f:
           baseline = json.load(f)
       _validate_drift_shape(baseline, source=f"baseline file ({path})")

       print(f"Health probe baseline: {baseline}")

       delta = data["drift_count"] - baseline["drift_count"]
       if delta >= max_drift_delta:
           print(
               f"CI gate FAILED: drift_count delta={delta} "
               f">= max={max_drift_delta} "
               f"(baseline_drift_count={baseline['drift_count']}, "
               f"post_drift_count={data['drift_count']})",
           )
           return 1

       print(
           f"CI gate OK: drift_count delta={delta} < max={max_drift_delta}",
       )
       return 0
   ```

3. Update `main()` to accept the new flag:

   ```python
   def main() -> int:
       parser = argparse.ArgumentParser(
           description=__doc__.split("\n", 1)[0],
       )
       # ... existing flags ...
       parser.add_argument(
           "--max-drift-delta",
           type=int,
           default=MAX_DRIFT_DELTA,
           help=(
               "Maximum tolerated ``drift_count`` delta between "
               "the baseline and the post-e2e probe response. "
               "Default = 2 (matches the canonical e2e suite "
               "expectation). Operators can tune via this flag "
               "without editing the source -- "
               "useful for staging-vs-prod drift budgets."
           ),
       )
       # ...
       if args.save_baseline:
           return _save_baseline(args.save_baseline)
       if args.check_delta:
           return _check_delta(args.check_delta, max_drift_delta=args.max_drift_delta)
       # ... debug mode branch ...
   ```

4. `MAX_DRIFT_DELTA = 2` constant is RETAINED as the DEFAULTS for `--max-drift-delta`. The constant is no longer the single source of truth (the CLI arg is); it's the default-value anchor.

## Tests (5, NEW file `apps/api/tests/scripts/test_health_gate.py`)

- `test_validate_drift_shape_passes_canonical_summary_drift` — `_validate_drift_shape({"drift_count": 5}, source="test")` does NOT raise. Confirms the canonical shape is accepted.
- `test_validate_drift_shape_raises_when_drift_count_missing` — `_validate_drift_shape({}, source="test")` raises `ValueError` whose message contains `"required field 'drift_count' missing"`.
- `test_validate_drift_shape_raises_when_drift_count_wrong_type` — `_validate_drift_shape({"drift_count": "string"}, source="test")` raises `ValueError` whose message contains `"must be an integer"`.
- `test_check_delta_uses_cli_max_drift_delta_flag` — invoke `_check_delta` via `main()` with `--check-delta ... --max-drift-delta 99`; capture the printed `CI gate OK:` line; assert `max=99` appears. Defensive: confirms the flag is wired all the way through the call chain.
- `test_check_delta_returns_1_when_baseline_shape_malformed` — write a JSON file `{path: "valid-looking-but-wrong-shape"}` containing `{"some_other_field": 5}` (no `drift_count`); invoke `main` with `--check-delta {path}`; assert `returncode != 0` AND stderr (or stdout) contains `"required field 'drift_count' missing"`.

## Rejected alternatives

- **Use Pydantic v2 `SummaryDrift.model_validate(baseline)` for shape validation** — the `SummaryDrift` typed is currently a TypedDict (a static-only annotation, NOT a runtime validator). Pydantic-validating would require promoting `SummaryDrift` to a Pydantic BaseModel, a cross-module change to `gw2analytics_api.health`. The minimal-fix shape check (3 lines) is the right scoped fix. REJECTED.
- **Drop the `MAX_DRIFT_DELTA` constant entirely; require the CLI flag** — breaks the canonical-script invocation `python -m gw2analytics_api.scripts.health_gate --check-delta PATH` (no `--max-drift-delta` set). The constant-as-default pattern preserves the canonical invocation while enabling operator tuning. REJECTED.
- **Move the budget to a `.env` / config file** — operators tune via env vars is fine for app config, but the CI gate's budget is a workflow-specific number (it's tied to the e2e suite's legitimate drift budget, not to the app's configuration). CLI flag is the right surface. REJECTED.
- **Use a single `--tolerance` flag with units** — overengineering for one tunable knob. `--max-drift-delta` (an integer count) is the simplest CLI surface. REJECTED.
- **Drop shape validation entirely (rely on the future author's discipline)** — leaves the opaque-KeyError footgun in place. The 6-line validator is minimal. REJECTED.

## Dependency graph

- Independent: touches `health_gate.py` only + NEW test file.
- Parallel-safe with plans 104 / 105.
- Pattern-aligns with `apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py` (which already uses `argparse` for `--limit` + `--dry-run` + `--fight-id` + `--log-level` — the same CLI-flag ergonomics).
- The shape validator is the canonical FastAPI `model_validate()` "Lite" pattern for scripts that EITHER can't import the Pydantic model OR want to fail fast without a heavy dependency on `gw2_analytics_api.health` import. The script stays hermetic.
