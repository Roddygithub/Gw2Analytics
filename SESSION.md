# Session log — Elite Insights parity

Newest first. Each entry records what moved, how it was confirmed, and what was
ruled out, so a later pass does not retrace the same ground.

Harness: `uv run python scripts/ei-parity/ei_diff.py` (no arguments = the
committed 35-log corpus). Setup: `docs/ei-parity-workbench.md`.

---

## 2026-08-06 — 690 → 444

Two passes, one decision: stop inferring the instant-cast rules and
read them out of Elite Insights' sources. Nine finders transcribed, each
verified on the corpus before a line of production code was touched.

### Why the previous approach could not work

Three attempts at `rotation` had failed the same way, and the fourth
diagnosis is now certain. Correlating our event stream against EI's cast
list finds triggers that *cover* every cast; it cannot find the ones that
fire *only* on casts. Two concrete refutations from this corpus:

- **77370 Zap** was measured last session as keying on `BoonApplyEvent
  76639` (35/36 across three player/log pairs). It does not. It is a
  `MinionCastCastFinder`: the *familiar* casts 76803 and EI credits the
  owner with 77370. Buff 76639 is "Familiar's Prowess", which correlates
  only because the familiar is out.
- **9084 "Advance!"** was assumed to be "a guardian shout that is not
  Stand Your Ground". It is not. It is picked out by a self-applied aegis
  of 20 to 40 seconds. The 41 false positives that regressed the corpus to
  726 were the other shouts, which the real rule excludes.

EI's finders are declarative, so they are transcribed and only *verified*
here. `scripts/ei-parity/probe_ei_finders.py` scores a rule against EI's own
output over all 35 logs; a rule is wired only at `missing=0 extra=0`.

| finder | mechanism | casts |
| --- | --- | ---: |
| 9153 Stand Your Ground | five-plus self-stabilities (already shipped, used as the control) | 202 |
| 9084 Advance! | self-applied aegis, 20–40 s | 68 |
| 5535 Cleansing Fire | by-dst effect + two same-destination secondary effects | 55 |
| 77370 / 76643 / 77225 / 77226 Evoker familiars | familiar's cast credited to its owner | 143 |

Result: **266 casts recovered, 0 introduced** — 1 012 missing → 746, extra
unchanged at 339. Corpus 690 → 644.

### What had to change underneath

- `SkillActivationEvent` now carries `src_master_instid`. Damage and healing
  records are re-attributed to the owner at parse time, but an activation
  must not be, or every pet ability would surface in its owner's rotation.
  EI keeps the caster and lets the *finder* credit the owner, so the owner
  is carried alongside instead.
- A secondary effect is matched on the finder's **key** agent, which for a
  by-dst finder is the destination, not the source. No by-dst entry used
  secondary effects before Cleansing Fire, so the bug was latent.
- `build_skill_rotation` takes `professions` and `agent_id_by_instance`.
  Both are general lookups rather than another ad-hoc agent-id set, and both
  are optional, so hand-built event streams keep working.

### Details worth keeping

- EI's `MinionCastCastFinder` never refreshes `lastTime` after an accepted
  cast, so its ICD is dead code there. The normal 50 ms gate is applied
  here instead: the closest two familiar casts by one owner on the corpus
  are 1 042 ms apart, so the two behaviours cannot diverge on real data.
- The guardian shout rules were checked for overlap before being chained:
  **zero** effects on the corpus satisfy both, so `if/elif` is provably
  equivalent to EI running the two finders independently.
- The fight origin is `header.start_time_ms`, not the first *emitted*
  event. On three logs the first raw record is a statechange `parse_events`
  drops, and using the emitted stream shifts every cast 1 ms late. Production
  already had this right; the first version of the probe did not, which is
  what made three exact rules look like near-misses.

### Second pass: three more finders — 644 → 635

Same method, run again on the new heads of the distribution.

- **Engineer kits (−38 casts).** EI declares seven `EngineerKitFinder`s and
  reads each kit's bundle off `/v2/skills` at runtime; we had four kits
  hard-coded. Added **Bomb Kit (5812)**, **Tool Kit (5904)** and **Grenade
  Kit (6020)** from the same API, which also confirmed the four existing
  bundles verbatim. 644 → 641.
- **30961 Exit Reaper's Shroud (−45 missing, −45 extra).** Two divergences,
  both mechanical: `BuffLossCastFinder` is typed on `BuffRemoveAllEvent`, so
  a partial strip is not a cast; and `UsingBeforeWeaponSwap` places the cast
  at `min(swap - 1, time)` when a swap is within half a server delay. We
  emitted on any removal, at the raw time. This was the "1-2 ms off, not a
  constant offset" entry from the previous pass — the offset is not constant
  because it depends on where the swap falls. 641 → 635.

The before-swap expression was corrected to EI's `min(swap - 1, time)` for
every buff on that path, not just the new one; the corpus confirms none of
the existing entries relied on the unconditional `swap - 1`.

### Third pass: two over-firing finders — 635 → 632

Both of these produced casts EI does not report, which the row count barely
registers: 55 spurious casts came off with the bucket moving by 3.

- **13684 Lesser Symbol of Protection (−19 extra).** EI guards the trait
  proc with `UsingNoAnimatedCastChecker(SymbolOfProtection)`, and we had no
  guard at all — every symbol effect was booked as the trait, including the
  ones the real skill placed. The guard was already present in a weaker form
  for the sibling 13677: it tested only for a cast *still open*, where EI
  tests the whole cast window widened by a server delay at both ends. Both
  are now driven by one `_NO_ANIMATED_CAST_GUARDS` table, which also fixes a
  detail the old code got wrong — Luminous Staff collides with only one of
  the two Symbol of Resolution variants, not both. Verified exact at 49
  casts.
- **Weaver attunements (−36 extra).** A Weaver swaps between *dual*
  attunements, which EI books as their own skills — four real ids and twelve
  synthetic negative ones — and it never books a base attunement skill for
  one. Confirmed corpus-wide across all four elements: Elementalist,
  Tempest, Catalyst and Evoker all get them, Weaver gets **zero**. We were
  reporting the base skill from the base attunement buff, which the log does
  carry for weavers. Those casts are now dropped rather than mislabelled.

Deriving the weaver swaps themselves is left undone, so they stay in the
missing column — that is the honest position, and it is visible.

### Fourth pass: regeneration — 632 → 583

`buffUptimes` 185 → 136, of which regeneration 116 → 67. Two changes, both
read off EI's `HealingLogic` / `BuffSimulatorDuration`.

- **`BuffStackActiveEvent` never reached the tracker (−44).** `process`
  has handled it since the stack-id work, but `ei_compare` filtered the
  event stream to apply / extension events only, so the whole `Activate`
  path was dead. Regeneration is a queue where only the front stack burns
  down and the rest wait, so activating a queued stack changes which
  duration is spent — and on `20260526-202841` alone that stream carries
  308 of these records.
- **The two `Activate` overloads are not the same rule (−5).** EI reaches
  the richer one — replace a nearly-spent active stack, and pin the
  ordering with `noSort` — only from the explicit stack-active record.
  An apply flagged `addedActive` goes through `QueueLogic.Activate`, which
  just moves the stack to the front. We were applying the richer rule to
  both, which pinned `noSort` from the first apply onwards.

`noSort` is now tracker-wide rather than per (agent, buff), matching EI:
its `HealingLogic` lives on a single `static readonly` instance, so the
first stack-active record anywhere in the log latches the flag for every
actor, permanently. On this corpus it changes nothing — the latch fires
early either way — but the scope is now the one EI actually has.

### Where regeneration still stands, precisely

67 differences left, 24 of them under 0.1. The 19 above 2 concentrate on
`20260526-202841`, and the cause is now located rather than guessed:

- Our queue model **is** EI's. `BuffSimulatorDuration.Update` burns
  `BuffStack[0]` and shifts the rest, which is what `_advance` does.
- A plain FIFO replay of `Ver.5187` on that log lands at **81.839 %**
  against EI's **81.941 %** — the model reproduces EI to a tenth of a
  point when nothing reorders the queue.
- The same player through the tracker lands at **66.668 %**. The gap is
  the reordering: once `Activate` moves stacks to the front, overflow at
  capacity 5 evicts a different stack, and evicting a long one costs its
  whole remaining duration.

The evictions were then instrumented, and the result is a warning as much
as a finding. On `Ver.5187`, moving each `added_active` apply to the front
keeps the queue permanently full — **six** capacity overflows instead of
three — and every overflow discards a whole stack's remaining duration.
Not activating on apply reproduces EI almost exactly:

| player | EI | no activate on apply | activate on apply |
| --- | ---: | ---: | ---: |
| `Ver.5187` | 81.941 | 81.839 | 60.923 |
| `MOTEUS.4861` | 86.039 | **86.039** | 65.289 |
| `syotox.7895` | 68.731 | 68.834 | 49.282 |
| `masterp.6390` | 98.270 | **98.270** | 86.315 |

Four players, two of them exact to three decimals — and **the change is
still wrong**. Removing the activation took the corpus from 583 to **631**
and `buffUptimes` from 136 to 184. It was reverted.

That is the whole lesson of this pass: a four-player probe is not the
corpus, and a rule that reproduces EI on the worst offenders can be
net-negative everywhere else. The remaining regeneration residual is a
question about *which* applies activate, not *whether* they do.

One input is missing for that, and it is a parser-level gap worth naming:
**we drop every uncredited regeneration remove-single.** The raw stream
for `20260526-202841` carries 594 of them (statechange 71, buffremove 2);
`parse_events` skips them with `iff == 2 and dst_agent == 0`, matching EI's
`OverstackOrNaturalEnd`. EI excludes them from the *simulation* too, but
keeps the last one to drive `FindLowestValue`: an apply landing within 10
ms of such a removal replaces the stack with that buff instance, or failing
that the one whose duration is closest. That override is currently
unimplementable here because the records never leave the parser.

### Fifth pass: the displaced stack — 583 → 533

The reverted experiment above asked the wrong question. Elite Insights
*does* activate on an `added_active` apply, keeping the queue full; what it
also does, and we could not, is evict the **right** stack.

arcdps names it. When an application displaces a queued regeneration
stack, the game emits an *uncredited* single-removal immediately before it
— no remover, no target agent, which is how a natural end or an overstack
is reported — carrying the displaced stack's remaining duration and its
buff instance. `parse_events` drops those records, and correctly so: EI
excludes them from the simulation as well. But EI keeps the last one as a
*hint*, and that is the input we were missing.

On `20260526-202841` the raw stream carries 594 of them, and **182 of the
762 regeneration applies** are paired with one inside a server delay.

`scan_regeneration_overstacks` recovers them without touching the emitted
stream — the same split EI makes, from the same records, in the shape
`scan_agent_awareness` already established. The tracker then reproduces
`HealingLogic.FindLowestValue`: evict the stack whose buff instance arcdps
named, else the one whose duration is closest to the removed one, else —
with nothing to go on — the last.

Regeneration goes **116 → 17** across the session, 11 of those under 0.1
and only 2 above 2 points. `buffUptimes` 136 → 86, corpus 583 → 533.

Might (740, 23 differences) is now the largest buff bucket, ahead of
regeneration.

### Sixth pass: the downed segment that never opens — 533 → 489

`downContribution` was the next family by size, and its rule is
`IsDownBeforeNext90`: at the moment of the hit the target is at or below
90 % health, is not already downed, will go down before the log ends, and
does not pass back above 90 % before that down.

We had all of that. What we did not have is what happens *before* the
rule runs. Elite Insights builds one downed **segment** per down event
and keeps it only when `start < end`, so an actor that dies on the same
millisecond it goes down has **no downed segment at all** — and
`IsDownBeforeNext90` then finds no next down and returns false for every
hit that took it there.

On `20260129-110256`, target `inst 7121` downs and dies at 142866 exactly.
EI credits zero down-contribution to it from anyone; we credited 16 838
to `Amazing Grace.2309` alone, which was that player's entire
`statsAll.downContribution` gap. The backlog had this recorded as a
one-off oddity — "the only target in that log with `downCount > 0` and no
contribution" — and it turns out to be a rule.

`statsAll.downContribution` 25 → 9, `statsTargets.downContribution` 22 →
6, and the four `appliedCrowdControl*DownContribution` buckets came down
with them, since they test the same predicate.

`againstDownedCount` (24 + 21) did **not** move: it reads the damage
record's own against-downed flag rather than this predicate, so it is a
separate problem.

### Seventh pass: a landed hit is not a hit that hurt — 489 → 444

`againstDownedCount` was the last big non-rotation bucket, and all 45 of
its differences pointed the same way: **ours lower, by one to three**.

Elite Insights counts an against-downed hit inside `if (dl.HasHit)` and
asks nothing about its magnitude. We required `damage > 0`. A hit fully
absorbed, or wholly converted to barrier, lands for zero health damage
and still counts — which is exactly why the *damage* sums already matched
and only the counters drifted.

Confirmed before coding, on `SnuSnu.6290` / `20260526-202841`: 19
against-downed records, 14 carrying damage, 5 at zero — of which exactly
**1** landed. 14 + 1 = 15, which is EI's number.

All 45 resolved; the bucket is gone.

The predicate now lives in one place. `ei_compare` had a private
`_connected` used by three counters, `down_contribution` had an
open-coded `damage > 0`, and they were answering the same question
differently. Both now import `damage_predicates.landed_hit`.

### Open, and deliberately left: 29560 Spiteful Spirit

30 casts, and neither documented finder explains them. Both were
transcribed and measured (`probe_ei_finders.py spiteful-spirit`): the
`EffectCastFinder` on `NecromancerUnholyBurst` covers **194 with 0 extra**
but misses 30, concentrated on two logs where the log contains *no* effect
carrying that GUID and *no* damage of 38767. The companion
`DamageCastFinder(SpitefulSpirit, SpitefulSpirit)` does not fill the gap
either — on `20260712-203400` it predicts 5 against EI's 8, overlapping on
only 1, and it is in any case gated off by `UsingDisableWithEffectData` on
logs that plainly have effect data.

So EI reaches those casts by a path not visible in `NecromancerHelper`.
Worth noting the trap that cost time here: an `EffectEvent.skill_id` of
29560 shows up on one of those logs and is **coincidence** — the field is a
per-log ephemeral effect id, not a skill id, and those events belong to
other players entirely.

### Ruled out this session

- **`_BUFF_GAIN_CASTS[76639] = 77370` for Zap.** Wired and measured: 0
  change in the player-row count but −71 missing / **+102 extra** at cast
  level. This is what prompted the harness to report both.
- **Reaching 29560 from either of its two declared finders.** See above.
- **Dropping the `added_active` activation for regeneration.** Reproduces
  EI on the four worst players (two exactly) and regresses the corpus 583
  → 631. EI's sources do call `QueueLogic.Activate` on the item whenever
  the record carries the flag, and the flag is set on most regeneration
  applies in every arcdps era, so it is not a byte-mapping artefact.

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
