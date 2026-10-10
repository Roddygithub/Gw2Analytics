# WvW Elite Insights export v1

**Status: prototype, not production cutover.** The Python validator and synthetic fixture are product-owned. An opt-in sidecar exporter is maintained in the dedicated [Gw2Analytics EI fork](https://github.com/Roddygithub/GW2-Elite-Insights-Parser/tree/gw2analytics-wvw-export-v1) at commit [`062e250d55c0a09a7f734524287043c7852483b4`](https://github.com/Roddygithub/GW2-Elite-Insights-Parser/commit/062e250d55c0a09a7f734524287043c7852483b4). It is based on upstream `baaron4/GW2-Elite-Insights-Parser` v3.26.0.0, commit `e4e548bf95b8a4901018a2c6a70058fc9c9e539f`. The implementation was built with local .NET SDK 8.0.425.

## Purpose and non-goals

The export addresses event-level gaps recorded by the [executed field-coverage gate](../validation/ei-field-coverage-gate.md): normalized combat events, time-aware ownership, positions, and per-target buff removals. It projects EI's parsed objects; it does not reparse EVTC bytes or copy EI's general JSON document.

This slice does not route uploads through EI, change `parser_adapter`, remove `gw2_evtc_parser`, or change persistence, API, or frontend behavior. The existing adapter remains the future process boundary. Archive extraction, multi-log grouping, upload/session identity, error mapping, and the production runtime remain product-owned and are not implemented here.

## Export contents

The sidecar has a `WvwExportV1` envelope with `schema_version`, EI `parser_version`, optional source/config/session metadata, `source_log_count`, and ordered `fights`. The product contract lives in `gw2_core.ei_wvw_export`; unknown fields and versions are rejected. The [fixture](../../libs/gw2_core/tests/fixtures/wvw_export_v1.json) is synthetic.

Each fight contains actor slices, normalized events, ownership intervals and position samples. It also includes aggregate `ownership_observation_count` and `ownership_same_time_collision_count` diagnostics so interval coalescing can be measured without exporting raw observation identities.

Events are a strict discriminated union on `kind`. Damage carries source, target, signed EI skill ID, health damage and shield damage. Buff apply, extension, and the three removal kinds each carry source, target, signed EI buff ID and duration; removals also carry removed stacks. Down, death, alive, spawn, despawn and health-update variants carry only their lifecycle fields. EI's `NoBuff` sentinel and stack activation/deactivation bookkeeping events are omitted: they are not product buff changes. Buff stack IDs are not included. Sequence values are assigned after deterministic sort and must equal their zero-based array index.

All event, actor-awareness, ownership and position times use the same origin: `event_time - ParsedEvtcLog.LogData.LogStart`. The exporter does not clamp timestamps; it uses checked integer conversion and the product validator rejects values outside `0..duration_ms`. Position samples use EI world coordinates and sort by `(time_ms, actor_id, x, y, z)`. Coordinates must be finite.

## Identity, grouping and missingness

Actor IDs are local to one fight. They are assigned from parsed actor ordering and are not account IDs, EI `AgentItem.UniqueID` values, or stable across fights. Separate awareness slices remain separate actors. Unreferenced EI synthetic (`IsFake`) actor records are omitted because EI creates their internal agent/instance IDs randomly; referenced synthetic actors remain so exported references resolve. EI instance and species IDs can be null; buff and skill IDs preserve signed EI identifiers. Nullable names, accounts, subgroup, profession/spec, and event actor references remain null when unavailable.

The current CLI invocation emits one fight as `log-0000/fight-0000`. `source_log_count=1`; `segment_index=0`. It does not group multiple `.zevtc` archive members. The eventual adapter must invoke the pinned process per archive entry, preserve archive order, and combine results with `source_log_index` and `segment_index`; it must not merge logs by timestamp or player identity. WvW outcome is `unknown` because this exporter has no product outcome mapping.

## Ownership semantics

EI's `EvtcParser.FindAgentMaster` resolves a master by instance ID at the observation timestamp (`AgentData.GetAgentByInstID(instID, time)`) and obtains the minion slice aware at that same time. When both resolve, the new opt-in path records the minion's observed master and timestamp while preserving the existing `AgentItem.Master` behavior. `AgentItem` copies retain observations and `ApplyOffset` shifts their times with the agent's awareness bounds.

Each distinct observation time starts a half-open interval. The next later observation ends it; the last interval ends at that minion slice's `LastAware`. Thus `start_basis` is `master_observation`; `end_basis` is `master_observation` or `agent_awareness`. Same-time records are counted as collisions and the last record in EI traversal order supplies that timestamp's owner. Non-positive intervals are omitted.

`owner_resolution="unresolved"` with `owner_actor_id=null` means EI recorded a master observation but the export could not map it to an actor slice at that timestamp. `resolved` requires a non-null ID. No observation produces no interval; EI does not report explicit unowned observations, so null is not used to mean unowned. The minion interval must fit its own awareness window. The owner must be aware at the observation start, matching EI's timestamped instance lookup; requiring the owner to remain aware through the interval end would be invalid when the minion's last observed relation extends beyond the owner's slice.

Local validation found no unresolved owner observations in the three logs. They contained many same-time observation collisions, so collision resolution remains an explicit tie rule requiring broader corpus review.

## EI source mapping and limits

| Family | Parsed EI source and projection | Limits |
| --- | --- | --- |
| Damage and lifecycle | `ParsedEvtcLog.CombatData`: `HealthDamageEvent`, down/dead/alive/spawn/despawn and `HealthUpdateEvent` | Projects typed event time, actors, skill IDs, damage/shield and health percent. Other EVTC flags are deferred. |
| Buff changes | `CombatData.GetBuffDataByDst`; `BuffApplyEvent`, `BuffExtensionEvent`, removal classes and `BuffEvent.By` / `.To` | The collection includes extensions: `CombatData` adds each buff to `_buffDataByDst` before excluding extensions only from the source index. For applies/extensions, `By` is applier and `To` is recipient; for removals EI sets `By` to remover and `To` to affected target. The exporter preserves those meanings and reference-deduplicates. Stack metadata and invalidated `NoBuff` events are omitted. |
| Ownership | `EvtcParser.FindAgentMaster`, `AgentData.GetAgentByInstID(instID,time)`, `AgentItem.FirstAware` / `LastAware`, and new opt-in `OwnershipObservations` | EI previously retained only a global master pointer. This sidecar records timestamped observations. Same-time tie behavior is deterministic for a parse but not proven semantically lossless. |
| Positions | `CombatData.GetMovementData` and `PositionEvent.GetPoint3D`; replay parser | Positions exist only when combat replay parsing is enabled. Exported float coordinates are EI world coordinates. Replay can increase output size substantially. |
| Identity and metadata | `AgentItem`, `Player`, `LogMetadata` | Actor IDs exclude `UniqueID`; unreferenced synthetic agents with random EI IDs are omitted. No skill dictionary, guild, gear, weapon, map or team metadata is included. |

The exporter is added in `GW2EIJSON/WvwExport.cs` and `GW2EIBuilders/WvwExportBuilder.cs`; the CLI writes an opt-in `_wvw_export_v1.json` through `GW2EIParserCommons.ProgramHelper`. `SaveOutWvwExport` is false by default. Parser ownership observation capture is also false by default and is enabled only when this sidecar is requested. Ordinary parses keep the existing `SetMaster` path without retaining the extra observation list.

## Real-log validation and resources

The private certification manifest contains 35 entries and all 35 logs are present locally. This slice ran the three requested representative logs twice each. Logs and JSON stayed under ignored `.tooling/ei-export-validation/`; nothing derived from them is committed. The values below are aggregate only. Peak RSS is a 10 ms `psutil` sampling estimate for the CLI process tree.

| Log | Input bytes | JSON bytes | Ratio | Wall seconds (two runs) | Sampled peak RSS MB | Actors | Events | Ownership observations / collisions / intervals | Owner changes | Unresolved | Positions | Repeat bytes identical |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | :---: |
| `20251205-211525` | 832,851 | 9,092,536 | 10.917x | 1.190 / 1.170 | 162.1 | 1,129 | 27,796 | 3,303 / 2,102 / 1,194 | 0 | 0 | 7,097 | yes |
| `20251207-225200` | 2,188,313 | 16,494,411 | 7.538x | 1.525 / 1.573 | 210.2 | 1,276 | 39,431 | 15,989 / 8,586 / 7,352 | 0 | 0 | 26,457 | yes |
| `20251208-230823` | 462,489 | 4,494,335 | 9.718x | 0.952 / 0.959 | 138.8 | 291 | 12,818 | 4,244 / 2,633 / 1,609 | 0 | 0 | 4,128 | yes |

Event counts by kind (`damage`, `buff_apply`, `buff_extension`, `buff_remove_all`, `buff_remove_single`, `buff_remove_manual`, `down`, `death`, `alive`, `spawn`, `despawn`, `health_update`):

- `20251205-211525`: 2,262; 12,408; 1,818; 1,530; 7,315; 1,727; 1; 24; 1; 34; 42; 634.
- `20251207-225200`: 2,665; 12,715; 4,398; 1,509; 7,164; 3,022; 47; 196; 34; 251; 220; 7,210.
- `20251208-230823`: 1,910; 4,022; 669; 1,087; 1,215; 2,555; 12; 20; 5; 43; 77; 1,203.

Across all three logs, event times ranged from 0 to 69,073 / 151,737 / 74,816 ms, respectively. Actor awareness, ownership intervals, and positions also validated within each fight's `0..duration_ms` window. The code applies no timestamp clamp. Both exports of each input had matching SHA-256: `eaf09735082505bef91fc2ad2cf4709236846b831a1c966fb24b18684073d4c6`, `c3ea1fa481bb2b94e36f8cb6262b319c217263e44b792737760030d4b949b6f9`, and `bc82fdfd4742cd6b37b6f6522abec447347a261b5315832c915b7de8d6c4978e`. This establishes repeatability for these runs, not 35-log determinism or semantic parity.

Output is 7.5–10.9 times compressed EVTC size with replay positions enabled. These samples do not set an acceptable production budget; output size, time, and peak memory need the full certification set and production-like process limits before cutover.

## Validation status

The focused exporter tests pass (14/14). The full EI suite reports 1,068 passed and two pre-existing failures on the corrected candidate; upstream base v3.26.0.0 reports 1,054 passed and the same two failures. Both failures are `StableSortByTimeThenSwap` and `StableSortByTimeThenNegatedSwap`, which throw `NullReferenceException` because their existing test helper constructs `CastEvent` with a null caster. No new test failure was introduced.

The exporter is not parser parity. The three private logs validate shape, ordering, actor references, timestamps and repeated output only. No product semantic comparison against `gw2_evtc_parser` has been performed.

## Migration acceptance gates

Keep `gw2_evtc_parser` until all of these pass:

1. EI projections cover every shipped product field and event semantic.
2. The complete 35-log certification set passes semantic parity for fight boundaries, actor slices, events, ownership attribution, positions and buff removals.
3. Multi-log archive grouping and stable fight/segment identities are validated.
4. Output is deterministic across repeated processes and versions.
5. Runtime, memory and JSON-size budgets are acceptable.
6. The process adapter tests pass; persisted data remains compatible; API and frontend behavior has no regression.

EI fork/export work remains separate from the Gw2Analytics adapter/runtime migration. This contract authorizes neither production cutover nor parser deletion.
