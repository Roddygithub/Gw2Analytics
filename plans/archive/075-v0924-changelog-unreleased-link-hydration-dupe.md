# Plan 075 — CHANGELOG Unreleased link + duplicate hydration guard entry cleanup

Drift base : `main` (3 commits ahead of origin).

## Problem

The CHANGELOG has **2 independent drift bugs** in the
`## [Unreleased]` section:

1. **The `[Unreleased]` link at the bottom of the file is wrong.** The
   file ends with:

   ```markdown
   [Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.8...HEAD
   ```

   But the latest release-tagged section is `## [0.9.2]`, NOT
   `## [0.8.8]`. The link should be
   `compare/v0.9.2...HEAD` (or — once a v0.9.3 is cut — `compare/v0.9.2...v0.9.3`
   for the released v0.9.2 and a new `[Unreleased]` link to the
   current HEAD). This is a pre-existing footgun (it was wrong even
   at the v0.8.9 close-out — the file had `## [0.8.9]` as the latest
   release at that point and the link was `compare/v0.8.8...HEAD`,
   which silently `404`s on GitHub's compare page because `v0.8.8`
   is not an ancestor of `v0.8.9`). The link has been wrong since
   v0.8.9 was tagged; the v0.9.x cycles inherited the bug.

2. **The `## [Unreleased]` section has 2 entries describing the same
   hydration-guard fix.** There are 2 separate top-level subsections
   that both describe the screenshots.mjs hydration guard:

   - `### Changed (web - screenshots.mjs hydration guard)` — the
     **first** entry, describing the `waitForFunction` predicate
     (scrollHeight > 900 + 500ms stability) + the 15s → 30s timeout
     bump.
   - `### Fixed (web e2e - VR hydration)` — the **second** entry,
     describing the same fix as a "restored v0.9.0 plan/003 hydration
     guard that commit `882edff` had over-aggressively removed" +
     the `PAGES` const's third slot `"stable-scroll"` tagged
     sentinel dispatch.

   Both entries describe the **same** code change (the hydration
   guard re-introduction in screenshots.mjs), but the second is a
   more verbose / "fix-up" framing of the first. This is a
   copy-paste accident — likely the second entry was meant to
   REPLACE the first (the second explicitly references "commit
   `882edff` had over-aggressively removed" which is a fix-up
   framing), but both were committed in the v0.9.0 close-out.

   The 2 entries are also stylistically inconsistent: the first is
   `### Changed (web - screenshots.mjs hydration guard)`, the second
   is `### Fixed (web e2e - VR hydration)`. A reader skimming the
   `## [Unreleased]` section will see 2 bullets describing the same
   fix and wonder which is the authoritative one.

## Fix

Two doc-only edits to `CHANGELOG.md`. No code changes. No new files.

### Edit 1 — Fix the `[Unreleased]` link at the bottom of the file

Replace the existing:

```markdown
[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.8...HEAD
```

With:

```markdown
[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.9.2...HEAD
```

(The latest release-tagged section is `## [0.9.2]`; the link should
point to the diff from the v0.9.2 tag to current HEAD. This restores
the link's correctness for the v0.9.2 close-out and is the same
1-line change that should have been made at the v0.8.9 close-out.)

### Edit 2 — Collapse the 2 hydration-guard entries into 1

The fix: keep the **more verbose** entry (the `### Fixed` one, which
documents the fix-up framing + the `"stable-scroll"` tagged sentinel
dispatch — the version that captures the actual code state) and
**delete** the shorter `### Changed` entry (which is a redundant
summary of the same change).

Rationale for keeping the `### Fixed` entry rather than the
`### Changed` entry:

- The `### Fixed` entry has the **commit reference** (`882edff`) —
  the `### Changed` entry doesn't, so the `### Fixed` is more useful
  for archaeology.
- The `### Fixed` entry documents the **operational behaviour**
  ("5 dynamic-page baselines will be 1440x3196 instead of 1440x900")
  — the `### Changed` entry is a diff-level summary, less useful for
  a visitor.
- The `### Fixed` entry uses the more accurate framing
  (it's a fix-up, not a new feature).

The deletion is a 1-paragraph removal (~10 lines), and the
keep-as-is entry is unchanged. Net delta: ~10 lines removed.

## Files modified

- `CHANGELOG.md` (2 edits, ~10 lines net removed — 1 link line
  replaced + 1 redundant entry deleted = 2 lines changed, 10 lines
  removed).

## CHANGELOG entry to add at v0.9.x close-out

```markdown
### Fixed (docs - CHANGELOG Unreleased link + duplicate hydration guard entry)

- `CHANGELOG.md`: 2 doc-only edits scoped to the v0.9.x cycle's
  CHANGELOG drift:
  * The `[Unreleased]` link at the bottom of the file is now
    `compare/v0.9.2...HEAD` (was `compare/v0.8.8...HEAD`); the
    latest release-tagged section is `## [0.9.2]`. The pre-v0.9.2
    link was a pre-existing footgun (it was wrong even at the
    v0.8.9 close-out; silently `404` on GitHub's compare page
    because `v0.8.8` is not an ancestor of `v0.8.9`).
  * The 2 redundant `## [Unreleased]` entries describing the
    screenshots.mjs hydration guard (`### Changed (web -
    screenshots.mjs hydration guard)` + `### Fixed (web e2e -
    VR hydration)`) are collapsed into 1 — the `### Fixed` entry
    is kept (has the `882edff` commit reference + the operational
    behaviour description), the `### Changed` entry is deleted
    (was a redundant summary of the same code change).
  No code changes.
```

## Validation

- `git diff CHANGELOG.md` shows the 2 edits cleanly; no other lines
  modified.
- The `[Unreleased]` link now resolves to a valid GitHub compare URL
  (the `compare/v0.9.2...HEAD` URL is well-formed; whether HEAD
  has diverged from v0.9.2 is out-of-scope for this plan).
- The `## [Unreleased]` section now has 1 entry for the hydration
  guard, not 2.
- The kept entry preserves the commit reference (`882edff`) and the
  operational behaviour description ("5 dynamic-page baselines will
  be 1440x3196 instead of 1440x900") verbatim.

## Rejected alternatives

1. **Add a new `## [0.9.3]` section instead of fixing the `[Unreleased]`
   link.** Would be wrong — v0.9.3 is not yet cut. The current HEAD
   has 3 un-pushed commits (per `git status`); once those are
   pushed + a v0.9.3 tag is cut, the `[Unreleased]` link will move
   to `compare/v0.9.3...HEAD` (but that's a v0.9.3 close-out
   concern, not this plan's scope). Rejected.
2. **Keep the `### Changed` entry and delete the `### Fixed` entry.**
   Would lose the `882edff` commit reference + the operational
   behaviour description (the more useful framing). Rejected.
3. **Merge the 2 entries into a single `### Changed/### Fixed`
   hybrid.** The CHANGELOG convention is 1 subsection per code
   change; a hybrid is non-standard. Rejected.
4. **Use `git log` to find the actual commit that introduced each
   entry and use the commit subject as the entry title.** Would
   couple the CHANGELOG to git history; the project does not have
   a doc-codegen pipeline for the CHANGELOG. The 2 manual edits
   are 1 minute of work and 0 deps. Rejected.
5. **Move both entries to a new `## [0.9.3]` section.** Would be
   wrong — v0.9.3 is not yet a release. The entries describe
   changes that landed in the v0.9.0 → v0.9.2 cycle (per the
   commit reference `882edff`), so they belong in `[Unreleased]`
   until v0.9.3 is cut. Rejected.
