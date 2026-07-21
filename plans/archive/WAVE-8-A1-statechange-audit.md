# A.1 Audit — arcdps StateChange kinds → v0.11.0 Event subclass mapping

> **Source:** [Elite Insights ArcDPSEnums.cs](https://github.com/baaron4/GW2-Elite-Insights-Parser/blob/master/GW2EIEvtcParser/ParserHelpers/ArcDPSEnums.cs)
> **Date:** 2026-07-21
> **Status:** Audit complete — A.2 (finalize kind→subclass map) ready

## Full StateChange enum (0–84)

| Byte | Name | v0.11.0 subclass | Notes |
|------|------|-----------------|-------|
| 0 | Combat | — | Not a statechange; standard cbtevent |
| 1 | EnterCombat | — | Log metadata |
| 2 | ExitCombat | — | Log metadata |
| 3 | ChangeUp | — | Unmapped (reserved) |
| 4 | ChangeDead | **DeathEvent** | A.3 target |
| 5 | ChangeDown | **DownEvent** | A.3 target |
| 6 | Spawn | — | Log metadata |
| 7 | Despawn | — | Log metadata |
| 8 | HealthUpdate | — | Log metadata |
| 9 | SquadCombatStart | — | Log metadata |
| 10 | SquadCombatEnd | — | Log metadata |
| 11 | WeaponSwap | — | Out of scope (no WeaponSwapEvent planned) |
| 12 | MaxHealthUpdate | — | Log metadata |
| 13 | PointOfView | — | Log metadata |
| 14 | Language | — | Log metadata |
| 15 | GWBuild | — | Log metadata |
| 16 | ShardID | — | Log metadata |
| 17 | Reward | — | Log metadata |
| 18 | BuffInitial | **BuffApplyEvent** | Already handled (CBTS_BUFFAPPLY=18 in parser.py) |
| 19 | Position | **PositionEvent** | Already handled (parser.py inline) |
| 20 | Velocity | — | Out of scope |
| 21 | Rotation | — | Out of scope |
| 22 | TeamChange | — | Log metadata |
| 23 | AttackTarget | — | Out of scope |
| 24 | Targetable | — | Out of scope |
| 25 | MapID | — | Log metadata |
| 26 | ReplInfo | — | Log metadata |
| 27 | StackActive | — | Out of scope |
| 28 | StackDeactive | — | Out of scope |
| 29 | Guild | — | Log metadata |
| 30 | BuffInfo | — | Log metadata |
| 31 | BuffFormula | — | Log metadata |
| 32 | SkillInfo | — | Log metadata |
| 33 | SkillTiming | — | Log metadata |
| 34 | BreakbarState | **CCEvent**? | Breakbar phase transitions; arcdps encodes CC as breakbar delta events. Elite Insights derives CC from `BreakbarState` + `BreakbarPercent` statechanges. |
| 35 | BreakbarPercent | **CCEvent**? | Companion to BreakbarState; used for CC magnitude. |
| 36 | Integrity | — | Log metadata |
| 37 | Marker | — | Log metadata |
| 38 | BarrierUpdate | **BarrierEvent** | ✅ Already mapped |
| 39 | StatReset | — | Log metadata |
| 40 | Extension | — | Log metadata |
| 41 | APIDelayed | — | Log metadata |
| 42 | InstanceStart | — | Log metadata |
| 43 | TickRate | — | Log metadata |
| 44 | Last90BeforeDown | — | Out of scope |
| 45 | Effect_45 | — | Out of scope |
| 46 | IDToGUID | — | Log metadata |
| 47 | LogNPCUpdate | — | Log metadata |
| 48 | Idle | — | Log metadata |
| 49 | ExtensionCombat | — | Log metadata |
| 50 | FractalScale | — | Log metadata |
| 51 | Effect_51 | — | Out of scope |
| 52 | RuleSet | — | Log metadata |
| 53 | SquadMarker | — | Log metadata |
| 54 | ArcBuild | — | Log metadata |
| 55 | Glider | — | Out of scope |
| 56 | StunBreak | **StunBreakEvent** | ✅ Already mapped |
| 57 | MissileCreate | — | Out of scope |
| 58 | MissileLaunch | — | Out of scope |
| 59 | MissileRemove | — | Out of scope |
| 60 | EffectGroundCreate | — | Out of scope |
| 61 | EffectGroundRemove | — | Out of scope |
| 62 | EffectAgentCreate | — | Out of scope |
| 63 | EffectAgentRemove | — | Out of scope |
| 64 | AgentChange | — | Log metadata |
| 65 | MapChange | — | Log metadata |
| 66 | EarlyExit | — | Log metadata |
| 67 | AnimationStart | — | Out of scope (no AnimationEvent planned) |
| 68 | AnimationStop | — | Out of scope |
| 69 | BuffApply | — | Out of scope (handled via BoonApplyEvent on non-statechange path) |
| 70 | BuffChange | — | Out of scope |
| 71 | BuffRemoveSingle | — | Out of scope (REMOVE-class handled via BuffRemovalEvent) |
| 72 | BuffRemoveAll | — | Out of scope |
| 73 | Transformation | — | Out of scope |
| 74 | WvWTeams | — | Log metadata |
| 75 | WvWObjectiveStatus | — | Log metadata |
| 76 | StealthChange | — | Out of scope |
| 77 | GadgetAnimation | — | Out of scope |
| 78 | GadgetNameVisible | — | Out of scope |
| 79 | EffectMissileCreate | — | Out of scope |
| 80 | GadgetCaptureOutlineShow | — | Out of scope |
| 81 | GadgetCaptureSplitPercent | — | Out of scope |
| 82 | GadgetCaptureOutlineHide | — | Out of scope |
| 83 | GadgetCaptureOutlinePoint | — | Out of scope |
| 84 | Tick | — | Log metadata |

## A.2 Final mapping: 8 remaining subclasses

| Subclass | Statechange byte(s) | arcdps name | Certainty |
|----------|---------------------|-------------|-----------|
| **DeathEvent** | 4 | ChangeDead | ✅ Confirmed |
| **DownEvent** | 5 | ChangeDown | ✅ Confirmed |
| **BarrierEvent** | 38 | BarrierUpdate | ✅ Already mapped |
| **CCEvent** | 34 + 35 | BreakbarState + BreakbarPercent | ⚠️ Derived (see §CC below) |
| **DodgeEvent** | — | NOT a statechange | ❌ See §Dodge below |
| **BlockEvent** | — | NOT a statechange | ❌ See §Block below |
| **InterruptEvent** | — | NOT a statechange | ❌ See §Interrupt below |
| **ConditionRemoveEvent** | — | NOT a statechange | ❌ See §Condi below |

### §CC — Crowd Control (BreakbarState / BreakbarPercent)

arcdps emits CC phases as `BreakbarState` (byte 34) + `BreakbarPercent` (byte 35)
statechange pairs. Elite Insights derives the CC applied magnitude from the
breakbar delta between consecutive BreakbarPercent events.

**Recommendation**: Map byte 34 (`BreakbarState`) to `CCEvent` with the breakbar
phase (active / recovering / immune). Use byte 35 (`BreakbarPercent`) as the CC
magnitude. The aggregator can compute the delta.

### §Dodge — NOT a statechange

arcdps does NOT emit a dedicated "dodge" statechange. Elite Insights detects
dodges via:
- Animation ID matching (dodge animation = specific skill/anim IDs)
- Or via the `is_activation == 0 && is_nondamage == 0` path with specific
  skill IDs (the dodge "skill" has known IDs)

**Recommendation**: Defer DodgeEvent to a post-A.4 parser enhancement using
skill-ID-based detection (not statechange). For v0.11.0 A.4, leave
`SCAFFOLD-zero`.

### §Block — NOT a statechange

Blocks are detected via buff applications (Aegis consumption, specific block
buffs) not via statechange records. Elite Insights uses buff-apply tracking.

**Recommendation**: Defer BlockEvent to a post-A.4 buff-tracker enhancement.
For v0.11.0 A.4, leave `SCAFFOLD-zero`.

### §Interrupt — NOT a statechange

Interrupts are detected via the `result` byte on cbtevent records (byte 50,
value = CBTR_INTERRUPT). This is NOT a statechange path — it's a regular
cbtevent with a specific `result` value.

**Recommendation**: Handle InterruptEvent as a non-statechange emit in the
parser's main cbtevent decode loop (check `result` byte after the statechange
filter). This can ship in A.4 since it uses the same cbtevent unpack path.

### §ConditionRemove — NOT a statechange

Condition cleanses are tracked via buff-remove events on condition-type buffs.
Elite Insights uses the buff table to distinguish conditions from boons.

**Recommendation**: Defer ConditionRemoveEvent to the post-A.4 buff-dispatch
layer (the existing `BuffRemovalEvent` already captures remove events; the
condition/boon distinction happens at the aggregator level via the Skills DB
catalog). For v0.11.0, the `condition_cleanses` column in player summaries
already handles this at the aggregator tier.

## Revised A.3 scope (7 subclasses, down from 8)

| # | Subclass | Statechange byte | Ready? |
|---|----------|-----------------|--------|
| 1 | **DeathEvent** | 4 (ChangeDead) | ✅ |
| 2 | **DownEvent** | 5 (ChangeDown) | ✅ |
| 3 | **BarrierEvent** | 38 (BarrierUpdate) | ✅ Already mapped |
| 4 | **CCEvent** | 34+35 (BreakbarState+Percent) | ⚠️ Needs dual-byte tracking |
| 5 | **InterruptEvent** | NOT statechange (result byte) | ⚠️ Different emit path |
| 6 | **DodgeEvent** | N/A | ❌ Deferred (skill-ID detection) |
| 7 | **BlockEvent** | N/A | ❌ Deferred (buff tracking) |
| 8 | **ConditionRemoveEvent** | N/A | ❌ Deferred (aggregator tier) |

**A.4 shippable for v0.11.0**: DeathEvent + DownEvent + InterruptEvent (3 new subclasses,
result-based emit for Interrupt). CCEvent pending dual-byte design. Dodge/Block/Condi
deferred to aggregator-tier or skill-ID-based detection in follow-up cycles.
