# Session log — Elite Insights parity

Newest first. Each entry records what moved, how it was confirmed, and what was
ruled out, so a later pass does not retrace the same ground.

Harness: `uv run python scripts/ei-parity/ei_diff.py` (no arguments = the
committed 35-log corpus). Setup: `docs/ei-parity-workbench.md`.

---

## 2026-08-04 — 798 → 690

Three fixes, each found by probing a single player before touching any code.
None was the regen work the session set out to do; see "What was *not* done".

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

### 3. `teamID` reported only on an account's last entry (#134) — 711 → 690

arcdps has no team column in the agent table; the team arrives in a
`CBTS_TEAMCHANGE` record, and EI carries the final value on the entry current
at the end of the fight, leaving 0 on the earlier slices of a split account.

Confirmed on `20260424-204954`, where `empiria.8961`, `Mikey.4982` and
`SharpSteel.3051` each have a single team change on the very last millisecond
and EI reports 0 on every slice but the last.

The more mechanistic-looking rule — "team known at the slice's end" — is *not*
what EI does, and was measured before being discarded: on `20260412-220632` the
record lands after every single-entry player's `lastAware`, yet EI still reports
707 for them. That variant fixed 22 and broke 36. The parser-side
`scan_agent_team_changes` timeline it needed was removed again rather than left
as dead code.

Result: 22 resolved, 1 introduced. The one exception is documented rather than
special-cased: `creative.1094` on `20260224-233019` has two slices, both
`group=1`, and EI reports the team on both.

### Where `rotation` (366) actually stands

Characterised but not attacked — it is now 53 % of everything left, and the
shape says the remedy is not uniform:

- 216 of the 366 player rows are **missing casts only**, 33 are **extra only**,
  117 are both. 1 012 casts missing against 339 extra.
- Three skills account for 246 of the 1 012 missing, all `isInstantCast`:
  **77370 Zap (123)**, **9084 "Advance!" (68)**, **5535 Cleansing Fire (55)**.
  These are genuinely absent `InstantCastFinder` entries.
- Skill **30961 (Exit Reaper's Shroud)** appears 45 times as missing *and* 45
  as extra: same cast, wrong timestamp, 1 ms late 30 times and 2 ms late 15
  times. Not a constant offset, so no blanket shift — the same trap as the
  consumable +1 ms.

So the bucket is roughly "a handful of high-frequency finders" plus "a few
per-skill timing anchors", which is worth the systematic extraction the backlog
asks for rather than diff-by-diff additions.

### Rotation: two triggers identified, one implemented and reverted

Probing the three biggest missing skills produced a usable answer for two and
an honest dead end for the third. Two probes are added for it:
`probe_cast_trigger.py` (what of ours coincides with a cast EI reports) and
`probe_cast_candidates.py` (which candidate holds 1:1 across *different*
players and logs — a single player is not enough, because a squad-wide boon
coincides with everything).

- **77370 Zap** — `BoonApplyEvent 76639` covers 35 of 36 casts across three
  player/log pairs. A `_BUFF_GAIN_CASTS` entry, not yet wired.
- **9084 "Advance!"** — effect GUID `122BA55CCDF2B643929F6C4A97226DC9`, which
  the table *already* maps to 9153 "Stand Your Ground!". The two guardian
  shouts share one effect. The self-stability count separates them cleanly in
  one direction: all 71 guardian effects with five-plus self-stabs are 9153,
  no exceptions. Warriors emit the same effect and EI books nothing for them,
  so a profession gate is load-bearing (16 warrior effects in the sample).
- **5535 Cleansing Fire** — every candidate that looked 1:1 for one player
  failed to hold across others. No trigger found.

**Attempted and reverted:** emitting 9084 whenever a guardian effect has fewer
than five self-stabs. It is wrong — only 29 of the 70 such effects are real
9084 casts, and the other 41 became false positives. Corpus went 690 → 726
(8 fixed, 44 introduced). The remaining discriminator between those 29 and 41
is unknown; the 50 ms instant-cast ICD does not absorb it. Do not re-attempt
without finding it first.

An effect-id caveat worth keeping: `EffectEvent.skill_id` is *per-log
ephemeral*. EI keys its effect finders on the GUID, and a probe that groups by
skill_id will show the same effect as a different candidate in every log —
which is exactly what hid the 9084 trigger on the first pass.

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
