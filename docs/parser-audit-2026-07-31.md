# In-house parser audit — 2026-07-31

Scope: `libs/gw2_evtc_parser` and the EI-facing parts of `libs/gw2_analytics`,
measured against Elite Insights 3.26.0.0 run locally over a 35-log WvW corpus
(see `docs/ei-parity-workbench.md`).

## Headline

The parser reads the EVTC container correctly — header, agent table, skill
table and event-stream boundary all resolve on every log in the corpus, at
roughly 200 k events/s. The gap with Elite Insights is not in byte handling but
in **semantics**: several arcdps enums were decoded from assumptions rather than
from the wire, and the mistakes were absorbed by regression thresholds
(`max_differences=17/9/7` in `test_parser_multilog_corpus.py`) instead of being
surfaced.

Measured on the corpus: **23 830 differences** at the start of this audit,
**5 941** after the seven fixes below. 24 of the 35 logs are now under 100.

## What the audit found

### 1. The elite-specialization table was wrong (fixed)

`EliteSpec` and `_VALID_ELITE_BY_PROFESSION` mapped Daredevil to 55, Deadeye to
72, Weaver to 63 and Catalyst to 75. Those IDs belong to Soulbeast, Untamed,
Renegade and Amalgam respectively. Bladesworn (68) was missing entirely. The
enum carried comments describing "collisions" between professions that do not
exist: the GW2 specialization catalogue assigns every elite spec a unique ID.

Consequence: `_validate_elite_for_profession` rejected every real Thief and
Elementalist elite ID and silently returned `EliteSpec.BASE`, so those players
were reported as core professions. Confirmed on the corpus — logs contain
Thieves with `elite_raw` 7 and 58, and Elementalists with 56 and 80, none of
which the old table accepted.

The corrected table is EI's own `Content/SpecList.json`, cross-checked against
every (profession, elite_raw) pair in the corpus.

### 2. Anonymized enemy names were compared in the client's language (fixed)

arcdps replaces an anonymized enemy player's character name with the *localized*
elite-spec string. On a French client that is `"Cataclyste"`; EI writes
`"Tempest"`. The comparison echoed the raw buffer, so every non-squad player on
a non-English log counted as a mismatch. Names are now rebuilt from the
profession/elite IDs via `spec_display_name`.

### 3. A fabricated `result` byte (fixed)

The EVTC2025 condition-damage path contained:

```python
damage_result = 13 if magnitude == 0 else _result
```

It assumed a zero-magnitude condition tick meant the target was invulnerable.
That is false: a tick that lands for zero health damage — fully mitigated, or
entirely converted to barrier — is a connected hit for EI. Every occurrence cost
one `connectedDamageCount` and one `connectedConditionCount` while inflating
`invulned` by the same amount, which is exactly the signature the corpus showed.

### 4. The condition `result` enum was renumbered by arcdps in 2026-05 (fixed)

arcdps writes two enums into the `result` byte, selected by the `ev.buff` byte,
and the condition one changed:

| Build | Condition results seen | Landed | Immune |
| --- | --- | --- | --- |
| ≤ `20260416` | 0, 1, 3 | 0 | 1-4 |
| ≥ `20260507` | 6, 13, 14, 16, 18 | 14, 16, 18 | 6, 13 |

Derived by reconciling every single-result (player, skill) entry in EI's
`totalDamageDist` against its `connectedHits` / `invulned` counters across the
corpus: 2 300+ observations, no disagreement. The direct-hit enum is unchanged
across all builds (0/1/2 landed, 6 absorbed, 3/4/7 blocked/evaded/blinded).

`DamageEvent` now carries `connected` and `absorbed`, resolved by the parser —
the only layer that knows the build — plus `is_condition` (which arcdps channel
the record came from) and `shield_damage` (the `overstack_value` field, which
was being skipped entirely).

### 5. arcdps moved buffs and casts onto new statechange codes in 2026-05 (fixed)

The same 2026-05-07 build that renumbered the condition enum also moved two
whole channels off the plain `is_statechange == 0` record:

| Code | Was | Meaning |
| --- | --- | --- |
| 69 | `statechange 0` + `ev.buff != 0`, `buffremove 0` | buff applied (`value` = duration) |
| 70 | — | buff apply that overstacked (`overstack_value` = wasted duration, no state change) |
| 71 | `statechange 0` + `buffremove` 2 or 3 | buff removed |
| 72 | `statechange 0` + `buffremove` 1 | all stacks removed |
| 67 | `statechange 0` + `is_activation` NORMAL | cast started |
| 68 | `statechange 0` + `is_activation` 3-6 | cast ended |

The parser's generic `if is_statechange != 0: continue` discarded all six. On
any log from 2026-05-07 onward that meant **no buff events and no cast events at
all** — boon uptimes read as ~0 against EI's 90-plus percent, and rotations were
missing every non-instant cast including dodges.

The record shape is otherwise unchanged, so the fix folds 67/68/69/71/72 back
onto statechange 0 (67 also restoring the `NORMAL` activation the byte no longer
carries) and lets the existing branches run untouched. Code 70 is deliberately
left out: an overstacked apply does not change the target's buff state.

### 6. Per-target damage matched a single agent (fixed)

An EI target is an *instance*, and arcdps reuses one instance ID across every
agent record that instance produces over a fight. The comparison resolved a
target to one agent, dropping the damage dealt to the others. Whole-fight totals
matched while per-target totals came up short — which is why the per-target
buckets were an order of magnitude larger than their whole-fight equivalents.

### 7. Condi/power split is a catalogue lookup, not a channel test (fixed)

EI splits condition from power damage by the buff's `classification` in its own
buff catalogue, not by the arcdps channel. Life-steal effects — Vampiric
Strikes, Vampiric Aura, Battle Scars, Fulgor — arrive on the buff-damage channel
but count as power. They are also in neither `connectedDirectDamageCount` (not
the physical channel) nor `connectedConditionCount` (not conditions), so those
two counters do not partition `connectedDamageCount`.

Note this one is a *data* dependency: the comparison reads the catalogue out of
the EI export. A standalone parser would need to ship its own.

## What remains

| Bucket | Count | Note |
| --- | ---: | --- |
| `rotation` | 549 | Instant-cast synthesis. Dodges and ordinary casts are fixed; what is left are sigil / rune / trait procs from EI's hand-maintained `InstantCastFinder` set. Needs systematic extraction, not diff-by-diff. |
| `buffUptimes` | 483 | Structurally correct now. Residual is mostly ±0.001-0.05 rounding plus a handful of real gaps. |
| `statsTargets` / `dpsTargets` | ~2 500 | Concentrated in five pre-2026-05 logs, all over-counting while the whole-fight totals match — the same event is being attributed to more than one target. |
| `againstDowned*` / `downContribution` | ~950 | Same five logs. |
| `consumables`, `defenses.*`, `teamID` | <100 | Long tail. |

Detail and reproduction steps in `BACKLOG.md`.

## Process finding

The EI-alignment tests assert `len(differences) <= N` against hardcoded Linux
paths (`/home/roddy/...`), so on any other machine they skip, and where they do
run they ratchet a threshold rather than a value. The thresholds were raised as
recently as PR #89. A skipped test and a passing test are indistinguishable in
CI output — every real defect above survived a green suite. Worth replacing with
a committed small-log fixture and an exact-match assertion on the buckets that
are already at zero, so they can only regress loudly.
