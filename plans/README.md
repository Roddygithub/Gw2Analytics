# v0.8.8 Advisor Plans

**Author:** senior-advisor audit (improve skill, `next` invocation, `quick` effort)
**Stamped at:** `fe99cb7` (origin/main HEAD)
**Recon scope:** README + CHANGELOG + pyproject.toml + apps/api routes + web/app pages + recent commits
**Audit mode:** direction-only (4 candidates below); correctness/security/perf/etc. out of scope

---

## Status table

| # | Finding | Category | Impact | Effort | Risk | Plans |
|---|---------|----------|--------|--------|------|-------|
| 1 | `pnpm screenshots` produces 8 PNGs that are gitignored + invisible to end-users | direction (DX + docs) | High (UX) | S | Low | [001](./001-screenshots-into-readme.md) |
| 2 | Playwright config + `pnpm test:e2e` exist but zero actual e2e tests in repo | direction (testing) | High (reliability) | M | Low | [002](./002-real-playwright-e2e-suite.md) |
| 3 | `pnpm generate:api` is manual; web app often runs against a stale or absent `schema.d.ts` | direction (DX) | Medium (dev experience) | S | Low | [003](./003-auto-codegen-on-pnpm-dev.md) |
| - | Web routes already cover all API endpoints (7/7 web pages vs 8 distinct API endpoint groups) | not a finding — already shipped | — | — | — | rejected |

---

## Recommended execution order

1. **Plan 001** (Screenshots → README) — self-contained, low risk, visible win. Closes the loop on the v0.8.7 `pnpm screenshots` investment that landed in commits `ad9959a`–`fe99cb7`.
2. **Plan 002** (Real Playwright e2e suite) — depends on 001's `docs/screenshots/` directory being a stable artifact store. Reuses the directory layout + adds `assertions`.
3. **Plan 003** (Auto-codegen on dev) — independent of 001/002. Standalone DX win.

There are no inter-plan dependencies blocking; the ordering is by leverage (impact ÷ effort), not strict sequencing.

---

## Considered and rejected

- **"Build /fights/[id]/timeline tab" / "Upload progress feedback" / "Per-player-fights route"**: each is plausible but small-leverage vs the plans above; would need full design + UX validation first. Reserved for v0.8.9+.
- **"S3-backed blob storage for evtc files"**: large infrastructure commitment (storage vendor, IAM, lifecycle, cost); proceed only after uploader has real-user volume proving the need. Out of scope for v0.8.8.
- **"Web route coverage of remaining API endpoints"**: all 7 web pages already exist and route to the corresponding API endpoints; coverage is full. Not a finding.

---

## Conventions for the executor

- The repo uses Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `style:`, `refactor:`).
- Python: `uv run <cmd>` from repo root or `cd apps/api && uv run <cmd>` — never `pip`.
- JS: `pnpm <cmd>` from `web/` or repo root (pnpm workspace).
- Validation: `uv run ruff check`, `uv run mypy --no-incremental libs apps`, `uv run pytest <path>`, `pnpm typecheck`, `pnpm test:unit`.
- Commit-style: every commit has substance (no empty commits); every feature gets a doc sync in the same cycle (README + CHANGELOG).
- Code-reviewer pattern: spawn `code-reviewer-minimax-m3` for **every** non-trivial commit with concrete prompt (≤70 words + focus questions).
