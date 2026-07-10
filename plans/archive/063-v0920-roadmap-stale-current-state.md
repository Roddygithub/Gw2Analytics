# Plan 063 — v0.9.20: `docs/ROADMAP.md` stale current state + §1.1/§1.2 reconciliation

## Drift base

`44ea862`. Docs cleanup only — no code changes, no migration.

## Surface

`docs/ROADMAP.md` (the canonical "what's left to do" doc, per its
own §4 update protocol),
`.github/workflows/ci.yml` (for the test count CI signal),
`CHANGELOG.md` (for the released-version list),
`git log` (for the commit-derived version + test count).

## Finding

The ROADMAP has 3 drift sub-issues vs the v0.9.2 code:

1. **"Current state" header is stale**:
   - "Last refreshed during the v0.9.0 close-out (post v0.8.9 ship)"
     — should be "Last refreshed at v0.9.2 (post v0.9.1 + v0.9.2 ships)".
   - "Latest shipped tag: v0.8.9" — should be `v0.9.2` (per the
     most recent tag per `git tag`).
   - "Test count: 303 active tests" — should be the current count
     (the v0.9.1 + v0.9.2 cycles added tests; the exact count
     requires a CI run, but the placeholder is in the
     hundreds-of-tests range).

2. **§1.1 "Items removed since v0.8.0/v0.8.9 release cycle"** has
   the webhooks backend entry BUT §1.2 "Ready to implement"
   shortlist does NOT reconcile the v0.9.1 retry+DLQ+replay
   item. The shortlist says "The webhooks row's new 'v0.9.1
   retry + DLQ + replay' scope is captured in the §1 table
   above" but §1 does not list it (it lists 4 items; the
   retry+DLQ+replay is in §2.1 "Tech debt" with a "shipped in
   v0.9.1" annotation).

3. **§1 table itself** does not list "webhook retry + DLQ + replay"
   as a v1.0 candidate (it shipped in v0.9.1, so it should be
   moved to the "shipped" archival list). The "Combat readout"
   row is the only v1.0 candidate from the v0.8.0 web-design
   doc that has not shipped.

## Fix

1. **"Current state" header refresh**:
   - Change "Last refreshed during the v0.9.0 close-out (post v0.8.9 ship)"
     to "Last refreshed at v0.9.2 (post v0.9.1 + v0.9.2 ships)".
   - Change "Latest shipped tag: v0.8.9" to "Latest shipped tag: v0.9.2".
   - Update the test count to a placeholder (e.g., "Test count:
     TBD — see CI badge for the current count") with a
     comment that a CI-injected value (e.g., from a
     `pytest --collect-only -q | wc -l` step) is the canonical
     source. The current count is ~400+ tests; the exact
     number should be filled in by the operator after `uv
     run pytest --collect-only`.

2. **§1.1 reconciliation**: add a new "shipped in v0.9.1" entry
   for the webhook retry + DLQ + replay (the v0.9.1 close-out
   shipped 7 file changes per the ROADMAP §2.1 archival note;
   this entry should be mirrored in §1.1 as a "shipped" item).

3. **§1.2 shortlist reconciliation**: update the "Ready to
   implement" shortlist to remove the now-shipped webhook
   retry + DLQ + replay item. The shortlist now has 2 items
   (cross-account comparison + combat readout) + the
   skill build analyser (3 items total, same as before, just
   the retry+DLQ+replay is removed).

4. **§2.1 "shipped" entry for webhooks retry+DLQ+replay**: keep
   the existing entry as the historical archival; the §1.1
   reconciliation is a duplicate of the §2.1 entry but in the
   "v1.0 candidates removed since" section (which is the
   canonical placement per the doc's own structure).

5. **Add a "Last refreshed at v0.9.2" footer** at the bottom of
   the doc.

## Risks

- The test count placeholder ("TBD — see CI badge") is a
  temporary degradation. A future plan can add a CI step that
  injects the count from `pytest --collect-only -q` into the
  ROADMAP at build time (e.g., a `sed` substitution in the
  CI workflow).
- The "Latest shipped tag" depends on `git tag` output, which
  may not be present in the cloned repo (tags are not fetched
  by default). A future plan can add a CI step that injects
  the latest tag from `git describe --tags --abbrev=0` into
  the ROADMAP at build time.
- The §1.1 + §2.1 dual-listing of the v0.9.1 retry+DLQ+replay
  is intentional (per the doc's own structure: §1.1 is
  "v1.0 candidates removed", §2.1 is "tech debt removed");
  a future audit may consolidate, but the v0.9.20 minimum
  is to keep both entries consistent.

## Tests

1. `test_roadmap_latest_shipped_tag_is_v0_9_2` — read the doc;
   assert "Latest shipped tag: v0.9.2" is present (not
   "v0.8.9").
2. `test_roadmap_last_refreshed_footer_is_v0_9_2` — read the doc;
   assert the "Last refreshed at v0.9.2" footer is present.
3. `test_roadmap_shortlist_excludes_v0_9_1_retry_dlq` — read §1.2;
   assert the shortlist does NOT list "webhook retry + DLQ + replay"
   as a ready-to-implement item.
4. `test_roadmap_§1_1_includes_v0_9_1_retry_dlq` — read §1.1;
   assert the v0.9.1 retry+DLQ+replay is listed as a
   "shipped" item.

## Rejected alternatives

- **Drop the test count from the ROADMAP entirely** (let the
  CI badge be the sole source): tempting (the placeholder
  is a temporary degradation). The test count is a useful
  at-a-glance signal in the doc itself; the CI badge is a
  separate surface. A future plan can add a CI-injected
  value to make the count dynamic.
- **Drop the "Latest shipped tag" from the ROADMAP** (let the
  git tag be the sole source): same reasoning as above. The
  tag is a useful at-a-glance signal.
- **Move the ROADMAP to a CI-rendered page** (e.g., a GitHub
  Pages site): out of scope (the doc is a markdown file in
  the repo; a CI-rendered page is a future refactor).
- **Consolidate §1.1 + §2.1 "shipped" lists into a single
  "archive" section**: out of scope (the doc's structure is
  intentional: §1 is "v1.0 candidates", §2 is "tech debt";
  the shipped items in each section have different
  contexts).
- **Add a CHANGELOG cross-reference for each shipped item**:
  out of scope (the CHANGELOG is a release log; the ROADMAP
  is a forward-looking doc; cross-references add a
  maintenance burden without a corresponding legibility win).
