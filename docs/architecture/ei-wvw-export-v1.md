# WvW Elite Insights export v1

**Status: compiled EI exporter prototype and product validator; no production parser cutover.** This document defines the small process boundary needed to carry EI's parsed WvW data into the product. The Python validator and example payload are Gw2Analytics-owned. The example is synthetic and contains no private log data. The local EI fork adds an opt-in CLI sidecar; it has not been run against a valid WvW log in this environment.

## Purpose and non-goals

The export fills the event-level gaps recorded by the [executed field-coverage gate](../validation/ei-field-coverage-gate.md): normalized combat events, time-aware ownership, positions, and per-target buff removals. EI's existing detailed-WvW JSON remains useful for its aggregates; this contract does not copy that document or expose its C# object graph.

This slice does not route uploads through EI, change `parser_adapter`, remove `gw2_evtc_parser`, change persistence/API/frontend contracts, or claim semantic parity. The adapter remains the eventual process boundary and will own archive unpacking, multi-file grouping, version validation, error mapping, and session identity.

The compiled prototype currently emits damage events (health/shield values), buff apply/extension/removal events, down/death/alive/spawn/despawn and health-update events, ownership intervals, and parsed position samples when replay parsing is enabled. This is deliberately not the complete generic event stream needed for cutover. Healing/barrier events, breakbar and CC details, activation/cast timing, weapon swaps, interrupts, damage-result flags, effects, and full raw event metadata remain deferred. Several are available as EI statistics/aggregates, but they do not preserve event-level timing/attribution; the field matrix documents those semantics. Extend the DTO only with a concrete product consumer and evidence of the corresponding EI source data.

## Envelope and shape

`WvwExportV1` is a UTF-8 JSON object with strict keys. The product-side Pydantic models are in `gw2_core.ei_wvw_export` and are exported from `gw2_core`.

```json
{
  "schema_version": 1,
  "parser_version": "3.26.0.0",
  "source_commit": null,
  "config_sha256": null,
  "session_id": null,
  "source_log_count": 1,
  "fights": [{
    "fight_id": "log-0000/fight-0000",
    "source_log_index": 0,
    "segment_index": 0,
    "started_at": "2026-01-01T00:00:00Z",
    "duration_ms": 2000,
    "build": null,
    "outcome": "unknown",
    "actors": [],
    "events": [],
    "ownership_intervals": [],
    "position_samples": []
  }]
}
```

The committed [fixture](../../libs/gw2_core/tests/fixtures/wvw_export_v1.json) shows one actor, one damage event, one ownership interval, and explicit missing values. It is a contract example, not EI output.

Each fight contains:

- `actors`: export-local stable actor IDs, actor kind, nullable name/account, subgroup, profession/spec labels, instance/species IDs, and awareness bounds.
- `events`: a monotonically ordered normalized event stream. IDs refer only to actors in the same fight. `source_actor_id`, `target_actor_id`, and event payload fields are explicitly nullable when EI cannot resolve them.
- `ownership_intervals`: half-open `[start_ms, end_ms)` relationships. A null owner is reserved for an explicit unowned interval; absence of an interval means ownership was not observed and must not be interpreted as unowned.
- `position_samples`: actor-local x/y/z samples in EI's world coordinate system, at fight-relative millisecond timestamps.

`time_ms`, awareness, interval, and sample values are relative to EI's fight-log start. `started_at` preserves EI's offset-qualified timestamp and is nullable; it is not used to calculate event times. This avoids inventing an epoch when the source timestamp is missing. Skill identity is the numeric EI skill/buff ID; labels stay metadata and are not required to interpret events.

## Identity, grouping, and ordering

Actor IDs are assigned within a fight from a deterministic ordering of the parsed actor slices; they are not account IDs, agent pointers, or stable across fights. Awareness slices for the same character remain separate actor records. The implementation must never use EI's `AgentItem.UniqueID` as an export ID; EI documents it as nondeterministic.

`fight_id` is `log-NNNN/fight-NNNN`, where the first index is the input EVTC entry order in the `.zevtc` archive and the second is the EI segment order within that entry. EI currently parses one log per invocation. The future adapter will invoke it per archive entry and combine results in archive order; the per-file prototype emits one segment at index zero. It must not merge different source logs based only on timestamps or names. WvW outcome is `unknown`: EI marks the WvW main phase successful by parser convention, which is not a product combat outcome.

Events are ordered by `(time_ms, sequence)`. The exporter assigns zero-based unique sequence values after sorting by time, kind, source, target, skill, and event payload; it does not promise original EVTC byte order among equal-time events. Position samples are ordered by `(time_ms, actor_id, x, y, z)`; ownership intervals by `(agent_id, start_ms, owner_actor_id)`. Consumers may rely on these orders, not on source collection iteration order.

## Missingness and versioning

Required arrays are always present; an empty array means no records were exported for that family. Optional identity, timestamp, actor references, and event-specific values are explicit JSON `null` when unavailable. Unknown EI fields are rejected (`extra="forbid"`), as are unknown schema versions, unknown event kinds, malformed type-specific payloads, invalid actor references, out-of-range timestamps, and unsorted events.

`schema_version` changes only for incompatible shape or semantic changes. `parser_version` identifies EI; `source_commit` and `config_sha256` must be provided by the pinned build/process wrapper when available, otherwise null. `session_id` is assigned by the Gw2Analytics upload adapter, not guessed by EI. The current one-file prototype uses null until that wrapper exists.

## EI source mapping and projection limits

The local source checkout is `.tooling/ei-src`, upstream `baaron4/GW2-Elite-Insights-Parser` at `e4e548bf95b8a4901018a2c6a70058fc9c9e539f` (`v3.26.0.0`). Relevant source objects and insertion points are:

| Export family | EI parsed source | Current JSON status | Projection notes |
| --- | --- | --- | --- |
| Damage and lifecycle events | `ParsedEvtcLog.CombatData`; `HealthDamageEvent`, `DownEvent`, `DeadEvent`, `AliveEvent`, `SpawnEvent`, `DespawnEvent`, `HealthUpdateEvent` | `JsonLogBuilder` exports aggregates and series, not generic per-event records; the local opt-in `WvwExportBuilder` projects these typed events | Parsed times, actor slices, skill IDs, damage/shield values and health percentages are already available. The v1 projection preserves these fields and intentionally omits other EVTC flags. |
| Buff apply/removal | `CombatData.GetBuffDataByDst`; `BuffApplyEvent`, `BuffExtensionEvent`, `BuffRemoveAllEvent`, `BuffRemoveSingleEvent`, `BuffRemoveManualEvent`; `BuffEvent.By` / `.To` | Existing buff uptime/volume aggregates only; local exporter reads typed target-indexed events | Buff ID, time, remover, affected target, removed duration and stack count exist in parsed objects. The source-indexed getter omits extensions, so the prototype reads by destination and deduplicates events. Keep `By` and `To` semantics; do not infer target from raw byte positions. |
| Ownership | `EvtcParser.FindAgentMaster`; EVTC `SrcMasterInstid` / `DstMasterInstid`; new local `AgentItem.OwnershipObservations` alongside `AgentItem.Master` | `JsonPlayer` minion membership only, no time-ranged relation; the local fork records each parsed master observation | The exporter forms half-open intervals from each observation to the next; the final observation extends to `LastAware`. Same-time conflicting observations resolve to the last record in EI's EVTC traversal order. Those boundary/tie assumptions are explicit, not proven lossless; corpus validation is required before product use. |
| Position samples | `CombatData.GetMovementData`; `PositionEvent.GetPoint3D`; `SingleActor` combat replay | Combat replay actor data exists only with replay parsing enabled; local exporter includes parsed position events when replay was computed | The source decodes packed position records to float32 coordinates. Replay polling is 300 ms; enabling replay can substantially grow output. |
| Multi-fight identity | CLI parses input files separately; `ParsedEvtcLog` is one parsed log | EI does not combine archive entries | Archive entry order and segment ordinal are explicit. Adapter grouping remains product-owned. |
| Actor/spec/squad/skill identity | `AgentItem`, `Player`, `SkillItem`, `LogMetadata` | Existing detailed JSON exports close equivalents; local DTO exports a subset | Export-local actor IDs preserve temporal slices. EI `UniqueID` is excluded. Player account/character/group and spec labels are mapped from `Player`; NPC/gadget identity uses parsed agent kind/species. Unknown values remain null. The prototype does not yet export map, guild, team, gear, weapons, or a skill dictionary. |

The JSON DTO project is `GW2EIJSON`; the existing DTO assembly point is `GW2EIBuilders.JsonModels.JsonLogBuilder.BuildJsonLog`, called by `RawFormatBuilder`. The prototype adds `GW2EIJSON/WvwExport.cs`, `GW2EIBuilders/WvwExportBuilder.cs`, records observations in `GW2EIEvtcParser/ParsedData/Agents/AgentItem.cs` from `EvtcParser.FindAgentMaster`, and writes an opt-in `_wvw_export_v1.json` sidecar from `GW2EIParserCommons.ProgramHelper`. Enable `SaveOutWvwExport=true` and `DetailledWvW=true` in a `.conf`; it calls the exporter on the already-parsed `ParsedEvtcLog` and does not re-read EVTC bytes. JSON nulls are retained by the dedicated serializer options.

The exporter has been compiled using .NET SDK 8.0.425 against the local v3.26.0.0 source. The repository's private 35-log corpus is absent locally; the only `.zevtc` in the workspace is a 990-byte sample that EI rejects as truncated before parsing. No real-log output, parity, or resource result is claimed. The exporter remains an experiment until valid-log validation proves all projections.

## Resource considerations

The executed 35-log gate measured 305.7 MB of existing detailed JSON total (0.37–29.88 MB, mean 8.73 MB), about 1.2–1.4x uncompressed input. It did not enable replay or measure peak memory. A normalized event list will add data; position samples are likely the largest increase. The sidecar is a transport format, not a persistence format. Record input bytes, output bytes, wall time, peak RSS, and event/sample counts for the same representative logs before setting a production budget. Do not enable replay by default before those measurements.

## Migration and acceptance gates

1. Freeze this schema and prove deterministic output from repeated parses.
2. Run a few representative private logs locally; keep logs, identities, generated JSON, and measurements containing identity outside Git and CI.
3. Run all 35 certified logs and compare fight boundaries, actor/slice identity, event counts by kind, timestamps, owner attribution, position availability, and buff removals against the existing parser. Record deltas per semantic field; do not call aggregate similarity parity.
4. Measure output size, wall time, and peak memory with replay both disabled and enabled if positions are needed.
5. Add a strict process adapter with pinned EI binary/source/config provenance, clear errors, and multi-file upload grouping. Do not put C# types in product services.
6. Remove `gw2_evtc_parser` only after shipped-field coverage, the complete 35-log parity set, multi-fight and ownership parity, position semantics, buff-removal semantics, deterministic output, resource budgets, adapter tests, persisted-data compatibility, and API/frontend regression gates all pass.

The EI fork/export work is separate from the Gw2Analytics runtime migration. This contract can be reviewed independently; it does not authorize production uploads through EI.
