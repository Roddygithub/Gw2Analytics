#!/usr/bin/env python3
"""Idempotent helper: insert the v0.9.35 audit section into plans/README.md.

Pattern matches _insert_v0927_section.py through _insert_v0934_section.py:
writes the section template literal to file if and only if the
v0.9.35 header is NOT already present, and places it just before
"## v0.9.34 audit (current)" so the section-order invariant (newest
always closest to the top of the closed history block) holds. Refuses
to re-run on consecutive invocations.
"""
from __future__ import annotations

import sys
from pathlib import Path

README = Path("plans/README.md")
V0935_HEADER = "## v0.9.35 audit (current)"
V0935_ANCHOR = "## v0.9.34 audit (current)"


SECTION_TEMPLATE = """## v0.9.35 audit (current)

**Author:** senior-advisor read-only audit pass. **Status:** current cycle.

**Scope.** Root-level operability files: `.github/workflows/ci.yml` + `Caddyfile` + `docker-compose.yml` + (cross-cutting) `.gitignore` NEW additions + NEW `docs/self-host.md`. The 3 files in scope are the deployment-CI surface never deeply audited (the codegen-scripts `web/scripts/dump_openapi.py` + `web/scripts/screenshots.mjs` were covered by plan 058 v0.9.18).

| Plan | File(s) touched | Risk | LOC delta |
| --- | --- | --- | --- |
| **107** | `docker-compose.yml` + NEW `docker-compose.override.yml.example` + `.gitignore` | low-medium — env_file mechanism + restart policy + production override split. Resolves the production-misconfig foot-gun (currently `MINIO_ROOT_PASSWORD: gw2analytics-secret` is a literal in source). | +35, -10 |
| **108** | `Caddyfile` + NEW `docs/self-host.md` | low — 5 canonical security headers (HSTS + X-Frame-Options + X-Content-Type-Options + Referrer-Policy + Permissions-Policy) + cross-link with the `next.config.ts::headers()` belt-and-braces layer (per plan 056 v0.9.18). | +45, -2 |
| **109** | `.github/workflows/ci.yml` | low — single-line addition `if: success()` to the post-e2e health-probe gate; fixes the false-negative surface when pytest fails before the e2e suite runs. | +1, -0 |

**Dependency graph.** All three plans touch DISJOINT file regions: 107 affects `docker-compose.yml` + a gitignored NEW override; 108 affects `Caddyfile` + a NEW docs file; 109 affects `.github/workflows/ci.yml` only. PRs can land concurrently.

**Cross-cutting thematics**:

- **Production hardening (Plan 107)**: dev-friendly compose defaults → operator-authored override file pattern (the canonical docker-compose hybrid pattern for self-hosting).
- **Belt-and-braces security headers (Plan 108)**: adds 5 canonical security headers at the Caddy TLS-termination boundary. The `next.config.ts::headers()` layer (per plan 056) added 4 of these on web responses; the Caddy layer adds them on ALL responses (including the FastAPI gateway responses that bypass the Next.js proxy).
- **CI false-negative guard (Plan 109)**: the existing post-e2e health probe gate runs unconditionally; if pytest errors out before the e2e suite runs (a common failure mode for import-time fixture errors), the gate sees baseline-vs-baseline (drift = 0) and reports success. The `if: success()` guard restricts the step to run only when pytest actually executed.

**Rejected alternatives (10 total across the 3 plans).** Highlights:

- **Plan 107 alternative: inline the production values in `docker-compose.yml` via git-ignored env-var substitution** — works but eliminates the merge pattern; operators can't add extra service overrides (e.g. adding the `apps-api` + `web/` services to the prod compose). The two-file split is the canonical pattern. REJECTED.
- **Plan 107 alternative: use Docker Swarm / k8s secrets** — the project doesn't run on Swarm / k8s today; the platform is bare-bones docker compose. The override pattern is the closest analogue. REJECTED.
- **Plan 108 alternative: skip the Caddy-side headers and rely solely on the `next.config.ts::headers()` layer** — works for web responses but not for the FastAPI gateway responses (the analytics bulk-download endpoints, the player profile JSON endpoint). The Caddy layer is the canonical reverse-proxy. REJECTED.
- **Plan 109 alternative: wrap the post-e2e gate in `if: always()` (= failure OR success)** — same as the current pattern; runs even on failure. The fix requires `success()` ONLY. REJECTED.
- **Plan 109 alternative: move the post-e2e health gate to a SEPARATE job** (`if: needs.lint-and-test.result == 'success'`) — adds another job's-worth of CI minutes for the same effect. The `if: success()` step-level guard is the cheaper fix. REJECTED.

**Test count.** 4 + 3 + 3 = **10 new hermetic tests** across the 3 plans (1 Caddy-derived test skipped in CI if `caddy` binary absent).

**Conventions for the executor.** All 3 plans:
- Touch **only** the listed files; no incidental edits.
- 107 introduces a NEW `docker-compose.override.yml.example` template file; the resolved `docker-compose.override.yml` is gitignored (operator-authored, secret-bearing).
- 108 introduces a NEW `docs/self-host.md` operational doc; cross-references with `plan 056 v0.9.18` for the Next.js-side belt-and-braces.
- 109 is the smallest change (1 line); the test (`test_post_e2e_health_gate_step_has_if_success_guard`) pins the guard's presence so a future refactor doesn't drop it.

"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if V0935_HEADER in text:
        print(f"[skip] {V0935_HEADER!r} already present; no-op.")
        return 0

    if V0935_ANCHOR not in text:
        print(f"[error] anchor {V0935_ANCHOR!r} not found; abort.", file=sys.stderr)
        return 1

    replacement = SECTION_TEMPLATE + V0935_ANCHOR
    updated = text.replace(V0935_ANCHOR, replacement, 1)
    README.write_text(updated, encoding="utf-8")
    print(f"[ok] inserted {V0935_HEADER!r} (anchor: {V0935_ANCHOR!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
