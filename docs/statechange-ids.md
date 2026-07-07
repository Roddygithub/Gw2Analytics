# arcdps StateChange enum (from Elite Insights parser)

**Source:** `https://raw.githubusercontent.com/baaron4/GW2-Elite-Insights-Parser/master/GW2EIEvtcParser/ParserHelpers/ArcDPSEnums.cs`
**Refreshed:** 2026-07-07
**Total entries:** $(grep -cE '^\s+[A-Z][a-zA-Z0-9_]+\s*=\s*[0-9]+' /tmp/StateChange.cs.clean) + 1 (Unknown)

This is the canonical mapping of the \`is_statechange\` field in the GW2 EVTC
binary to a human-readable effect name. The v0.9.0 combat-readout feature
(\`docs/v0.9.0-combat-readout-design.md\`) depends on this table to surface
boons / conditions / CC / down / death / dodge / block / interrupt / stun-break
events to the analyst.

## Format

| ID | Name |
|----|------|
| 0 | Combat |
| 1 | EnterCombat |
| 2 | ExitCombat |
| 3 | ChangeUp |
| 4 | ChangeDead |
| 5 | ChangeDown |
| 6 | Spawn |
| 7 | Despawn |
| 8 | HealthUpdate |
| 9 | SquadCombatStart |
| 10 | SquadCombatEnd |
| 11 | WeaponSwap |
| 12 | MaxHealthUpdate |
| 13 | PointOfView |
| 14 | Language |
| 15 | GWBuild |
| 16 | ShardID |
| 17 | Reward |
| 18 | BuffInitial |
| 19 | Position |
| 20 | Velocity |
| 21 | Rotation |
| 22 | TeamChange |
| 23 | AttackTarget |
| 24 | Targetable |
| 25 | MapID |
| 26 | ReplInfo |
| 27 | StackActive |
| 28 | StackDeactive |
| 29 | Guild |
| 30 | BuffInfo |
| 31 | BuffFormula |
| 32 | SkillInfo |
| 33 | SkillTiming |
| 34 | BreakbarState |
| 35 | BreakbarPercent |
| 36 | Integrity |
| 37 | Marker |
| 38 | BarrierUpdate |
| 39 | StatReset |
| 40 | Extension |
| 41 | APIDelayed |
| 42 | InstanceStart |
| 43 | TickRate |
| 44 | Last90BeforeDown |
| 45 | Effect_45 |
| 46 | IDToGUID |
| 47 | LogNPCUpdate |
| 48 | Idle |
| 49 | ExtensionCombat |
| 50 | FractalScale |
| 51 | Effect_51 |
| 52 | RuleSet |
| 53 | SquadMarker |
| 54 | ArcBuild |
| 55 | Glider |
| 56 | StunBreak |
| 57 | MissileCreate |
| 58 | MissileLaunch |
| 59 | MissileRemove |
| 60 | EffectGroundCreate |
| 61 | EffectGroundRemove |
| 62 | EffectAgentCreate |
| 63 | EffectAgentRemove |
| 64 | AgentChange |
| 65 | MapChange |
| 66 | EarlyExit |
| 67 | AnimationStart |
| 68 | AnimationStop |
| 69 | BuffApply |
| 70 | BuffChange |
| 71 | BuffRemoveSingle |
| 72 | BuffRemoveAll |
| 73 | Transformation |
| 74 | WvWTeams |
| 75 | WvWObjectiveStatus |
| 76 | StealthChange |
| 77 | GadgetAnimation |
| 78 | GadgetNameVisible |
| 79 | EffectMissileCreate |
| 80 | GadgetCaptureOutlineShow |
| 81 | GadgetCaptureSplitPercent |
| 82 | GadgetCaptureOutlineHide |
| 83 | GadgetCaptureOutlinePoint |
| 84 | Tick |
| 85 | Unknown |

## Notes

- \`Normal = 0\` is the **sentinel** value: every \`cbtevent\` record with
  \`is_statechange == 0\` is a non-state-change event (damage / heal / strip),
  handled by the existing v0.5.0-parser / v0.6.0-parser surface.
- The arcdps spec evolves: re-fetch this file at every new Elite Insights
  release (or check the upstream \`arcdps_arcdps.h\` header for changes).
- The IDs in this table are the **byte values** of the \`is_statechange\`
  field in the V1.3 \`cbtevent\` 64-byte struct (see \`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py\`:
  \`EVENT_SIZE = 64\`, \`_EVENT_STRUCT = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")\`).
- v0.9.0 sub-mapping (which ID lands in which readout column) is **TBD**:
  it requires reviewing each \`Name\` against the GW2 wiki to know if it is
  a boon apply, a condition remove, a CC effect, a defensive event, etc.
  See the open questions in \`docs/v0.9.0-combat-readout-design.md\` §11.
