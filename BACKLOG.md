# Backlog — parser / Elite Insights parity

Measured with `uv run python scripts/ei-parity/ei_diff.py` over the 35-log corpus.
Setup and probes: `docs/ei-parity-workbench.md`. Findings so far:
`docs/parser-audit-2026-07-31.md`.

**Scoreboard: 4 503 → 1 116 differences** over the 35-log corpus (2026-08-04).
Split evenly across the wire-format break: 620 over the 21 pre-2026-05 logs,
496 over the 14 post-2026-05 ones, so neither era is systematically worse. No
log is at exactly 0 yet.

| Log | 2026-07-31 | now |
| --- | ---: | ---: |
| `20260424-204954` | 2 202 | 170 |
| `20260526-202841` | 903 | 142 |
| `20260506-211522` | 89 | 83 |
| `20260224-233019` | 674 | 70 |
| `20260610-212627` | 2 328 | 62 |
| `20260125-194936` | 198 | 60 |

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

## Next

- [ ] **`rotation` (424)** — largest bucket. `gw2_analytics/rotation.py`
      reimplements EI's `InstantCastFinder` set from GUID tables and still
      misses a long tail of sigil / rune / trait procs. Needs a systematic
      extraction from the EI sources, not diff-by-diff additions.
- [ ] **`buffUptimes` (363)** — no longer slice-related (see ruled-out above).
      Needs its own investigation: compare a single-entry player's uptime
      against EI's own `buffUptimesActive` and check the denominator EI uses.
- [ ] **`consumables` (58)** — a mix of the +1 ms offset on some entries and
      entries we never emit at all. `extract_initial_buffs` is only used by
      `ei_compare` and its own test, so it can be changed freely.
- [ ] **Refresh the visual-regression baselines on Linux.** #121 moved the
      player profile by 86 px, so `06-player-profile-with-timeline.png` and
      `07-player-empty-timeline.png` are stale. macOS Chromium does not
      reproduce the committed captures (it also fails `01-landing.png` and
      `08-fight-drilldown.png` untouched), so this must run on Linux:
      `cd web && UPDATE_BASELINES=1 pnpm exec playwright test --project=visual-regression`.
      Baselines live in `docs/screenshots/`.
- [ ] **Render the 28 per-fight boon columns.** They now reach the client
      (#121) but nothing displays them; 28 extra table columns needs a design.
- [ ] **Old: per-target over-attribution on pre-2026-05 logs** — biggest remaining
      cluster (`20260424-204954`, `20260526-202841`, `20260224-233019`,
      `20260412-220632`, `20260125-194936`). Every `statsTargets` /
      `dpsTargets` counter reads high while `statsAll` matches exactly, so
      the same event is being booked against more than one target.
      Already ruled out: duplicate `instanceID`s in EI's target list (none),
      and an awareness-window filter on `firstAware`/`lastAware` (no effect —
      the candidate agents' windows all overlap). Also confirmed the fix is
      not to narrow back to one agent per instance: that regresses these logs
      further (`20260224` 682 → 3 205) and undoes the `20260129` gain
      (69 → 769). Next step is to dump, for one over-counted (player, target)
      pair, exactly which events we include that EI does not.
- [ ] **Recorder-agent surplus on `20260125-194936`** — for
      `krill le faucheur.1679` skill 9107 we emit 28 records where EI reports
      16 hits. Most of the surplus carries `is_offcycle = 1` (the parser reads
      that as "against a downed target") at distinct timestamps, so they are
      not literal duplicates. Reproduce with
      `scripts/ei-parity/probe_raw_events.py 20260125-194936 "krill le faucheur.1679" 9107`.
      May be the same root cause as the item above.
- [ ] **`overstack_value` on direct-damage records** — on the same log a
      direct hit carries `overstack = 2265124730`, which is not a barrier
      amount. `shield_damage` currently only guards against the INT32_MAX
      sentinel, so a garbage value just under the cap would leak through.
      Nothing compares `shieldDamage` yet, so this is latent, not live.
- [ ] **Instant-cast synthesis** (`rotation`) — `gw2_analytics/rotation.py`
      reimplements EI's `InstantCastFinder` set from GUID tables. Still
      missing entries; EI maintains hundreds. Needs a systematic extraction
      from EI rather than one-at-a-time diffing.
- [ ] **`againstDowned*` / `downContribution`** — small residual, concentrated
      in a few logs.
- [ ] **Boon uptime residuals** — mostly ±0.001-0.05 rounding, plus a handful
      of real gaps. Check EI's rounding and its handling of a player who is
      not present for the whole fight.
- [ ] **`consumables`**, **`defenses.deadCount`**, **`teamID`** — single-digit
      residuals.

## Test-suite hygiene

- [ ] `test_parser_multilog_corpus.py` and `test_parser_dps_report_golden.py`
      point at `/home/roddy/...` and skip everywhere else. Move to a small
      committed fixture so they actually run in CI.
- [ ] Replace `assert len(differences) <= N` with exact-match assertions on
      the buckets already at zero. A ratcheting threshold cannot distinguish
      "fixed" from "not yet broken enough to notice".
- [ ] `apps/api` webhook tests need a live Postgres and error out locally.
      Either mark them `integration` or provide a compose target.
