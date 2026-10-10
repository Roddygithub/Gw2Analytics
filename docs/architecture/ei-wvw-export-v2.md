# WvW Elite Insights export V2

Status: prototype. Elite Insights remains the canonical EVTC interpreter; V2 is
a process/JSON transport contract and does not switch the production parser
adapter.

## Source findings (pinned EI 3.26.0.0 fork)

### Timed healing

The healing-stats extension handler creates `EXTDirectHealingEvent` and
`EXTNonDirectHealingEvent`, both derived from `EXTHealingEvent`. The common
`SkillEvent` fields provide `Time`, `From`, `To`, and `SkillID`; the healing
subtype provides `HealingDone`. Direct healing reads `-CombatItem.Value`, while
non-direct healing reads `-CombatItem.BuffDmg`. The event has no overheal
property. Barrier has separate `EXTBarrierEvent` types. `CombatData.HasEXTHealing`
is true when the extension handler attached its event collection; without the
extension EI cannot provide the timed healing records through this collection.
The export will report that availability explicitly and will not synthesize
events from aggregate totals. Event references will be deduplicated by object
identity because EI indexes each event by both source and recipient.

Shipped consumers require timestamped healing amount, source, target and skill
for timeline HPS and per-target/event-window healing. No shipped event-window
consumer requires timed barrier.

### Up/rally

`CombatEventFactory.AddStateChangeEvent` maps the EVTC `StateChange.ChangeUp`
record to `AliveEvent`, indexed by `Src`; the pinned source creates
`AliveEvent` nowhere else and the class exposes no custom-event constructor,
so `CombatData.GetAliveEvents` can only contain raw ChangeUp records.
Because the base `StatusEvent` discarded the raw combat item, `AliveEvent`
now retains its `StateChange` property. The V2 exporter verifies it at
export time and emits `up` only for the canonical `StateChange.ChangeUp`
transition, throwing a narrow `InvalidDataException` if any broader
alive-state semantic ever reaches the V2 path. V2 will not infer rally from
health, spawn, death, or alive-state sequences. This is the canonical actor
transition consumed by the shipped pre-down contribution windows. The V1
`alive` projection of `GetAliveEvents` is unchanged.

### Timed CC

`CombatEventFactory` constructs `CrowdControlEvent` for the canonical
`DamageResult.CrowdControl` result. It inherits `Time`, `From`, `To`, and
`SkillID` from `SkillEvent`; `CrowdControlEvent.Duration` is populated from
`CombatItem.Value`. `DefianceCalculation` is a separate getter (`Value +
OverstackValue`) and is not the current shipped contribution metric. The
Gw2Analytics consumer counts the canonical CC records in pre-down windows and
sums `Duration`. V2 therefore exports source, target, skill and duration only;
it does not claim a hard/soft classification or add breakbar/cast machinery.

### Temporal domain

For WvW, `GetGenericLogOffset` returns `LogData.EvtcLogStart`. `EvtcParser`
subtracts this offset from combat records and agent awareness; `LogData.LogStart`
is zero after offset application. Thus V2 timestamps remain milliseconds since
the EI EVTC recording origin.

`LogLogicPhaseUtils.GetInitialPhase` creates the WvW full-fight phase from
`LogStart` to `LogEnd`. `LogData.LogDuration` aliases `LogEnd`. On success,
`LogEnd` is set to the success time plus EI's server-delay constant, capped at
`EvtcLogEnd`; this is the active analyzed fight boundary. `EvtcLogEnd` is the
raw recording boundary, initialized from the final parsed combat-record time
and offset with the rest of the EVTC metadata.

`EvtcParser.ParseCombatList` continues retaining extension records after a
`SquadCombatEnd` marker (non-extension records are then filtered), and
`CombatData` builds buff events from those retained records without filtering
them to `LogDuration`. The exact late events in the three V1 certification
cases are also produced by
`EIData/ProfHelpers/Necromancer/ScourgeHelper.cs`: EI projects a shade effect as
an apply at `shade.Time` and a single removal at `shade.Time + duration`, where
the duration is derived from the EI effect end and the build's expected
duration. That canonical synthetic removal can exceed the last raw EVTC
timestamp. The observed times are 56,974 ms vs. a 56,789 ms recording end,
286,971 ms vs. 285,414 ms, and 51,167 ms vs. 45,064 ms.

V2 represents three distinct temporal concepts per fight:

- `duration_ms` is the active EI analyzed-fight boundary (`LogData.LogEnd`).
- `recording_end_ms` is EI's raw EVTC recording end (`LogData.EvtcLogEnd`),
  relative to the same origin as event timestamps.
- `event_domain_end_ms` is `max(recording_end_ms, latest exported canonical
  event timestamp)`. It describes the temporal envelope of the EI projection,
  including EI-derived events, instead of asserting that every projected
  event occurred inside the raw recording interval.

The exporter requires `duration_ms <= recording_end_ms <= event_domain_end_ms`.
For WvW, `WvWLogic` never calls `SetSuccess`, so EI's active WvW phase ends at
the raw recording end and the corpus logs have
`duration_ms == recording_end_ms`; the relation still guards future logs
where the active phase ends earlier than the recording. Events may extend to
`event_domain_end_ms`; none are clamped or dropped. Raw-recording facts —
agent awareness, positions, ownership — retain their EI-specific guarantee of
staying inside `recording_end_ms` and are not broadened merely because a
derived event extends the event domain.

The V1 exporter does not expose `FightData` objects; WvW's V1/V2 fight envelope
is the EI full WvW phase. Any instance-log segmented phases are a separate
future grouping concern and are not inferred as additional fights in this
slice.

### Actor identity and `instance_id`

`AgentItem.InstID` is assigned from the first observed nonzero instance ID by
`EvtcParser.UpdateAgentData`; EI does not document it as a stable serialized
identity. The prior certification observed changes in this metadata while
actor references and event ordering stayed stable. The product `Agent` model
contains the field, but the API `AgentOut` does not expose it. The
`TemporalIdentityResolver` and merged-minion-uptime helper have unit-tested
support for it, but the current runtime call sites found are in `ei_compare`,
the CLI migration-comparison tool; production API/analytics paths do not call
them. Within-fight references use actor IDs and ownership is explicit. V2
therefore omits this non-stable field. A future adapter must treat it as
unavailable rather than use a placeholder as an identity; any proven shipped
need would require a separate EI/export contract decision.

The V2 actor ordering key excludes `InstID` and ends with the raw EVTC agent
address (`Agent`) after awareness, type, species and name. Event-to-actor
resolution uses the same raw address and awareness slice. `UniqueID` is
explicitly documented by EI as nondeterministic and is not used. This preserves
within-fight references without inventing cross-log identity or deriving IDs
from player names.

Independent review verified how the V2 slice fallback can trigger and whether
its previous `FirstOrDefault` selection was safe. Pinned EI does not prove
uniqueness of a `(raw Agent, timestamp)` slice:

- `AgentData.GetAgent` returns the first agent by `FirstAware` whose awareness
  contains the timestamp, silently choosing among overlaps.
- `EvtcParser.UpdateAgentData` expands awareness to cover every attributed
  event, and events without an instance ID always extend the first same-address
  slice; awareness windows are therefore constructed, not disjoint by design.
- The orphaned instance-ID repair matches candidates with a plus-or-minus
  300 ms slack and can extend a window into a neighboring slice's range.

The V2 fallback therefore now gathers all candidate slices for the raw
address that are aware at the event timestamp: zero candidates keep the
existing null behavior, exactly one candidate is used, and more than one
distinct slice raises a narrow `InvalidDataException` instead of exporting a
potentially wrong actor reference. `InstID` is not reintroduced. The V1
fallback keeps its certified instance-ID and shortest-window selection.

## Minimal V2 delta

- `schema_version = 2` and a separate `_wvw_export_v2.json` artifact.
- Active `duration_ms`, raw `recording_end_ms`, and `event_domain_end_ms`,
  which covers raw recording time and any later EI-derived event timestamp,
  with `duration_ms <= recording_end_ms <= event_domain_end_ms`.
- Per-fight `healing_available` marker.
- Strict `healing`, `up` (canonical EVTC `ChangeUp` only), and `cc` event
  variants.
- No actor `instance_id`.

V1 schema, exporter switch, fixtures, and certification evidence remain
unchanged. The V2 certification is a new report and uses exact output bytes for
repeat determinism.

## V2 certification outcome

The certified candidate is the separate EI branch
`feat/gw2analytics-wvw-export-v2` at
`445eeb80e373b4597b0b38f9fbf90099c475fefc`. Across all 35 manifest logs,
replay-enabled and replay-disabled exports were each 35/35 produced, schema
valid, and byte-identical under the hardened repeat harness, which deletes
the first sidecar and requires exactly one freshly produced output per
repeat. The three late Scourge shade expiry events are preserved; the
computed event-domain end includes their canonical EI event times while the
new `recording_end_ms` keeps the raw recording boundary explicit. The seven
previous `instance_id`-variation logs also repeat exactly; V2 contains no
`instance_id` field, and the V2 slice fallback's ambiguity guard never fired
on the corpus.

See the [executed certification and aggregate resource report](../validation/ei-v2-35log-certification.md).
V2 is ready for a separately reviewed process-adapter prototype only. This
does not validate upload-level multi-log grouping or authorize production
cutover.
