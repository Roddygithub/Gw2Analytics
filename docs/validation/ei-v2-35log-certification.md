# WvW Export V2: 35-log certification

Status: **prototype certified for a process-adapter prototype; not a production
cutover**. Elite Insights is the canonical EVTC interpreter. Legacy-parser
comparisons measure migration and product impact; they do not decide which
parser's interpretation is correct.

## Certified source and method

- Elite Insights: `Roddygithub/GW2-Elite-Insights-Parser`, branch
  `feat/gw2analytics-wvw-export-v2`, commit
  `445eeb80e373b4597b0b38f9fbf90099c475fefc`.
- Base: reviewed V1 commit `062e250d55c0a09a7f734524287043c7852483b4`, on
  upstream Elite Insights `v3.26.0.0` commit
  `e4e548bf95b8a4901018a2c6a70058fc9c9e539f`.
- The existing 35-entry manifest resolved every log and verified its EVTC
  SHA-256 before the runs. The hardened harness ran each input twice with the
  same configuration: it stored the first output bytes, deleted the export
  sidecar, verified that no matching export remained, reran EI, required
  exactly one freshly produced output, and compared its raw bytes against the
  first run; it did not normalize JSON and never reused a resolved path as
  proof of a fresh export. The harness rejects a repeat run that produces no
  output or more than one output as a failure.
- The machine-readable, aggregate-only measurements are in
  [`ei-v2-35log-certification.json`](ei-v2-35log-certification.json). Per-log
  rows identify certification logs by manifest stem and contain no player
  identity fields.

## Certification result

| Replay setting | Produced | V2 valid | Exact-byte repeats | Combined pass |
| --- | ---: | ---: | ---: | ---: |
| Enabled | 35/35 | 35/35 | 35/35 | 35/35 |
| Disabled | 35/35 | 35/35 | 35/35 | 35/35 |

Every export passed the versioned schema, actor/event reference checks,
contiguous event sequence, ordering, finite-position, and timestamp-domain
validation, including the new `duration_ms <= recording_end_ms <=
event_domain_end_ms` relation and the exact event-domain definition. Repeated
output SHA-256 matched for every log. All seven logs that previously varied
only in `instance_id` also passed with byte-identical output; V2 omits that
unused non-stable field. The export's per-fight `actor_id` values and
references remained deterministic, and the new ambiguity guard never fired on
the corpus.

The remediation rerun also restored V1 ownership reference, agent-awareness,
owner-awareness-at-observation, and canonical-order checks. The V2 envelope
again enforces unique canonical fight IDs, source-log indexes, and fight order,
while allowing multiple segments to refer to one source log. Healing events
require `healing_available=true`; the reverse is intentionally not required.

## Required event families

| V2 family | Events | Logs containing family | Aggregate |
| --- | ---: | ---: | ---: |
| `healing` | 46,247 | 33/35 | 29,776,408 healing units |
| `up` | 861 | 29/35 | exact EI `ChangeUp` transitions |
| `cc` | 2,491 | 31/35 | 3,642,340 ms canonical CC duration |

EI reported healing-extension data available for all 35 logs. Two logs contain
no timed healing events. Healing events preserve EI timestamp, source, target,
skill and amount. Every V2 `up` fact is now verified at export time to carry
the canonical EVTC `ChangeUp` state change — the pinned factory creates
`AliveEvent` from nothing else, and any broader alive-state semantic reaching
the V2 path fails the export loudly instead of being mislabeled; the count is
unchanged from the prior certification. CC facts preserve EI `CrowdControlEvent`
time, source, target, skill and `Duration`; no hard/soft classification is
inferred. Timed barrier remains deferred because no current shipped
event-window consumer requires it.

## Temporal-domain result

V2 exposes three distinct concepts:

- `duration_ms` — EI's active WvW phase end (`LogData.LogEnd`).
- `recording_end_ms` — EI's raw EVTC recording end (`EvtcLogEnd`), relative
  to the same origin as event timestamps.
- `event_domain_end_ms` — `max(recording_end_ms, latest exported canonical
  event timestamp)`; the temporal envelope of the EI projection.

The exporter requires `duration_ms <= recording_end_ms <= event_domain_end_ms`
and defines the domain end exactly. `WvWLogic` never sets a success end, so for
all 35 corpus logs the active phase ends at the raw recording end and
`duration_ms == recording_end_ms`; three logs then project canonical EI-derived
events beyond it. Raw-recording facts — agent awareness, positions, ownership —
are validated against `recording_end_ms`, not the broader event domain.
Exported event times remain relative to EI `LogStart` (zero); the exporter
does not clamp or drop timestamps.

The three known tail records are EI-created Scourge shade expiry removals in
`ScourgeHelper`, using `shade.Time + duration`:

| Log | Active duration | Recording end | V2 event-domain end | Preserved late event |
| --- | ---: | ---: | ---: | ---: |
| `20260205-231349` | 56,789 ms | 56,789 ms | 56,974 ms | 56,974 ms |
| `20260508-001302` | 285,414 ms | 285,414 ms | 286,971 ms | 286,971 ms |
| `20260327-223844` | 45,064 ms | 45,064 ms | 51,167 ms | 51,167 ms |

Each of the three logs contains exactly one event after its recording end, and
each V2 export validates and repeats byte-for-byte in both replay modes.
Across the corpus event timestamps range from 0 to 455,850 ms; positions range
from 1 to 455,877 ms. The event-domain maximum is 456,001 ms. Validation found
no event, awareness, ownership, or position timestamp outside its V2 domain.

## Ownership and positions

V2 preserves the V1 EI ownership projection. Across the corpus there are
326,265 master observations, 199,602 same-time collision records, 125,604
intervals, 9,061 explicitly unresolved intervals, and two observed owner
changes. The prior collision audit found 87,894 same-time groups and no group
with conflicting owners; the deterministic EI traversal tie rule is unchanged.
These aggregates match the V1 certification.

Replay enabled exported 525,221 EI position samples; replay disabled exported
none. V2 preserved the same coordinates and ordering rules as V1. Position
selection, downsampling, and heatmap calculation remain product concerns.

## Resource measurements

The corpus totals 50,596,242 compressed input bytes. V2 first-export totals
were:

| Replay setting | JSON bytes | Weighted expansion | Wall time | Maximum sampled direct-dotnet VmRSS |
| --- | ---: | ---: | ---: | ---: |
| Enabled | 459,459,753 | 9.0809x | 71.305 s | 346.8 MiB |
| Disabled | 375,222,817 | 7.4160x | 71.971 s | 347.4 MiB |

The RSS sample is `VmRSS` from the direct `dotnet` process; child processes are
not included. Replay adds 84,236,936 output bytes and 525,221 position samples;
the two wall-time totals differ by less than one second in this run and the
sampled peak RSS by 0.6 MiB. Compared with the prior V2 run the JSON grew by
1,167 bytes — exactly the new `recording_end_ms` field across the 70 exports —
while event, ownership, and position content is unchanged. Measured full-corpus
wall time rose from 57.297 s to 71.305 s with replay and from 55.354 s to
71.971 s without; the previous runs and this one were taken on the same
machine under different ambient load, and per-log maxima moved from 4.454 s to
5.462 s (enabled) and 4.781 s (disabled) in the same proportion, which points
at machine variance rather than an export-content change. Peak sampled memory
remained about 347 MiB. A process-adapter benchmark must still set and verify
an operational budget before production use.

## Shipped-feature coverage and decision

The three previously identified shipped gaps are direct canonical facts in
V2: timed healing, up/rally transitions, and timed CC. No unexplained
`MISSING_EI_EXPORT` remains among the 21 requirements classified in the
current shipped-feature audit. Reclassification moves those three rows to
`EI_CANONICAL_DIRECT`; `instance_id` moves to `NOT_CURRENTLY_SHIPPED`: the
internal `Agent` model has the field, but `AgentOut` does not expose it and
the current production API/analytics paths do not consume it. V2 intentionally
omits it; a future adapter must not substitute a placeholder identity. Timed
barrier remains deferred. The only remaining `PRODUCT_CHANGE_REQUIRED` row is
the deliberate choice whether to consume EI buff uptime aggregates or derive
the product's uptime from faithfully exported EI buff events; it is a product
semantics decision, not missing event data.

| Classification | Current requirement rows |
| --- | ---: |
| `EI_CANONICAL_DIRECT` | 12 |
| `EI_CANONICAL_TRANSFORM` | 1 |
| `PRODUCT_DERIVED` | 3 |
| `MISSING_EI_EXPORT` | 0 |
| `PRODUCT_CHANGE_REQUIRED` | 1 |
| `NOT_CURRENTLY_SHIPPED` | 4 |

Decision: **`READY_FOR_PROCESS_ADAPTER_PROTOTYPE`**. The exact pinned EI export
is valid and deterministic across the full reference corpus under the hardened
repeat harness, `up` is pinned to the canonical EVTC `ChangeUp` transition, the
actor-slice fallback refuses ambiguous references instead of guessing, the
time envelope explicitly separates active, raw-recording, and projected
boundaries, actor identity is deterministic without `instance_id`, ownership
behavior is unchanged, and replay cost is measured. This does not validate
upload-level multi-log grouping, persistence compatibility, API/frontend
continuity, or production budgets; those remain required before any production
cutover. No production adapter, API, database, or frontend behavior changed in
this slice.
