# Plan 088 — v0.9.28 — `apps/api/src/gw2analytics_api/services.py::_save_fight` docstring "aspirational future `started_at = datetime.now(UTC)`" framing cleanup

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (LOW DX + docs hygiene):** `apps/api/src/gw2analytics_api/services.py::_save_fight` has a 12-line comment on `started_at = datetime.now(UTC)` that frames the line as a "v0.8.1 unconditional override" with an "aspirational future v0.9" parenthetical about parsing the EVTC build field:

```python
# EVTC blobs do not carry a wall clock. ``cf.started_at`` defaults
# to the Unix epoch sentinel (``datetime(1970, 1, 1, tzinfo=UTC)``
# in :class:`gw2_core.Fight`), so we MUST override with the
# server's wall clock at parse time. The previous
# ``cf.started_at if cf.started_at.tzinfo else datetime.now(UTC)``
# guard was a bug: the epoch sentinel HAS tzinfo (UTC), so the
# guard fell through and every fight landed on 1970-01-01
# midnight UTC, breaking the v0.8.0 timeline chart (all points
# stack at the leftmost X-axis slot). v0.8.1 unconditionally
# uses ``datetime.now(UTC)``; a future v0.9 could parse the
# EVTC build field (``yyyymmdd``) to get a date anchor.
```

The 12-line block mixes 3 things:
1. An historical bug explanation (the v0.8.0 → v0.8.1 transition from "guard fell through" → "unconditional override"). This is useful for a maintainer who needs to understand WHY the unconditional override is the correct semantic.
2. The CURRENT canonical behavior: `started_at = datetime.now(UTC)` is the v0.8.1 unconditional override.
3. An aspirational future: "a future v0.9 could parse the EVTC build field" — this is forward-looking musing, not current behavior.

The cleanest framing of the same content:
- 1 paragraph documenting the current canonical behavior (the unconditional override is correct + the historical bug it closed)
- 1 paragraph noting the aspirational future **outside** the inline comment (the `parser.py` EVTC build field parsing is a future plan, not a current observation)

A future maintainer reading the current comment is misled to think the aspirational line is a current refactor target. The `parser.py` already has the build field parsing (it's a `yyyyMMdd` string in the EVTC header); a future v0.9+ plan can add an opt-in "use EVTC build for date anchor" flag. The docstring should not pre-frame this as a current commitment.

Fix: extract the 12-line comment into 2 cleaner paragraphs + move the aspirational line to a `_FUTURE_WORK` docstring section (or to the module-level docstring's forward-compat note).

## File changes

### 1 file edited + 0 NEW modules

**`apps/api/src/gw2analytics_api/services.py::_save_fight`** — current 200+ line file with 1 patch on the `started_at = datetime.now(UTC)` line:

```diff
-    # EVTC blobs do not carry a wall clock. ``cf.started_at`` defaults
-    # to the Unix epoch sentinel (``datetime(1970, 1, 1, tzinfo=UTC)``
-    # in :class:`gw2_core.Fight`), so we MUST override with the
-    # server's wall clock at parse time. The previous
-    # ``cf.started_at if cf.started_at.tzinfo else datetime.now(UTC)``
-    # guard was a bug: the epoch sentinel HAS tzinfo (UTC), so the
-    # guard fell through and every fight landed on 1970-01-01
-    # midnight UTC, breaking the v0.8.0 timeline chart (all points
-    # stack at the leftmost X-axis slot). v0.8.1 unconditionally
-    # uses ``datetime.now(UTC)``; a future v0.9 could parse the
-    # EVTC build field (``yyyymmdd``) to get a date anchor.
-    started_at = datetime.now(UTC)
+    # ``started_at = datetime.now(UTC)`` is the v0.8.1 unconditional
+    # override -- the EVTC binary format does NOT carry a wall-clock
+    # anchor (only a `yyyyMMdd` build-version string), so we use
+    # the server clock as the canonical wall-clock anchor. The
+    # pre-v0.8.1 code path used a guard
+    # (cf.started_at if cf.started_at.tzinfo else datetime.now(UTC))
+    # which silently fell through on the Unix epoch sentinel
+    # (which HAS tzinfo=UTC) -- every fight landed on 1970-01-01
+    # midnight UTC, breaking the v0.8.0 timeline chart (all points
+    # stacked at the leftmost X-axis slot).
+    #
+    # Future work: a v0.9+ plan could parse the EVTC build field
+    # (yyyyMMdd, already decoded by libs/gw2_evtc_parser's
+    # EvtcHeader.build_version) into a date anchor + use it as the
+    # canonical started_at instead of the server wall clock. The
+    # current behavior is correct for the v0.8.x cycle range.
+    started_at = datetime.now(UTC)
```

Net change: ~5 lines shorter (the paragraph is reorganized + the aspirational line is in a `Future work` block, easier to scan).

## Considered and rejected

- **Alternative: remove the comment entirely** — the historical context (the pre-v0.8.1 guard bug) is genuinely useful for a maintainer who needs to understand why the unconditional override is canonical. Removing the comment loses that context.
- **Alternative: extract the aspirational line to a separate TODO docstring on `_save_fight`** — TODO docstrings are typically written in `TODO:` or `FIXME:` form which is noisy; the `Future work:` block reads cleaner.
- **Alternative: move the aspirational line to a `## Future work` section in `docs/ROADMAP.md`** — Roadmap is the canonical home for aspirational items; moving the line out of the inline comment fully unlocks the inline comment for "current behavior" only.
- **Alternative: upgrade the inline comment to a docstring on `_save_fight`** — the function's docstring is documented in the module-level docstring; the comment block is the canonical place for the historical context. The patch stays in the comment block.

## Effort

`S` — 1 file edit (the 12-line comment block in `_save_fight`). Net `-5` lines. No code change. No test impact. No new test file (this is purely a docs hygiene change; the 12 e2e tests in `test_uploads_e2e.py` already validate the current canonical behavior + the test_health_summary.py tests verify the date-time invariant post-UPDATE). Independent of plans 086 + 087.
