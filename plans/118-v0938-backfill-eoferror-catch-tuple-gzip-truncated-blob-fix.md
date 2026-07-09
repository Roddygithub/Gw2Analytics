# Plan 118 (v0.9.38) — `backfill.py::run_backfill` exception tuple gap: `EOFError` from truncated gzipped blobs aborts the loop instead of counting as `failed: 1`

## Files touched
- `apps/api/src/gw2analytics_api/backfill.py` (extend the `except (S3Error, OSError, SQLAlchemyError, ValidationError)` clause to ALSO catch `EOFError` raised by `gzip.decompress` on truncated input; collapse the duplicated `assert agent.account_name is not None # noqa: S101 # narrowed by the caller's filter` comment block in `_backfill_pre_phase7`)
- `apps/api/tests/test_backfill.py` (NEW — 5 hermetic tests pinning the truncated-blob + comment-block invariants)

## Findings (audit)

- `apps/api/src/gw2analytics_api/backfill.py::run_backfill` line ~135 catches:
  ```python
  except (S3Error, OSError, SQLAlchemyError, ValidationError) as exc:
  ```
- This catch tuple is narrow but DOES NOT include `EOFError`. Yet `gzip.decompress(gz_bytes)` on a truncated input raises `EOFError` (CPython's `_GzipDecompress.decompress` raises `EOFError("Compressed file ended before the end-of-stream marker was reached")` on a mid-stream truncation). This is a real bug surface:
  - Scenario: a partially-uploaded `.zevtc` was uploaded during network instability; MinIO persisted the partial blob; a queue retry sees the partial blob on backfill.
  - Today: the `gzip.decompress` raises `EOFError` → not caught → propagates up → `run_backfill` aborts the entire loop → **operator sees a stacktrace, not a `failed: 1` count + continue**.
  - Expected per the function's docstring: per-fight failure is supposed to be `try/except` + `failed += 1` + `continue`.
- The same gap exists on `routes/players.py::_contributions_from_blob_walk` (line ~163) and `routes/fights.py::_load_fight_events` (the `try/except OSError` for gzip decode). The latter raises `HTTPException(502, "events blob corrupt")` on the `OSError` path — but `EOFError` would propagate to FastAPI's default error handler (a 500 Internal Server Error rather than the canonical 502 for "blob corrupt"). A future fix should close the same gap in those surfaces; this plan closes the highest-impact first (the backfill, since it processes batches and a single truncation currently aborts ALL queued fights).
- A **second** hygiene finding in the same file: `_backfill_pre_phase7` (line ~195) has an `assert agent.account_name is not None  # noqa: S101  # narrowed by the caller's filter` line. The comment block immediately above it ALSO ends with the same exact `# narrowed by the caller's filter` phrase — so on a re-read the comment block appears to contain the assert twice. This is a pure readability cost: a future maintainer wonders "is this the first or second assert?". The fix is to collapse the explanatory comment block to a single canonical sentence + let the assert + noqa speak for themselves.
- Why the `EOFError` finding matters most right now:
  - The backfill's design contract (from the function's docstring) is explicitly "per-fight failures are NOT propagated". A future operator who runs the backfill script in production + hits one truncated-blob fight would experience the entire backfill aborting on the first failure, requiring manual intervention to identify the first truncated-blob fight.
  - The v0.8.x documents the "O(fights x events) → O(rows)" performance migration (per the v0.8.4 design doc). Maintenance scripts that the backfill runs on CORRUPTED data are the most exposed to blameless-error scenarios.
  - The fix is a 1-token addition (`EOFError,`) to the catch tuple — 1 line of code, ~5 LoC of test.

## Fix

1. `apps/api/src/gw2analytics_api/backfill.py::run_backfill` line ~135:

   ```python
   except (S3Error, OSError, EOFError, SQLAlchemyError, ValidationError) as exc:
       # The 5 caught exception types are the per-fight failure
       # modes the backfill is designed to survive:
       #
       # - ``S3Error``: a single missing MinIO blob (the operator
       #   may have deleted the blob out-of-band or the
       #   pre-Phase-7 fight never had one). NOT a MinIO outage
       #   (which would be an operational concern, not a per-fight
       #   issue) -- the catch is narrow enough to let a real
       #   MinIO outage propagate (e.g. ``ConnectionError`` from
       #   the boto3 layer).
       # - ``OSError``: gzip decode errors on a corrupted blob
       #   (the gzip module raises ``OSError`` with
       #   ``errno.EIO`` on bad CRC + length).
       # - ``EOFError``: gzip decode errors on a TRUNCATED blob
       #   (the gzip module raises ``EOFError("Compressed file
       #   ended before the end-of-stream marker was reached")``
       #   when the stream cuts off mid-record). This is the
       #   network-instability-mid-upload case: MinIO persisted
       #   a partial blob, the backfill sees the partial blob,
       #   WITHOUT this catch tuple the EOFError would propagate
       #   + abort the entire loop. With it, the fight is
       #   counted as ``failed`` + the next fight is processed.
       # - ``SQLAlchemyError``: constraint violations, transient
       #   DB issues, etc.
       # - ``ValidationError``: a single malformed event line in
       #   the gzipped JSONL (e.g. a corrupted record). The
       #   ``TypeAdapter.validate_json`` callers raise this.
       #
       # Each of these is a per-fight issue -- the next fight
       # is processed. The script is re-runnable; a re-run
       # retries the failed fights (they still have zero
       # summary rows + their failures were transient or
       # out-of-band).
       logger.exception("failed backfilling fight %s: %s", fight.id, exc)
       db.rollback()
       failed += 1
       continue
   ```

2. `apps/api/src/gw2analytics_api/backfill.py::_backfill_pre_phase7` — collapse the duplicated `# narrowed by the caller's filter` comment block:

   - The original:
     ```python
     db.add(
         OrmFightPlayerSummary(
             ...,
             account_name=agent.account_name,
             ...
         ),
     )
     # ``agent.account_name`` is truthy (filtered by the
     # caller), so the cast to ``str`` is safe. The
     # ``agent.name or ""`` fallback matches the write
     # path's contract (the parser may surface an empty
     # char-name for synthetic agents).
     # ``agent.account_name`` is truthy (filtered by the
     # caller), so the cast to ``str`` is safe. The
     # ``agent.name or ""`` fallback matches the write
     # path's contract (the parser may surface an empty
     # char-name for synthetic agents). The ``assert`` is
     # type-narrowing only; ``# noqa: S101`` silences the
     # assert-detection lint (the codebase doesn't run
     # with ``python -O`` so the assert cannot be
     # optimised away in production).
     assert agent.account_name is not None  # noqa: S101  # narrowed by the caller's filter
     ```
   - The refactor:
     ```python
     # ``agent.account_name`` is truthy (filtered by the caller);
     # the cast to ``str`` is safe in that branch. The
     # ``agent.name or ""`` fallback matches the write path's
     # contract (the parser may surface an empty char-name for
     # synthetic agents). The ``assert`` below is type-narrowing
     # only; ``# noqa: S101`` silences the assert-detection
     # lint (the codebase doesn't run with ``python -O`` so the
     # assert cannot be optimised away in production).
     assert agent.account_name is not None  # noqa: S101  # narrowed by the caller's filter
     ```
   - The 3-line comment block becomes 1 comment-with-detail; the assert + noqa + trailing comment stay verbatim.
   - Wait — re-reading carefully, the duplication is one block-comment above the `db.add` + the same block-comment immediately above the `assert`. There is **only one** `assert agent.account_name is not None` statement in the function. The two comment blocks are below the `db.add` call. So the fix is to consolidate the two back-to-back `agent.account_name is truthy (filtered by the caller)` blocks into one canonical block. 8 comment lines → 1 ~7-line consolidated block.

3. Same `EOFError` catch extension applies transitively to `routes/players.py::_contributions_from_blob_walk` (post-refactor in Plan 116's hub). Plan 116 already closes it. This plan closes it for `backfill.py`.

## Tests (5, NEW `apps/api/tests/test_backfill_eof_catch.py`)

Hermetic tests pinning the new catch + the comment-block dedup:

- `test_run_backfill_catches_eoferror_on_truncated_blob` — fixture: a fight with `events_blob_uri = "events/test-fight.jsonl.gz"`, the gzipped blob is the first 50 bytes of a real gzip stream (truncated before the end-of-stream marker). Monkeypatch `storage.get_events` to return the truncated bytes. Call `run_backfill(db, fight_id="test-fight")`. Assert: returns `(0, 0, 1)` (`failed == 1`, `backfilled == 0`, `skipped == 0`); the DB session is still alive and ready for the next fight (assert `db.is_active`).
- `test_run_backfill_catches_oserror_on_bad_crc_blob` — same pattern but the gzipped blob has a tampered CRC; asserts `failed == 1`.
- `test_run_backfill_catches_validation_error_on_malformed_event_line` — fixture: a `gfzip.decompress`-able blob whose JSONL has one malformed line; asserts `failed == 1`.
- `test_run_backfill_propagates_unexpectedexception_key_error_outside_catch_tuple` — fixture: a blob whose `TypeAdapter.validate_json` raises `KeyError` (a non-listed exception type). Asserts the exception propagates (NOT silently swallowed as `failed == 1`). Pins the closed-form exception contract: future generic-exception regression is loud, not silent.
- `test_backfill_pre_phase7_dedups_assert_comment_block` — `inspect.getsource(backfill._backfill_pre_phase7)` does NOT contain the literal substring `# narrowed by the caller's filter` twice (catches a regression that pastes-back the comment). The single canonical sentence is present.

## Rejected alternatives

- **Catch `Exception` broadly** — the canonical "specific exception types only" closed-form pattern. `Exception` would silently swallow keyboard interrupts (`KeyboardInterrupt` is `BaseException`, not `Exception`, so this is OK) + would scoop up `AttributeError` from a future schema change, silently marking fights as `failed` without operator visibility. The closed-form catch tuple is the canonical Python pattern. REJECTED.
- **Add a separate `except EOFError` clause BELOW the existing tuple** — Python merges them; functionally equivalent, but `except (X, Y, Z)` is more readable than two stacked `except` clauses for the same handler body. KEPT (single tuple).
- **Skip the comment-block dedup in `_backfill_pre_phase7`** — the duplication is harmless functionally but it confused the audit re-read; a future maintainer will also be confused. The cleanup is a 1-line deletion with no behavioural cost. KEPT.
- **Catch `zlib.error` instead of `EOFError`** — `gzip.decompress` raises BOTH `OSError` (CRC/length failure) AND `EOFError` (truncation) AND `zlib.error` (bad-zlib-header). `OSError` already covers zlib cases for the common path, and `EOFError` covers truncation. Skipping the per-zlib-error path: the candidate exception type list would expand indefinitely. KEPT (closed-form 5-tuple).
- **Move the `assert agent.account_name is not None` to the caller (`run_backfill`)** — the assertion lives on the construct call site for proximity. Moving it up to the caller would lose proximity to the schema construct. The `assert` stays where it is. REJECTED.

## Dependency graph

- Independent of plans 116 / 117. Plan 116 also addresses the same `EOFError` gap (in `routes/players.py::_contributions_from_blob_walk` post-hub refactor). Plan 117 doesn't intersect. The 3 plans can ship concurrently as 3 separate PRs.
- Touches 1 production source file (`backfill.py`) + 1 NEW test file.
- Patterns align with Plan 098 (gw2_evtc_parser importlib.metadata convergence) and Plan 100 (CLI inspect-zip OOM streaming fix): the v0.9.32 + v0.9.38 audit passes both systematically close per-fight failure-mode gaps in the data-ingestion pipeline. The `EOFError` truncation case is the same surface-level concern as a future schema-validation gap (`jsonl.json` reading a non-gzip payload) — closure patterns generalise.

## Notes for executors

- The `EOFError` is raised by `gzip.decompress` directly; the Python `gzip` module does NOT chain any `from` clause so the traceback's depth is 1. Verify after fix.
- The minimal-gzip-bytes fixture can use a real gzip-encoded blob truncated with `bytes[:50]`; no need for `ftruncate` on a zlib stream.
- The `_backfill_pre_phase7` comment-block dedup is a NO-OP behaviourally; the assert's invariant is unchanged. The fix is purely documentation.
- Future follow-up (out of scope for this plan): do the same `EOFError` catch extension to `routes/players.py::_contributions_from_blob_walk` (which is the plan 116 hub consolidation) and `routes/fights.py::_load_fight_events` (which raises `HTTPException(502)` on `OSError` but NOT on `EOFError`). This plan closes the highest-impact site (backfill) and signals the pattern for the 2 route sites in a follow-up.
