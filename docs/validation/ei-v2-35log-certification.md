# WvW Export V2: 35-log certification

Status: **prototype certified for a process-adapter prototype; not a production
cutover**. Elite Insights is the canonical EVTC interpreter. Legacy-parser
comparisons measure migration and product impact; they do not decide which
parser's interpretation is correct.

## Certified source and method

- Elite Insights: `Roddygithub/GW2-Elite-Insights-Parser`, branch
  `feat/gw2analytics-wvw-export-v2`, commit
  `b8be784a670c78092089ace3f91bb7022d2bc8f5`.
- Base: reviewed V1 commit `062e250d55c0a09a7f734524287043c7852483b4`, on
  upstream Elite Insights `v3.26.0.0` commit
  `e4e548bf95b8a4901018a2c6a70058fc9c9e539f`.
- The existing 35-entry manifest resolved every log and verified its EVTC
  SHA-256 before the runs. The harness ran each input twice with the same
  configuration and compared the raw output bytes; it did not normalize JSON.
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
validation. Repeated output SHA-256 matched for every log. All seven logs that
previously varied only in `instance_id` also passed with byte-identical output;
V2 omits that unused non-stable field. The export's per-fight `actor_id` values
and references remained deterministic.

## Required event families

| V2 family | Events | Logs containing family | Aggregate |
| --- | ---: | ---: | ---: |
| `healing` | 46,247 | 33/35 | 29,776,408 healing units |
| `up` | 861 | 29/35 | exact EI `ChangeUp` transitions |
| `cc` | 2,491 | 31/35 | 3,642,340 ms canonical CC duration |

EI reported healing-extension data available for all 35 logs. Two logs contain
no timed healing events. Healing events preserve EI timestamp, source, target,
skill and amount. The V2 `up` fact is emitted from EI's `AliveEvent` projection
of the EVTC `ChangeUp` state change. CC facts preserve EI `CrowdControlEvent`
time, source, target, skill and `Duration`; no hard/soft classification is
inferred. Timed barrier remains deferred because no current shipped
event-window consumer requires it.

## Temporal-domain result

`duration_ms` remains the end of EI's active WvW phase. V2's
`event_domain_end_ms` is the greater of EI's raw recording end and the latest
timestamp in the exported canonical event stream. This includes derived EI
facts whose event time legitimately exceeds the last raw EVTC timestamp.
Exported event times remain relative to EI `LogStart` (zero); the exporter
subtracts that origin and does not clamp or drop timestamps.

The three known tail records are EI-created Scourge shade expiry removals in
`ScourgeHelper`, using `shade.Time + duration`:

| Log | Active duration | V2 event-domain end | Preserved late event |
| --- | ---: | ---: | ---: |
| `20260205-231349` | 56,789 ms | 56,974 ms | 56,974 ms |
| `20260508-001302` | 285,414 ms | 286,971 ms | 286,971 ms |
| `20260327-223844` | 45,064 ms | 51,167 ms | 51,167 ms |

Each V2 export validates and repeats byte-for-byte in both replay modes. Across
the corpus event timestamps range from 0 to 455,850 ms; positions range from 1
to 455,877 ms. The event-domain maximum is 456,001 ms. Validation found no
event, awareness, ownership, or position timestamp outside its V2 domain.

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
| Enabled | 459,458,586 | 9.0809x | 88.166 s | 350.9 MiB |
| Disabled | 375,221,650 | 7.4160x | 82.083 s | 338.0 MiB |

The RSS sample is `VmRSS` from the direct `dotnet` process; child processes are
not included. Replay adds 84,236,936 output bytes, 525,221 position samples,
6.083 seconds of measured wall time, and 12.9 MiB to the sampled peak RSS.
Compared with the historical V1 report, V2 output grew by 10,937,112 bytes
(2.44% replay enabled; 3.00% disabled). Measured full-corpus wall time rose
from 52.461 s to 88.166 s with replay and from 51.726 s to 82.083 s without
replay; this is a material increase to track. Current per-log maximum was
5.778 s. Peak sampled memory remained about 351 MiB. This is acceptable for a
bounded prototype; a process-adapter benchmark must set and verify an
operational budget before production use.

## Shipped-feature coverage and decision

The three previously identified shipped gaps are now direct canonical facts in
V2: timed healing, up/rally transitions, and timed CC. No unexplained
`MISSING_EI_EXPORT` remains among the 21 requirements classified in the
current shipped-feature audit. Reclassification moves those three rows to
`EI_CANONICAL_DIRECT`; `instance_id` moves to `NOT_CURRENTLY_SHIPPED`: the
internal `Agent` model has the field, but `AgentOut` does not expose it and the
current production API/analytics paths do not consume it. V2 intentionally
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
is valid and deterministic across the full reference corpus, the three event
families required by current shipped event-window behavior are present, the
time envelope explicitly accommodates EI-derived timestamps, actor identity
is deterministic without `instance_id`, ownership behavior is unchanged, and
replay cost is measured. This does not validate upload-level multi-log
grouping, persistence compatibility, API/frontend continuity, or production
budgets; those remain required before any production cutover. No production
adapter, API, database, or frontend behavior changed in this slice.
