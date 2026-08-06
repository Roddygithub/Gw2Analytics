# Session log — Elite Insights parity

Newest first. Each entry records what moved, how it was confirmed, and what was
ruled out, so a later pass does not retrace the same ground.

Harness: `uv run python scripts/ei-parity/ei_diff.py` (no arguments = the
committed 35-log corpus). Setup: `docs/ei-parity-workbench.md`.

---

## 2026-08-04 — 798 → 711

Two fixes, both found by probing a single player before touching any code.
Neither was the regen work the session set out to do; see "What was *not* done".

### 1. Buff simulation now stops at an actor's last-aware (#130) — 798 → 779

EI stops accruing a player's buff uptime once the log stops seeing them. The
tracker only stopped on an explicit despawn, so an actor that simply dropped off
the log kept every still-active boon running to the end of the fight.

Confirmed before coding: on `20260718-154555`, `Non Squad Player 16` is aware
`44..56428` of a 71 500 ms fight, and aegis, protection and fury each overcounted
by *exactly* 21.07 points — 21.08 % of the fight, i.e. the 15 072 ms absence.
Buffs that had already expired before the player left were unaffected, which is
the behaviour the hypothesis predicts.

Added `scan_agent_awareness` to the parser: one pass over the raw cbtevent
stream returning each agent's first/last mention. It reproduces EI's own
`firstAware`/`lastAware` exactly on 250 of 269 players.

Only actors that genuinely leave are clamped, and the corpus justifies the
boundary rather than a guess: absence is 70 ms at the median and 15 s at p90,
with a single player anywhere between 1 s and 5 s.

| absence floor | buff diffs (5 logs) |
| --- | ---: |
| 0 ms | 440 |
| 50 ms | 251 |
| 200 ms | 146 |
| **1 s** | **79** |
| 3 s | 79 |
| unclamped | 87 |

Result: 19 differences resolved, 0 introduced.

### 2. Down-contribution row sliced per EI entry (#132) — 779 → 711

The damage events feeding `statsAll` have been sliced per EI entry since the
split-account work, but the down-contribution row paired with them was still the
whole-fight aggregate, so every slice of a split account repeated the account's
whole-fight totals.

The arithmetic confirmed it outright — `krill le faucheur.1679` on
`20260125-194936` has three slices reporting `downContribution` 0 / 1 894 /
11 441 and `againstDownedCount` 0 / 25 / 15, summing to exactly the 13 335 and 40
we were repeating on each.

Result: 68 differences resolved, 0 introduced. `againstDownedDamage`, `killed`
and `downed` went to zero.

### What was *not* done, and why

The session's stated priority was Regeneration (buff 718) via a faithful port of
EI's `HealingLogic`. Measuring first changed the plan: the brief's premise that
**EI is always higher on regen** does not hold on the corpus — it is 80 cases
where EI is *lower* against 40 where it is higher, with a median |delta| of
**0.053**. Of the 204 buff differences, 123 were under 0.1 and only 32 above 2.
The two fixes above were both larger, better-evidenced wins, so they came first.
The `HealingLogic` port remains open and is still the right next step for the
regen tail.

### Ruled out this session

- **A denominator mismatch behind the small buff diffs.** If EI divided by a
  different duration the relative error would be constant; measured it is
  median 0.000357 with stdev 0.027, and `corr(uptime, |delta|)` is 0.013.
- **Clamping every actor at last-aware.** Correct for actors who leave, wrong
  for everyone else — see the sweep table above.
- **Deriving last-aware from the emitted event stream.** Lands a median 181 ms
  early, enough to shift every uptime by ~0.1 points. The raw scan is exact.
