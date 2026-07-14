# F17 Combat Readout UI Rollout (AG Grid frontend)

> **Companion docs:**
> - **Upstream Plan:** [`plans/WAVE-8-parser-side.md`](WAVE-8-parser-side.md) — scopes the Blocker A + B backend parser logic that feeds these tables via the SCAFFOLD-zero contracts.
> - **Spike:** [`docs/v0.10.19-combat-readout-spike.md`](../docs/v0.10.19-combat-readout-spike.md) — scopes F17 execution sizes (W.1-W.12 frontend implementation sub-blocks).
> - **Design:** [`docs/v0.9.0-combat-readout-design.md`](../docs/v0.9.0-combat-readout-design.md) — canonical table attributes, default sorting, and UI heuristics.

> **Status:** Plan (post-v0.10.19 spike; post Wave 8 backend scope; pre v0.10.22 cycle authorisation).
> **Branch target:** a fresh `feat/f17-frontend-rollout` branch on cycle authorisation (lands AFTER the Wave 8 backend reaches DONE).

## §0 Scope + ownership

> **Cross-references:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) (F17 cycle topology) + the upstream provider [`plans/WAVE-8-parser-side.md`](WAVE-8-parser-side.md) + the spec [`docs/v0.9.0-combat-readout-design.md`](../docs/v0.9.0-combat-readout-design.md).

This plan details the F17 frontend delivery workstream (W.1-W.12 from the spike doc §3 Web section), a separate downstream cycle from Wave 8 backend. Ownership belongs entirely to the `web/` stream — AG Grid component mapping + state lifecycle + icon acquisition + visual regression baseline are independent of parser progression. The frontend safely navigates complex component rendering alongside the SCAFFOLD-zero column contract — the UI shapes ship unbroken while specific metrics wait for their upstream Blockers to reach DONE.

The frontend rollout cycle is **XL+ effort** (~2500 LoC web-only with the spike §3 estimates). Cycle topology per the spike §4:

- **v0.10.22** (or whenever Wave 8 backend is DONE): ship W.1-W.12 in 1 cycle.
- **v0.10.23**: maintenance cycle (role-threshold calibration + cosmetic tweaks per the spike §9 step 3 cadence).

## §1 Design contracts (verbatim from design doc §2 + §3-§6 + §8 + §13)

The 4 tactical layouts require a strict wrapper component to guarantee consistency + minimize AG Grid configuration boilerplate.

**Shared Base (5 stable columns via `<PlayerReadoutBase>`):**

The wrapper component injects 5 strict identity columns to the left-pane side of all tables (per design §2):

1. **Sub-groupe** — `OrmAgent.subgroup` (integer → label mapping: `1` → "Sub 1", `2` → "Sub 2", ...).
2. **Nom du personnage** — `OrmAgent.name` (string).
3. **Spécialisation jouée** — `PlayerProfile.elite_spec` (or `profession` if no elite); rendered with the Tango Medium icon (per design §8).
4. **Icône commandant** — `OrmAgent.is_commander`; Crown icon, only when the flag is set.
5. **Rôle(s) du joueur** — `roles: list[str]`; multi-role set (e.g. `["DPS", "STRIP"]`); backend-computed by the §3.1 heuristic.

**The 4 Specific Tables (per design §3-§6):**

- **`<PlayerReadoutDamage>`** — DPS total (with power/condi splits), Strips, CC appliqués, Down contribution, Kills (§3 Table 1).
- **`<PlayerReadoutHeal>`** — Heal/Barrier totals (per-s breakdown), HPS + Barrier/s, horizontal relative squad-contribution bars, Cleanses, Breakstunt (§4 Table 2).
- **`<PlayerReadoutBoons>`** — 6 fixed columns (Stability + Alacrity + Resistance + Aegis + Superspeed + Stealth) + **Dynamic "Autres boons"** columns; per design §11 Q3, the ~34 remaining boons expand dynamically as discrete AG Grid columns based on the backend fight payload (§5 Table 3).
- **`<PlayerReadoutDefense>`** — Damage reçu, CC reçus, Deaths, Time on ground (ms format), Dodges, Blocks, Interrupts, Barrier absorbed (§6 Table 4).

**Icon Source (per design §8):** Tango Medium from the official wiki. Two asset sets:

- 9 core profession icons → `web/public/icons/professions/`
- ~30 elite spec icons → `web/public/icons/specializations/`

Naming convention: `Profession_<name>_tango.png` + `Specialization_<name>_tango.png`. Acquisition is a 50-line Node spike that downloads the icons once; committed to the repo (re-run only if ArenaNet updates the icon set).

**Default Sorting Strategy (per design §13):**

Every table forces `subgroup ASC` grouping as the primary sort key (mirrors standard WvW squad-centric mental models). Secondary tiebreakers differ per domain:

- *Damage:* `dps DESC`
- *Heal:* `hps DESC` (= `heal/s + barrier/s`)
- *Boons:* `boon_out_rate DESC` (= `boons_applied / duration_s`)
- *Defense:* `damage_taken DESC`

Standard AG Grid header attributes apply — analysts can re-sort by single-click on any column header.

## §2 Sequencing

12 sub-blocks from the spike doc §3 Web section (each reflinks the spike's full description + effort):

1. **W.1** Acquire Tango Medium icons (~40 SVGs into `web/public/icons/{professions,specializations}/`). Effort: **S**. Reflink spike §3.4 W.1.
2. **W.2** `<PlayerReadoutBase>` wrapper component (the 5 shared columns). Effort: **M**. Reflink spike §3.4 W.2.
3. **W.3** `<PlayerReadoutDamage>` AG Grid table. Effort: **L**. Reflink spike §3.4 W.3.
4. **W.4** `<PlayerReadoutHeal>` AG Grid table. Effort: **L**. Reflink spike §3.4 W.4.
5. **W.5** `<PlayerReadoutBoons>` AG Grid table + dynamic "Autres boons" column. Effort: **XL**. Reflink spike §3.4 W.5 (the most-complex table).
6. **W.6** `<PlayerReadoutDefense>` AG Grid table. Effort: **L**. Reflink spike §3.4 W.6.
7. **W.7** Integrate into `/fights/[id]` (default to the new tab per the §12 Notes recommendation). Effort: **M**. Reflink spike §3.4 W.7.
8. **W.8** TanStack Query cache wiring (reuse `fetchCached` per v0.10.14 D2 substrate). Effort: **S**. Reflink spike §3.4 W.8.
9. **W.9** Per-section error chips (reuse v0.10.15 plan 035 unification). Effort: **S**. Reflink spike §3.4 W.9.
10. **W.10** 5+ AG Grid component tests (vitest + jsdom). Effort: **M**. Reflink spike §3.4 W.10.
11. **W.11** Playwright e2e for readout tab (mirrors v0.10.18 D3 replay-ui spec precedent). Effort: **M**. Reflink spike §3.4 W.11.
12. **W.12** Visual regression baseline (mirror v0.10.14 D3 refresh precedent + 8 full-page screenshots). Effort: **S**. Reflink spike §3.4 W.12.

**Order:** W.1 (icons) → W.2 (base wrapper) → W.3-W.6 (4 tables, in parallel branches) → W.7-W.9 (page integration + cache + error chips) → W.10-W.11 (vitest + Playwright) → W.12 (visual baseline close-out).

## §3 Migration impact (cross-ref to Wave 8 §5)

This plan's §3-§6 + W.5-W.7 implementation **encodes** the Wave 8 backend §5 column-prune contract: when a Wave 8 Blocker reaches DONE, the corresponding SCAFFOLD-zero column lights up in the AG Grid tables.

For each Blocker-DONE column unlock, the migration is **3 small edits** (per the Wave 8 §5 contract):

1. `web/src/app/fights/[id]/page.tsx` — the `readout-tab-status` Banner prunes the column from the inline `SCAFFOLD-zero` list (~+1/-1 line per column).
2. `web/src/components/PlayerReadout{Damage,Heal,Defense}.tsx` — the AG Grid `valueGetter` flips from `() => 0` (SCAFFOLD-zero stub) to `(params) => params.data.<path>` (R.1-R.4 already wired from spike Bl C).
3. `web/tests/e2e/fights.spec.ts` — add a Playwright spec asserting the unlocked cell renders a non-zero value for a known fixture fight; the readout payload fixture in `tests/e2e/mock-server.mjs` is updated to include the column's wire value.

Net: ~5 LOC per column × 8 columns = **~40 LOC web-side** spread across 8 incremental PRs (1 PR per column-unlock, not 1 monolithic "F17 ships").

## §4 Risks + mitigations

1. **Tango Medium icon licensing** (W.1) — ArenaNet's wiki Terms of Use. *Mitigation:* acceptable for personal analytics project (community precedent: gw2efficiency + discretize + snowcrows). If project ever goes public, switch to `Special:FilePath` at render time instead of bundled SVGs (design §8).
2. **AG Grid bundle size** (W.3-W.6) — 4 tables × full AG Grid Community may bloat the bundle. *Mitigation:* code-split the readout tab (`tab=readout` is loaded on-demand, not in the initial bundle for the Overview tab).
3. **Dynamic "Autres boons" rendering** (W.5, per design §11 Q3) — locked default is dynamic columns; the W.5 calibration phase tunes against real fights. *Mitigation:* the §6 design lock provides a fallback (a "Top 3 other boons" cell) if dynamic-column rendering overwhelms the AG Grid visual budget.
4. **Visual regression baseline** (W.12) — 4 tables × multiple analysts = diverse baselines. *Mitigation:* use the canonical fixtures (`fixture-fight-001`, `fixture-fight-002`) as the single baseline; per-analyst acceptance via PR review (existing v0.10.14 D3 visual-regression spec precedent).
5. **AG Grid runtime in jsdom** (W.10 component-level tests) — full AG Grid bootstrap needs a real DOM + canvas. *Mitigation:* the existing `web/tests/setup.ts` global mocks (`FightsGrid`, `TargetRollupsGrid`, `SquadRollupsGrid`, `SkillUsageTable`) already absorb AG Grid runtime; add the 4 `PlayerReadout{Damage,Heal,Boons,Defense}` mocks as needed (the v0.10.18 d20bdd4 regression lock established the pattern).

## §5 Done criteria

F17 frontend rollout is DONE when, cumulatively:

- All 4 AG Grid tables (Damage / Heal / Boons / Defense) render with the 5 shared columns + the table-specific columns.
- The 8 SCAFFOLD-zero columns in the `readout-tab-status` banner have been pruned in `web/src/app/fights/[id]/page.tsx` (tied to Wave 8 backend DONE; the banner mutates from the current long footnote to a concise "Combat readout loaded · N players · duration X.X s." without any column-pruning footnote).
- The default sort (subgroup ASC + per-table tiebreaker from design §13) is locked; column headers allow analyst re-sort via AG Grid click.
- Playwright e2e (W.11) covers the happy-path + at least one Blocker-DONE state (where at least 1 of the 8 SCAFFOLD-zero columns renders a non-zero wire value).
- Visual regression baseline (W.12) is wired into the CI flow (post-merge); FAIL on diff against the canonical fixtures.

The readout tab becomes the canonical **"what did each player do in this fight"** surface for analysts, replacing the manual cross-reference of per-target + per-skill + per-bucket-window views.

## §6 Counterpart documents + cross-references

- **Upstream provider:** [`plans/WAVE-8-parser-side.md`](WAVE-8-parser-side.md) — the backend parser + Skills DB workstream (Bl A: statechange extension; Bl B: Skills DB catalog).
- **Parallel dev work:** [`plans/BLOCKER-C-role-classifier.md`](BLOCKER-C-role-classifier.md) — the role-classifier implementation per the spike doc §2 Blocker C (calibration phase, after R.1-R.4 are stable). TODO if absent (separate scope from THIS plan).
- **Source-of-truth sub-block descriptions + Effort tags + cycle topology:** [`docs/v0.10.19-combat-readout-spike.md`](../docs/v0.10.19-combat-readout-spike.md) §3 (F17 impl sub-blocks W.1-W.12).
- **Table contracts + icon-licensing decision + default sort:** [`docs/v0.9.0-combat-readout-design.md`](../docs/v0.9.0-combat-readout-design.md) §2 + §3-§6 + §8 + §13.
- **Cycle position + cross-cycle dependencies:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) §1.1.

*Owner sign-off required before cycle authorisation:* (the F17 frontend cycle assignee, separate role from this plan's author).
