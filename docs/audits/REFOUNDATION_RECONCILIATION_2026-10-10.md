# Refoundation reconciliation — 2026-10-10

Record of the preservation + reconciliation gates performed before any
destructive cleanup, and the decisions that drive the `refactor/ei-foundation`
candidate branch.

## Baseline

| Item | Value |
| --- | --- |
| Owner HEAD (dirty) | `346ee279` on `reconcile/ei-certification` |
| Published default | `origin/main` = `d83e0e363d36a536b4e824dd7e2b6fcb61668d08` |
| Local `main` | `cfccc5d` (merge-base `175f1f7`, 22 ahead / 68 behind `origin/main`) |
| Audit report | `origin/audit/ei-migration-baseline` = `231550a` (report only) |
| Canonical base for the refoundation | `origin/main` |

Local `main` is not the publication base: its 68 "missing" commits are the live
product line, and its 22 unique commits are largely a less-refined duplicate of
the EI/parser semantics plus a handful of genuinely unique product changes.

## Preservation (Phase 0, hard gate)

Verified recovery root outside the repository:
`/home/roddy/Projects/Gw2Analytics-recovery/20261010-032644`

- full `.git` copy (all objects, reflogs, stash, worktree metadata);
- 128-ref `git bundle` of `refs/*`, restore-verified in a clean repo
  (116 refs, 11 775 objects);
- per-worktree `status`/`diff`/staged/untracked manifests, plus copies of every
  untracked artifact (including the 441 MB `ei_report*.json`);
- both stashes exported as patches with base commits;
- the temporary audit `AGENTS.md` and its diff preserved before replacement;
- 35-log certification set SHA-256 manifests (50 596 242 bytes total);
- EI tooling identity (`ei-src` `e4e548bf…`, `GW2EICLI-v3.26.0.0.zip`);
- no live PostgreSQL/MinIO/Redis instance exists on this host, so no DB backup
  was fabricated.

See the recovery root's `RECOVERY_MANIFEST.md` for the full inventory.

## Commit / patch equivalence (MAJ-1)

Patch-id (`--stable`) equivalence between the two lanes:

- `e0e4b4f` (local main) == `dbfc2f6` (reconcile lane) — same work.
- `cfccc5d` (local main) == `446823e` (reconcile lane) — same work.
- Sibling commits with the same title but **different** patch-ids (do not treat
  either as superseding the other): `5d2d154` vs `97d7ea0`, `43751e3` vs
  `34573c0`, `45b3d4c` vs `0df8edd`, `18f9d36` vs `8e7b74f`.
- Genuinely unique local-main product work integrated here: defense counters,
  web fonts/readout memo, coverage CI, security docs.

The EI/uptime semantic refinement chain lives on `reconcile/uptime-semantics`
and `rework/wave6-uptime-f7e73e5` (the shared 14-commit chain plus uptime
refinements). See the regeneration decision below.

## Database lineage (MAJ-2)

`0017_player_defense_events` already adds `blocked` / `dodges` / `interrupts`
to `fight_player_summaries` and is present at the merge base **and** on
`origin/main`. Local main's `0022_player_summary_defense_actions` re-added
`dodges` / `interrupts` to the same table and therefore **could not apply on
top of `0017`** — a broken migration.

Resolution: keep `0017` untouched; rewrite `0022` as a forward-only
reconciliation that renames the unused legacy `blocked` column to the product
name `blocks` and only adds what is genuinely missing. The migration is
reversible (`alembic downgrade -1` renames back). Alembic now reports a single
head (`0022`).

A duplicated select-label defect inherited from the source branch was also
fixed in the per-account aggregate query.

## Regeneration / buff_state (three-way)

Three mutually inconsistent, mutually unverified proposals existed:

1. dirty owner-root `buff_state.py` (regeneration queue extension rework);
2. dirty uptime-worktree `buff_state.py` (QueueLogic.Activate semantics);
3. the committed certified lineage (`reconcile/uptime-semantics`,
   `rework/wave6-uptime-f7e73e5`).

Decision: adopt (3) — the committed, tested, EI-3.26-tagged lineage. (1) and (2)
are preserved in the recovery root and are **not** applied mechanically, because
they change product semantics without EI re-certification. This remains an open
item for the final reviewer.

## Not integrated (deliberately)

- The parser-semantic commits (`5d2d154`, `43751e3`, `cc06de7`, `18f9d36`,
  `45b3d4c`) that only refine the home-grown parser, which the EI migration
  removes.
- The two unverified dirty regeneration proposals (see above).
- The dependency/CI branches (`dep-audit/*`, `fix/codecov-*`,
  `maintenance/ci-security-baseline`, `compose/minio-official-pin`) — their
  intent is already represented on `origin/main`; `git cherry` and patch-id
  comparison show no unmerged product need.
