# M9 — Pre-commit `end-of-file-fixer` race-condition fix

**Plan ID:** M9 (forward-deferred to v0.10.20 cycle startup OR v0.10.20 close-out pre-mode; effort S).
**Cycle context:** v0.10.20 `plan-landing` sub-cycle (the 4 followups this audit set up).
**Filename convention:** standard M-prefix.

---

## §1 — Problem statement

The `end-of-file-fixer` pre-commit hook
(`https://github.com/pre-commit/pre-commit-hooks` rev `v5.0.0`,
configured at `.pre-commit-config.yaml`) auto-fixes trailing newlines
ON DISK AFTER `git add` but BEFORE `git commit` completes. The auto-fix
either:

- (A) **Silently mutates the committed tree** — `git commit` finalizes on
  the auto-fixed content without warning, so the committed blob differs
  from the staged blob. The user has no way to know the auto-fix ran
  unless they inspect `git diff --staged` mid-pre-commit-hook.

- (B) **Causes a mid-flight reschedule** — if pre-commit's race resolution
  re-stages the auto-fixed content, the hook re-runs from scratch
  (potentially infinitely if the hook is itself triggered by another
  file's statechange).

The auto-fix itself is benign (just trailing-newline normalization), but
its side-effects on the commit stage are not. At v0.10.18.1 close-out +
v0.10.19 close-out, the hook's mid-flight behavior caused mid-cycle
closeout failures (the CHANGELOG.md splice was auto-fixed AFTER staging
but BEFORE commit-final, requiring a `--no-verify` workaround).

---

## §2 — Observed occurrences (post-v0.10.18)

| Cycle | Symptom | Resolution |
|---|---|---|
| v0.10.18.1 close-out | `CHANGELOG.md` entry splice triggered EOF auto-fix rescheduling mid-commit | `--no-verify` bypass used |
| v0.10.19 close-out | Plan-landing phase hit the exact same EOF auto-fix block on `CHANGELOG.md` splice | `--no-verify` bypass used (pattern recurrence) |

Both occurrences involved the close-out workflow's CHANGELOG.md splice
pattern: `git status` shows dirty `CHANGELOG.md` → `python
apply_docs.py` adds new entry → `git add CHANGELOG.md` → `git commit`
mid-flight: hook auto-fixes trailing newline → commit finalizes on
auto-fixed content.

If future cycles continue this close-out workflow (4-cycle thread
includes v0.10.20 mimo-half close-out, v0.10.21 ADR 002 implementation,
v0.10.21 cycle close-out, etc.), the `--no-verify` bypass would be a
RECURRING workaround. M9 addresses this recurrence.

---

## §3 — Root cause analysis

Git's pre-commit hook lifetime:
1. User runs `git commit -m "..."` (or `git commit --no-verify`).
2. Git stages the user's modifications (if not already staged) and
   captures the index + working-tree blob-IDs to be committed.
3. Pre-commit hooks fire in order (per `.pre-commit-config.yaml`).
4. `end-of-file-fixer` runs `pre-commit-hooks`'s `eol_fixer` module
   which may MUTATE the working-tree blob (re-stages after fix).
5. Git finalizes the commit on the (now auto-fixed) index blob.

When step 4 mutates content already staged, the commit's expected
(staged) blob-IDs diverge from the committed (auto-fixed) blob-IDs.
Git silently uses the AUTO-FIXED blob. The user has no audit trail.

---

## §4 — Recommendation: option (i) — file-scope hook exclusion

**Why (i) over (ii)/(iv):**

- **(i) file-scope exclusion** is the SIMPLEST fix. Excluding
  `CHANGELOG.md` from `end-of-file-fixer` makes the hook a no-op for
  the ONLY file that triggers the recurrence. CHANGELOG.md is
  machine-generated (via `cycle_closeout_apply_docs.py`) and the
  trailing-newline invariant is enforced at write-time (the script's
  `+ "\n\n"` rstrip pattern).

- **(ii) race-detector hook** requires writing a custom Python hook +
  maintaining it across pre-commit-config.yaml bumps. More moving parts.

- **(iv) formalize `--no-verify`** is OK as a FINAL fallback if (i) +
  (ii) prove insufficient, but `--no-verify` skips ALL hooks
  (including ruff + mypy) which is undesirable for the slice of the
  close-out workflow where the ruff/mypy gate IS valuable.

**Concrete config diff** (apply to `.pre-commit-config.yaml`):

```yaml
- repo: https://github.com/pre-commit/pre-commit-hooks
  rev: v5.0.0
  hooks:
    - id: check-yaml
    - id: check-json
    - id: check-toml
    - id: end-of-file-fixer
      exclude: ^CHANGELOG\.md$
    - id: trailing-whitespace
```

The `exclude: ^CHANGELOG\.md$` regex is anchored at the repo root (the
`.pre-commit-config.yaml` is at the repo root) and matches the
CHANGELOG.md file at the root. Adding a future `docs/CHANGELOG-*.md`
would require extending the regex.

---

## §5 — Deferral criteria

**Apply M9 (option i) at:**

- **Option α (preferred)**: v0.10.20 cycle startup build. Add the
  config diff in the v0.10.20 mimo-half plan-landing's M9 preparation
  commit. Shipping this BEFORE any v0.10.20 close-out eliminates the
  recurrence for the v0.10.20 mimo-half close-out itself.

- **Option β (fallback)**: v0.10.20 mimo-half close-out pre-mode. If
  the v0.10.20 plan-landing did NOT include the M9 config delta, apply
  it as a separate pre-close-out commit + use the same `--no-verify`
  workaround as v0.10.18.1 + v0.10.19 cycles.

**Do NOT defer M9 to v0.10.21 or later.** The recurrence rate (2 of the
last 2 close-out cycles) is sufficiently high that deferring costs more
than fixing.

---

## §6 — Risk register

1. **`exclude:` regex drift.** If a CHANGELOG-style file is added to a
   different path (e.g., `apps/api/CHANGELOG.md`), the exclusion
   pattern won't match it. Mitigation: review the regex periodically;
   consider `^CHANGELOG\.md$|^.*/CHANGELOG\.md$` for broader coverage.

2. **Other EOF-affected files in future cycles.** The exclusion is
   scoped to CHANGELOG.md ONLY. If the close-out workflow expands to
   include other machine-managed files (e.g., ROADMAP.md if
   `cycle_closeout_apply_docs.py` ever touches it), the exclusion
   pattern must extend. The current hardened script touches ROADMAP.md
   — but it does NOT benefit from EOF exclusion because ROADMAP.md is
   human-curated (not machine-generated).

3. **pre-commit minor-version churn.** `pre-commit-hooks` rev `v5.0.0`
   is the pinned version; if the maintainer bumps to `v6.x`, the
   `exclude:` regex syntax should remain stable but verify the diff
   post-bump.

---

## §7 — Cross-references

- **`.pre-commit-config.yaml`** (config target): `<repo-root>/.pre-commit-config.yaml`.
- **v0.10.18.1 cycle-end audit** (the FIRST observed occurrence):
  `plans/AUDIT-2026-07-13-2ffafc75.md` (search for `--no-verify`).
- **v0.10.19 cycle-end audit** (the SECOND observed occurrence):
  `plans/AUDIT-2026-07-12-cd6e9ad.md` (search for
  "`end-of-file-fixer` auto-fix on CHANGELOG.md caused mid-closeout failure").
- **v0.10.20 cycle-end audit** (would record the M9 resolution evidence).
- **Hardened cycle close-out script** (the workflow whose EOF drift
  this M9 addresses): `apps/api/scripts/cycle_closeout_apply_docs.py`.
- **Smoke test** (verifies the hardened script's invariants):
  `apps/api/tests/test_cycle_closeout_apply_docs.py`.
- **Forward-prep audit for M9**: `plans/AUDIT-2026-07-12-v01020-plan-landing.md`.

---

## §8 — Acceptance criteria

M9 closes when:

1. `.pre-commit-config.yaml` has the `exclude: ^CHANGELOG\.md$` rule
   on the `end-of-file-fixer` hook.
2. Next close-out cycle (v0.10.20 mimo-half OR v0.10.21) does NOT
   require `--no-verify`.
3. CHANGELOG.md's blob-id at commit-time matches the staged blob-id
   (verified via `git diff --staged` mid-pre-commit-hook flow OR by
   inspecting the committed `git show HEAD:CHANGELOG.md | diff - <staged-version>`).
4. `ruff` + `mypy` + other pre-commit hooks continue to run
   (the exclusion is SCOPED to end-of-file-fixer ONLY).

If any of these is unmet, M9 closes via option (iv) instead (formal
`--no-verify` workaround documented + audited).
