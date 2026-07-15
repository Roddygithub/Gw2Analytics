# Cycle release plan — Tour 7 v0.10.25 (F17 frontend rollout)

> **Companion docs:**
> - [F17 plan — Combat Readout UI Rollout](./F17-frontend-rollout.md) — the 12 W.1-W.12 sub-blocks + ownership + done criteria
> - [Cycle release plan — Tour 6 v0.10.24-pre](./RELEASE-v0.10.24-pre.md) — predecessor cycle
> - [Post-release audit — Tour 6 v0.10.24-pre followup](./AUDIT-2026-07-15-v0.10.24-pre-followup.md) — wire-contract widening history
> - [Spike — v0.10.19 combat readout](../docs/v0.10.19-combat-readout-spike.md) — W.1-W.12 sub-block source-of-truth
> - [Design doc — v0.9.0 combat readout](../docs/v0.9.0-combat-readout-design.md) §2 + §3-§6 + §8 + §13 — table contracts + icon licensing + default sort

> **Status:** Plan (post-Tour 6 v0.10.24-pre wire-contract stabilisation; pre cycle authorisation).
> **Branch target:** a fresh `feat/f17-frontend-rollout` branch on cycle authorisation.
> **Shippable in:** v0.10.25 cycle (single cycle; sub-block effort per the F17 §2 + spike §3.4).

## §1 Cycle thread

Tour 7 picks up the F17 frontend deliverable against the Combat-readout wire contract just stabilised by Tour 6 v0.10.24-pre. The wire contract now ships:

- `GET /api/v1/fights/{fight_id}/readout` (`apps/api/src/gw2analytics_api/routes/fights/__init__.py`) returns the `FightReadoutOut` envelope with one `PlayerReadoutOut` per player
- The 5 shared identity columns (`subgroup` + `name` + `account_name: str | None` + `profession` + `elite_spec` + `is_commander`) hydrate from the new `AgentIdentity` Pydantic model + the `agent_id_to_identity` mapper (Tour 6 commit e9d2ba2)
- The `stun_breaks` column on Heal-side is wired end-to-end through the `stun_break_events: Iterable[StunBreakEvent]` dispatcher parameter + the heal aggregator's union-keys row-builder (Tour 6 commit e9d2ba2)
- The `account_name` Lossy truthy `or ""` collapse is REMOVED — the wire preserves the arcdps `None`-vs-`""` distinction (Tour 6 commits 1aebf96 + 5725423)

This cycle ships the F17 W.1-W.12 sub-blocks (per the F17 §2 + spike §3.4) against the now-stable wire. The 4 `PlayerReadout{Damage,Heal,Boons,Defense}.tsx` table skeletons already exist in `web/src/components/` from the Wave 6 PART-2 Tour 5 work; the cycle closes the integration (W.7-W.9) + the test pass (W.10-W.11) + the visual baseline (W.12).

### W.5 dynamic-column audit (the only carry-over from Tour 6's unblock-event note)

The Tour 6 v0.10.24-pre F17 plan status note flagged W.5 (`<PlayerReadoutBoons>` + dynamic 'Autres boons' column expansion per design doc §11 Q3) as `PENDING VERIFICATION` — the file exists but the per-row dynamic-column logic needs a Tour 7 audit pass before the W.5 acceptance criterion is confirmed. Tour 7 starts by auditing the W.5 component:

- **Audit task W.5.A**: read `web/src/components/PlayerReadoutBoons.tsx`, confirm whether the dynamic-column expansion is implemented per design doc §11 Q3 (a) or whether the file ships a static-only fallback per design doc §11 Q3 (b/c); document the answer in a Tour 7 commit
- **If W.5.A is positive (dynamic columns ship)**: W.5 is DONE; no follow-up code needed
- **If W.5.A is negative (static-only ships)**: W.5 ships in the cycle as part of an extension commit; the §11 design lock provides a fallback pattern (a "Top 3 other boons" cell)

The audit pass is a single read + comment-only commit, not a scope lift. The cycle planning budget absorbs this audit task under W.5.

## §2 Cycle-execution checklist (operator handoff)

```
[ ] Step 1: Cycle authorisation (operator signs off the budget for v0.10.25)
[ ] Step 2: git checkout -b feat/f17-frontend-rollout (fresh branch from main post-5725423)
[ ] Step 3: W.5.A audit pass on PlayerReadoutBoons.tsx (single commit)
[ ] Step 4: W.1 — acquire Tango Medium icons into web/public/icons/{professions,specializations}/ (~50 SVGs, single bash script)
[ ] Step 5: W.7 — integrate the readout tab as the default-to-tab on /fights/[id]
            (the analysis tabs are now Combat-readout-first via design §12)
[ ] Step 6: W.8 — TanStack Query cache wiring (reuse fetchCached per v0.10.14 D2 substrate)
[ ] Step 7: W.9 — per-section error chips (reuse v0.10.15 plan 035 unification)
[ ] Step 8: W.10 — New AG Grid component tests (vitest + jsdom)
            add the 4 mock entries for PlayerReadout{Damage,Heal,Boons,Defense}
            per the v0.10.18 d20bdd4 pattern
[ ] Step 9: W.11 — Playwright e2e for the readout tab
            mirror v0.10.18 D3 replay-ui spec precedent
[ ] Step 10: W.12 — visual regression baseline
            8 full-page screenshots; the canonical fixtures fight-001 + fight-002
            as the single baseline; FAIL on diff
[ ] Step 11: Regenerate web types — pnpm openapi-typescript against the running apps/api
            (this re-asserts the manual schema.d.ts edit; the regeneration would overwrite
             the manual # noqa: wire-followup-2026-07-15 marker in schema.d.ts; the marker
             must be removed at regeneration time as it represents a consumed migration)
[ ] Step 12: Ruff + mypy + pytest + vitest + tsc + Playwright all green
[ ] Step 13: git push origin feat/f17-frontend-rollout (no tag — branch review + cycle close-out)
[ ] Step 14: gh release create v0.10.25 after cycle close-out / merge to main
[ ] Step 15: Update ROADMAP Status to v0.10.25 + remove the v0.10.24-pre Status line
```

## §3 Topology

```
pre-cycle: feat/f17-frontend-rollout branch from main post-5725423
           PlayerReadoutBase.ts + 4 PlayerReadout*.tsx table skeletons exist
           BUT /fights/[id] integration is NOT the default tab
           AND W.5 dynamic-column logic is PENDING VERIFICATION
           AND W.1 icons not yet acquired
post-cycle: /fights/[id] defaults to the readout tab per design §12
            W.5 acceptance criterion confirmed (via audit + extension if needed)
            W.1 icons shipped in /web/public/icons/{professions,specializations}/
            vitest + Playwright + visual regression baseline wired into CI
            web types regenerated (the manual schema.d.ts marker removed)
```

ZERO regression on Tour 6 (v0.10.24-pre). ZERO regression on Tour 6 followup (1aebf96 + 5725423). ZERO regression on Tour 5 (v0.10.23-pre). ZERO regression on Tour 4 (v0.10.22).

## §4 Risks + mitigations

1. **W.5 dynamic-column render budget** — the ~34 remaining GW2 boons expanding dynamically could bloat the AG Grid visual column width. *Mitigation:* design doc §11 Q3 fallback (a "Top 3 other boons" cell) applies; the W.5.A audit pass confirms whether the dynamic-column implementation handles the budget concern. Cycle budget absorbs the extension if needed.
2. **regenerated `schema.d.ts` overwrites the `# noqa: wire-followup` marker + the manual `account_name: string | null` widening** — the regeneration is the canonical way to keep schema.d.ts in sync with the Python Pydantic schema. *Mitigation:* Step 11 of the cycle-execution checklist removes the marker as part of the regeneration (it's a consumed migration; the Python schema is now the source-of-truth).
3. **AG Grid v34 Theming API + React 19 compatibility** — the Wave 5 work migrated to the Theming API per the ag-grid-setup.ts module. *Mitigation:* W.10 vitest component tests use the AG Grid v34 jsdom shim per the existing PlayerReadout components' precedent.
4. **Account_name None rendering** — combatants that have `account_name=None` (the Tour 6 widened Optional) cluster as empty-string in the AG Grid cell without a fallback string. *Mitigation:* PlayerReadoutBase.formatName() (a future helper) renders None as `(no account)` symmetric with `(no squad)` for subgroup=0.

## §5 Done criteria (closed when ALL of)

- 4 PlayerReadout{Damage,Heal,Boons,Defense}.tsx tables rendered with the 5 SHARED_COLUMNS + the aspect-specific columns
- The 8 SCAFFOLD-zero columns in the `readout-tab-status` banner have been pruned (tied to the WAVE-8 backend DONE; the banner mutates from the current long footnote to a concise "Combat readout loaded · N players · duration X.X s.")
- The default sort (`subgroup ASC` + per-table tiebreaker from design doc §13) is locked
- Vitest component tests + Playwright e2e + visual regression baseline all green in CI
- Re-generated `schema.d.ts` consumes the manual `# noqa: wire-followup` marker
- The W.5.A audit pass documents the dynamic-column acceptance criterion

The readout tab becomes the canonical "what did each player do in this fight" surface for analysts, replacing the manual cross-reference of per-target + per-skill + per-bucket-window views (per design doc §0).

## §6 Counterpart documents (TODO, complementary to THIS plan)

- [Tour 6 v0.10.24-pre audit](./AUDIT-2026-07-15-v0.10.24-pre.md) — parent cycle audit
- [Tour 6 v0.10.24-pre followup audit](./AUDIT-2026-07-15-v0.10.24-pre-followup.md) — wire-contract widening history
- [WAVE-8 plan](./WAVE-8-parser-side.md) — the v0.11.0 successor parser-stream + Skills DB workstream
- [WAVE-8 release plan (draft)](./RELEASE-v0.11.0-wave-8-parser.md) — the v0.11.0 release plan
- [BLOCKER-C role classifier plan](./BLOCKER-C-role-classifier.md) — the role-classifier follow-up after Blocker C is unblocked by Tour 7

*Owner sign-off required before cycle authorisation:* (the F17 frontend cycle assignee, separate role from this plan's author).
