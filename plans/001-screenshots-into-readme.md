# Plan 001 — Wire `pnpm screenshots` output into the README

## Context

The v0.8.7 chore cycle (commits `ad9959a`–`fe99cb7`) shipped `web/scripts/screenshots.mjs` + a `pnpm screenshots` entry in `web/package.json` that captures 8 full-page PNGs (`01-landing.png` through `08-fight-drilldown.png`) of the GW2Analytics UI into a gitignored `/screenshots/` directory at the repo root.

**Gap:** the developer can take screenshots, but the resulting PNGs are:
- invisible to anyone reading the README (no rendering of the UI),
- invisible to recruiters / contributors / users evaluating the project,
- gone on the next clone (gitignored).

The fix is to commit the PNGs to a stable `docs/screenshots/` directory + reference them from a new "Screenshots" section in the root README.

## Goal

A new top-level `docs/screenshots/` directory containing the 8 PNGs (committed), plus a "Screenshots" section in the root README that references 6 of them (landing, account, upload, fights, players, player-timeline) with `markdown image syntax` — leaving the 2 fixture/empty-state PNGs (`07-player-empty-timeline.png`, `08-fight-drilldown.png`) available for future use but not visually demoed.

## Files in scope

- **Create:** `docs/screenshots/.gitkeep` (empty marker, never commit the auto-generated PNGs here unless deliberately refreshed)
- **Commit:** `docs/screenshots/01-landing.png` through `docs/screenshots/08-fight-drilldown.png` (8 files, ~384 KB total)
- **Update:** `README.md` — add a new `## Screenshots` section between `## Run` and `## Tech stack` (or wherever it best fits after a quick read of the current section ordering)
- **Update:** `web/scripts/screenshots.mjs` — add a `--persist` flag (default off) that copies the 8 PNGs into `docs/screenshots/` AFTER the run, so future devs can refresh the committed docs in 1 command

## Files explicitly out of scope

- `.gitignore` — do NOT add `docs/screenshots/` (the dir is meant to be tracked)
- `web/README.md` — out of scope (root README is the project's canonical landing)
- Any changes to the screenshots themselves (no re-rendering, no cropping, no resizing — committing what the script produces)
- Any other docs (`CONTRIBUTING.md`, `CHANGELOG.md` — CHANGELOG is bumped only when v0.8.8 ships)

## Steps

1. **Create the directory + copy the 8 PNGs.**
   ```bash
   mkdir -p docs/screenshots
   cp /home/roddy/Gw2Analytics/screenshots/*.png docs/screenshots/
   ls -la docs/screenshots/
   ```
   Verify 8 PNGs exist; if any are missing, re-run `pnpm screenshots` against the dev stack first.

2. **Add a `.gitkeep` so the dir is recognized before any PNGs land (idempotent — already has PNGs, skip if step 1 succeeded).**
   ```bash
   test -f docs/screenshots/.gitkeep || touch docs/screenshots/.gitkeep
   ```

3. **Update `web/scripts/screenshots.mjs`:**
   - After the per-page screenshot loop, if `--persist` was passed, copy each `${label}.png` to the path `resolve(import.meta.dirname, "..", "..", "docs", "screenshots", `${label}.png`)` (using the existing `cp` via `node:child_process` → `execFile` or `promisify(exec)`; avoid shell:true).
   - Add the flag to the script's docstring Usage block: `Usage: node web/scripts/screenshots.mjs [--persist]`.
   - Use `process.argv.includes("--persist")` rather than pulling in a CLI parser — matches the script's no-deps philosophy.

4. **Update the root README:**
   - Read the current README first to find a clean insertion point (likely before `## API` or `## Tech stack`).
   - Add a new `## Screenshots` section with 6 image references, each with a 1-line caption:
     ```markdown
     ## Screenshots

     | Route | Capture |
     |-------|---------|
     | [`/`](../) | ![Landing](docs/screenshots/01-landing.png) |
     | [`/account`](../account) | ![Account resolve form](docs/screenshots/02-account.png) |
     | [`/upload`](../upload) | ![Upload flow](docs/screenshots/03-upload.png) |
     | [`/fights`](../fights) | ![Fights grid](docs/screenshots/04-fights.png) |
     | [`/players`](../players) | ![Players grid](docs/screenshots/05-players.png) |
     | [`/players/[account_name]`](../players) | ![Player profile with timeline](docs/screenshots/06-player-profile-with-timeline.png) |
     ```
   - Add a footnote-style reminder after the table: `* Refreshed via: \`pnpm screenshots --persist\`` (matches the script's CLI usage).

5. **Verify:**
   - `git status --short` — should show only the new `docs/screenshots/*.png` files + the README.md diff.
   - `git diff README.md | head -50` — visual sanity check.
   - `node --check web/scripts/screenshots.mjs` — syntax check.
   - `pnpm install --frozen-lockfile` from repo root (no dependency change but proves package.json is valid).

6. **Commit and push:**
   - Conventional Commits prefix: `docs(readme): wire pnpm screenshots into the root README as visual evidence`.
   - Body should reference the v0.8.7 chore cycle (commits `ad9959a`–`fe99cb7`) so future readers can trace the lineage.

## Test plan

- **Manual visual test:** render the README on GitHub after push; confirm the 6 inline PNGs render correctly + the table layout doesn't break.
- **No new tests required** — this is a docs change. The existing `pnpm test:unit` + Playwright suites remain green.

## Done criteria

- `git log -1 origin/main` shows a new `docs(readme): ...` commit on top of `fe99cb7`.
- `git status --short` is clean post-push.
- 8 PNGs present under `docs/screenshots/` on origin/main.
- README's `## Screenshots` section renders on GitHub with 6 visible images.
- `pnpm screenshots --persist` regenerates the 8 PNGs into BOTH `/screenshots/` AND `docs/screenshots/` (verified locally; does not trigger a CI run for this plan).

## Maintenance note

- When the UI changes meaningfully (e.g., a new route, a layout overhaul), re-run `pnpm screenshots --persist` + commit the refresh as part of the feature's doc sync.
- The `docs/screenshots/` dir will grow with the UI; cap at 12-16 PNGs to keep README scannable — if it grows beyond, demote older screenshots to a `## Archive` subsection or split into per-route files.
- The `--persist` flag is intentionally opt-in; the default behavior (`/screenshots/` only) stays gitignored so casual runs don't accidentally clobber the committed docs.

## Escape hatch

If `pnpm screenshots` fails in step 1 because the dev stack isn't up, STOP and report back — this plan depends on having fresh PNGs to commit. Do not commit stale PNGs from a previous run (check the timestamps; if any is older than 24 hours, re-run).
