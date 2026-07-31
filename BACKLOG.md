# Backlog — parser / Elite Insights parity

Measured with `uv run python scripts/ei-parity/ei_diff.py` over the 35-log corpus.
Setup and probes: `docs/ei-parity-workbench.md`. Findings so far:
`docs/parser-audit-2026-07-31.md`.

**Scoreboard: 23 830 → 5 941 differences** (2026-07-31). 24 of 35 logs are
under 100; five carry two thirds of what is left:

| Log | Before | After |
| --- | ---: | ---: |
| `20260424-204954` | 3 052 | 2 217 |
| `20260526-202841` | 1 480 | 905 |
| `20260224-233019` | 3 210 | 682 |
| `20260412-220632` | 319 | 305 |
| `20260125-194936` | 223 | 210 |
| `20260610-212627` | 2 328 | 48 |
| `20260314-234454` | 3 318 | 51 |
| `20260508-001302` | 2 539 | 91 |
| `20260718-154555` | 752 | 76 |

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

## Next

- [ ] **Per-target over-attribution on pre-2026-05 logs** — biggest remaining
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
