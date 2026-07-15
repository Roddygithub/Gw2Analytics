# Plan 004 — Archive stale plans in `plans/`

- **Slug:** `004-cleanup-stale-audit-plans`
- **Priority:** P4
- **Effort:** XS (30 minutes, mostly `git mv`)
- **Risk:** Low (planning only, no code paths affected)
- **Confidence:** 1.0
- **Status:** open

## Why

`plans/` contains 131+ markdown files, accumulated across v0.8.0 → v0.10.x audit cycles. Many of them are now:

- **Already-shipped**: their `## Status: COMPLETED` header is the only thing they have; the committed code lives in `CHANGELOG.md` + a git tag.
- **Superseded**: a later plan replaced the design (e.g. an early webhook delivery plan replaced by v0.9.1 hardening plan).
- **Orphan**: the plan describes a feature that the maintainer decided NOT to ship (no source counterpart, no CHANGELOG reference).

For an executor (human or agentic) navigating the project, 131 entries in the directory listing **shrinks visibility** of which plans are actionable. The `plans/README.md` index helps but only if the executor reads it first; raw `ls plans/` should be navigable too.

## Scope

**In scope:**
- Create `plans/archive/` directory.
- `git mv plans/<stale-plan>.md plans/archive/` for plans matching the staleness criteria.
- Update `plans/README.md` with a one-line "Archive: N plans" pointer.

**Out of scope:**
- Deletion of plans (none should be deleted — the audit history has investigative value).
- Modifying `plans/archive/*` content (read-only).
- Renaming any plan's slug.

## Files to reference

- `plans/README.md` (the existing guide / index for the plans directory).
- `CHANGELOG.md` (the canonical versioned history; the source of truth for "shipped" status).
- `git log -- plans/<slug>.md` (the commit history of each plan; frozen means shipped).

## Steps

1. **Audit** the plan corpus: for each `plans/*.md` (excluding `README.md`), check whether it satisfies ANY of these "stale" criteria:
   - Header contains `## Status: COMPLETED` AND the matching feature is in `CHANGELOG.md` under a released `[0.x.y]` header.
   - Plan slug `<plan_number>-v<old_version>-*.md` where `<old_version>` is older than the last 2 active cycles (i.e., for a v0.10.x project, anything `< 0.10.3`).
   - No matching source file / git diff / CHANGELOG entry (orphan — confirm by `git log --all -- plans/<slug>` returning no recent activity).

2. **Cross-check** with `plans/README.md` index. If a plan is marked DONE/SUPERSEDED there, archive.

3. **Move**: for each stale plan, `git mv plans/<slug>.md plans/archive/<slug>.md`. Preserve original filename (including numbering).

4. **Update** `plans/README.md`: add a `## Archive` section near the bottom with a single line:
   ```markdown
   ## Archive

   47 plans moved to `plans/archive/` (stale, superseded, or orphan). See `plans/archive/` for full history.
   ```

5. **Verify**: `ls plans/*.md | wc -l` decreases; `ls plans/archive/*.md | wc -l` increases by the same.

## Done criteria

```bash
# 1. archive/ exists and has stale plans
test -d plans/archive                                                                    # exit 0
ls plans/archive/*.md | wc -l                                                           # ≥ 30

# 2. plans/ top-level count decreased
ls plans/*.md | wc -l                                                                   # ≤ 100 (down from 131)

# 3. plans/README.md updated
grep -q '^## Archive' plans/README.md                                                   # exit 0

# 4. git status shows the moves (no content edits)
git status --porcelain plans/ | grep -c '^R'                                            # ≥ 30

# 5. No commits yet
git status --short | grep -v '^R ' | grep -v '^??'                                      # empty

# 6. (final, after commit): tree still parses
python3 -c 'import pathlib; [p.read_text() for p in pathlib.Path("plans").glob("*.md")]'  # exit 0
```

## Maintenance note

Future stale-plan triage should be a recurring quarterly chore: new plans added, old plans archived. The `plans/README.md` index is the source of truth.

## Escape hatch

If a member of `plans/archive/` is later revived as the basis for a new plan, copy-and-modify rather than `git mv` it back (preserves the historical trail).
