# Backlog — parser / Elite Insights parity

Measured with `uv run python scripts/ei-parity/ei_diff.py` over the 35-log corpus.
Setup and probes: `docs/ei-parity-workbench.md`. Findings so far:
`docs/parser-audit-2026-07-31.md`.

**Scoreboard: 690 differences** over the 35-log corpus (2026-08-04).
Per-session history in `SESSION.md`.

Trajectory: 23 830 (2026-07-31 audit) → 4 503 → 1 116 → 798 → 711 → **690**.

Note the "0 diffs corpus-wide" figure quoted in #117/#118 was measured over 20
logs. The committed corpus is 35; always run the harness with no arguments.

## Done (2026-07-31)

- [x] Reproducible local EI ground truth (EI 3.26.0.0 CLI + .NET 8, offline)
- [x] Stratified 35-log corpus spanning ten arcdps builds
- [x] Correct elite-spec catalogue (`EliteSpec`, `_VALID_ELITE_BY_PROFESSION`)
- [x] Anonymized enemy names compared in English, not the client's language
- [x] Drop the fabricated `result = 13` on zero-magnitude condition ticks
- [x] Decode the condition `result` enum per arcdps era (2026-05-07 rebase)
- [x] Read `overstack_value` (barrier absorption / EI `shieldDamage`)
- [x] Fold the 2026-05-07 buff statechanges (69 / 71 / 72) back onto the
      apply/remove path — boon uptimes were ~0 on every recent log
- [x] Fold the 2026-05-07 cast statechanges (67 / 68) back onto the
      activation path — rotations were missing every non-instant cast
- [x] Resolve an EI target to every agent sharing its instance ID
- [x] Split condi/power by EI's buff classification, not the arcdps channel

## Done (2026-08-04)

- [x] **Root cause of the per-target over-attribution** (#120). EI emits one
      player entry per *contiguous stretch of squad membership*, not one per
      player: an account appears several times with adjacent firstAware /
      lastAware windows and a different `group` on each, and every counter on
      an entry covers only that stretch. Each entry is now compared against
      its own slice of the event stream. 4 503 → 1 140.
- [x] Consumables are no longer sliced (#120 follow-up) — they are pre-fight
      applications EI repeats on every entry. 1 140 → 1 116.
- [x] postcss raised past GHSA-fxqj-rqcc-2cmp (#119). The `overrides` pin in
      `web/pnpm-workspace.yaml` was itself what blocked Dependabot.
- [x] Buff simulation stops at an actor's last-aware (#130). 798 → 779.
- [x] Down-contribution row sliced per EI entry (#132). 779 → 711.
- [x] `teamID` reported only on an account's last entry (#134). 711 → 690.
- [x] Backend→frontend drift check (#121). `PlayerProfile` was missing
      `boon_strips` / `condition_cleanses`; `PerFightBreakdownRow` was missing
      28 more. `scripts/ei-parity/api_coverage.py` now guards both directions.

## Ruled out — do not retry

- **Windowing buff uptimes per slice.** EI reports the same whole-fight
  `buffUptimes` on every entry of a split account; slicing them takes buff
  differences from 225 to 913 on the four logs that have splits.
- **Subtracting two `BuffStateTracker` readings** to get stack-time inside a
  window. The tracker only moves forward, so both readings taken after the
  full feed return the same total. Replaying per window computes the window
  correctly and still diverges, because the target is whole-fight.
- **Shifting consumable timestamps by +1 ms.** 39 mismatching entries are
  short by exactly 1, but most entries already agree, so the blanket shift
  takes consumables from 39 to 95.
- **Narrowing a target back to one agent per instance.** Regresses
  `20260224` from 682 to 3 205.

## Next (2026-08-04, in impact order)

- [ ] **`players.rotation` (366)** — by far the largest bucket, now
      characterised (see `SESSION.md`). 1 012 casts missing against 339 extra;
      three `isInstantCast` skills carry 246 of the missing — **77370 Zap
      (123)**, **9084 "Advance!" (68)**, **5535 Cleansing Fire (55)** — and
      skill **30961 (Exit Reaper's Shroud)** is 45 missing + 45 extra, i.e. the
      right cast 1-2 ms late (not a constant offset, so no blanket shift).
      Start from the three finders, then the timing anchors.
- [ ] **`buffUptimes` (185)** — 120 of the pre-session 204 were Regeneration.
      Note the brief's premise is wrong: EI is *lower* in 80 cases and higher in
      40, median |delta| 0.053, and only 32 of 204 exceed 2. Port EI's
      `HealingLogic` (`BuffStackType.Regeneration`, capacity 5) faithfully:
      `Activate` / `FindLowestValue`, replace by overrideStackID, else min
      |TotalDuration - overrideDuration|, else last. Validate with
      `scripts/ei-parity/probe_buff_ei.py` on one player before the corpus.
- [ ] **`statsTargets.againstDownedCount` (24) + `statsTargets.downContribution`
      (22)** — the per-target rows already slice their inputs, so this is a
      different cause from the `statsAll` one fixed in #132. Dump the events we
      include that EI does not.
- [ ] **`statsTargets.downContribution` residual** — one narrow case found and
      left: on `20260129-110256`, target inst 7121 (`Firebrand pl-7121`) has
      `downCount=1` yet EI credits **zero** down-contribution to it from any
      player, while we credit six. It is the only target in that log with
      `downCount > 0` and no contribution, so it is an edge case rather than a
      rule.
- [ ] **`group` (7)**, **`consumables`**, float residuals — long tail.

## Still open from earlier passes

- [ ] **Refresh the visual-regression baselines on Linux.** #121 moved the
      player profile by 86 px, so `06-player-profile-with-timeline.png` and
      `07-player-empty-timeline.png` are stale. macOS Chromium does not
      reproduce the committed captures, so this must run on Linux:
      `cd web && UPDATE_BASELINES=1 pnpm exec playwright test --project=visual-regression`.
      Baselines live in `docs/screenshots/`.
- [ ] **Render the 28 per-fight boon columns.** They reach the client (#121)
      but nothing displays them; 28 extra table columns needs a design.
- [ ] **Recorder-agent surplus on `20260125-194936`** — for
      `krill le faucheur.1679` skill 9107 we emit 28 records where EI reports
      16 hits. Most of the surplus carries `is_offcycle = 1` at distinct
      timestamps, so they are not literal duplicates. Reproduce with
      `scripts/ei-parity/probe_raw_events.py 20260125-194936 "krill le faucheur.1679" 9107`.
- [ ] **`overstack_value` on direct-damage records** — a direct hit carries
      `overstack = 2265124730`, which is not a barrier amount. `shield_damage`
      only guards the INT32_MAX sentinel, so garbage just under the cap would
      leak. Nothing compares `shieldDamage` yet, so this is latent.
- [ ] **`consumables`** — a mix of a +1 ms offset on some entries and entries
      we never emit. `extract_initial_buffs` is used only by `ei_compare` and
      its own test, so it can be changed freely.

## Test-suite hygiene

- [ ] `test_parser_multilog_corpus.py` and `test_parser_dps_report_golden.py`
      point at `/home/roddy/...` and skip everywhere else. Move to a small
      committed fixture so they actually run in CI.
- [ ] Replace `assert len(differences) <= N` with exact-match assertions on
      the buckets already at zero. A ratcheting threshold cannot distinguish
      "fixed" from "not yet broken enough to notice".
- [ ] `apps/api` webhook tests need a live Postgres and error out locally.
      Either mark them `integration` or provide a compose target.
