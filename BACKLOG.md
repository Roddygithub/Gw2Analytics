# Backlog — parser / Elite Insights parity

Measured with `uv run python scripts/ei-parity/ei_diff.py` over the 35-log corpus.
Setup and probes: `docs/ei-parity-workbench.md`. Findings so far:
`docs/parser-audit-2026-07-31.md`.

**Scoreboard: 583 differences** over the 35-log corpus (2026-08-06).
Per-session history in `SESSION.md`.

Trajectory: 23 830 (2026-07-31 audit) → 4 503 → 1 116 → 798 → 711 → 690 →
644 → 635 → 632 → **583**.

`rotation` is reported twice: a bucket count of player *rows*, and the cast
counts under the total. Judge any rotation change on the casts — a partial
finder can degrade the data while leaving the row count untouched.

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

## Done (2026-08-06)

- [x] **Four instant-cast finders transcribed from EI's sources**, each
      verified exact over the corpus before being wired: 9084 "Advance!"
      (self-aegis 20–40 s), 5535 Cleansing Fire (by-dst + two secondary
      effects), and the four Evoker familiar skills (credited to the
      owner). 266 casts recovered, 0 introduced. 690 → 644.
      `scripts/ei-parity/probe_ei_finders.py` scores a candidate rule.
- [x] `SkillActivationEvent` carries `src_master_instid`, so a familiar's
      cast can be credited to its owner without re-attributing the cast.
- [x] **Three missing engineer kits** (Bomb 5812, Tool 5904, Grenade 6020).
      EI declares seven `EngineerKitFinder`s and reads each bundle off
      `/v2/skills`; we had four. 644 → 641.
- [x] **30961 Exit Reaper's Shroud** now fires only on a full removal and
      lands at `min(swap - 1, time)`, matching `BuffLossCastFinder` +
      `UsingBeforeWeaponSwap`. 45 fixed on each side. 641 → 635.
- [x] **`UsingNoAnimatedCastChecker` ported properly** for the guardian
      symbol traits (13684, 13677) — a cast-*window* test, not "a cast is
      open right now". 19 spurious casts dropped.
- [x] **`BuffStackActiveEvent` now reaches the buff tracker.** The
      `Activate` path existed but `ei_compare` never delivered the events,
      so regeneration's queue was never reordered. 185 → 141 buff diffs.
- [x] **The two `Activate` overloads separated.** Only the explicit
      stack-active record gets EI's richer rule (replace a nearly-spent
      active stack, pin `noSort`); an `addedActive` apply just moves its
      stack to the front. `noSort` is now tracker-wide, matching EI's
      shared static `HealingLogic`.
- [x] **Base attunement skills are no longer booked for a Weaver.** EI books
      weaver dual-attunement swaps as separate skills and never the base
      one; confirmed corpus-wide on all four elements. 36 spurious casts
      dropped.

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
- **Emitting 9084 "Advance!" for every guardian shout effect with fewer than
  five self-stabilities.** Only 29 of 70 such effects are real casts; the other
  41 become false positives. Corpus 690 → 726 (8 fixed, 44 introduced). The
  50 ms instant-cast ICD does not absorb them. *Superseded 2026-08-06*: the
  real rule is a self-applied aegis of 20 to 40 seconds, and it is exact.
- **Deriving an `InstantCastFinder` by correlation.** Three attempts failed
  the same way: a trigger that *covers* every cast is not one that fires
  *only* on casts, and a single log cannot tell them apart. Both triggers
  found this way were wrong on inspection of EI's sources — 77370 Zap is a
  minion finder, not `BoonApplyEvent 76639`. Read the rule from
  `.tooling/ei-src`, then verify it with `probe_ei_finders.py`.

## Next (2026-08-06, in impact order)

- [ ] **`players.rotation` (308 rows / 668 casts missing, 215 extra)** — still
      the largest bucket, and the method is now settled: transcribe the finder
      from `.tooling/ei-src` (a shallow sparse clone of
      `baaron4/GW2-Elite-Insights-Parser`, MIT), then verify it with
      `scripts/ei-parity/probe_ei_finders.py` before wiring anything. Adding a
      rule to that probe is a few lines. Current heads of the distribution:
      **29560 Spiteful Spirit** (30) is the head of the missing side and is
      **not** explained by either of its two declared finders — see
      `SESSION.md`; it needs a path outside `NecromancerHelper`.
- [ ] **Weaver dual-attunement swaps.** EI books sixteen of them as their own
      skills: `DualFireAttunement` (43470) and its three siblings carry real
      ids, the twelve mixed ones carry synthetic negative ids (-5 through
      -20, see `SkillIDs.cs`). It derives them from the pair of attunement
      buffs a weaver holds (`WeaverHelper.GetLastAttunement`). We now drop
      the base-attunement casts for weavers rather than mislabel them, so
      these sit squarely in the missing column.
- [ ] **`buffUptimes` (136)** — 67 are Regeneration, 24 of them under 0.1.
      The queue model is confirmed correct (a plain FIFO replay of
      `Ver.5187` on `20260526-202841` lands at 81.839 % against EI's
      81.941 %); the residual is the **eviction victim** once `Activate`
      reorders the queue — the same player through the tracker gives
      66.668 %. Next step: instrument which stack each model evicts on that
      player's three capacity-5 overflows. Blocked input, and a parser-level
      gap: `parse_events` drops every uncredited regeneration remove-single
      (`iff == 2 and dst_agent == 0`, 594 of them on that log). EI drops
      them from the simulation too but keeps the last one to drive
      `FindLowestValue` — an apply within 10 ms replaces the stack carrying
      that buff instance, else the one with the closest duration. That
      override cannot be written until the records reach the analytics
      layer. The rest of the bucket: might 23, swiftness 13, stability 9.
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
