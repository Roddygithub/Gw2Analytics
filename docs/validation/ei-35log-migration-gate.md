# Pinned WvW Elite Insights 35-log migration gate

**Decision: `NEEDS_EI_EXPORT_EXTENSION`.** This is a validation slice, not production parser cutover.

> **Elite Insights is the canonical EVTC interpreter.** Legacy parser comparisons measure migration and product impact, not parser truth. The first question for any difference is whether EI’s parsed fact was faithfully transported. If it was, EI remains canonical and the product impact is assessed separately.

## Scope and provenance

The certification used the existing stratified manifest at [`scripts/ei-parity/corpus-manifest.json`](../../scripts/ei-parity/corpus-manifest.json): exactly 35 unique entries. All 35 local files existed, matched the manifest EVTC SHA-256, and none was Git-tracked. The private logs and generated exports remained local and ignored. Tracked results identify logs only by the manifest filename stem; no player/account identity is included.

- Gw2Analytics baseline: `7573f8a7c7a1e42bf9f09f70a2e197fa78fb2534`.
- Canonical EI fork: [`Roddygithub/GW2-Elite-Insights-Parser`](https://github.com/Roddygithub/GW2-Elite-Insights-Parser), branch `gw2analytics-wvw-export-v1`, commit [`062e250d55c0a09a7f734524287043c7852483b4`](https://github.com/Roddygithub/GW2-Elite-Insights-Parser/commit/062e250d55c0a09a7f734524287043c7852483b4), based on EI v3.26.0.0 (`e4e548bf95b8a4901018a2c6a70058fc9c9e539f`).
- Export configuration: one input per invocation, WvwExportV1 enabled, single-threaded, detailed WvW, combat replay on for primary run; every input was exported twice with identical settings.
- Harness: [`scripts/ei-certification/certify_wvw_export.py`](../../scripts/ei-certification/certify_wvw_export.py). Machine-readable aggregate/per-log data: [`ei-35log-migration-gate.json`](ei-35log-migration-gate.json). The harness requires caller-supplied local paths and checks the manifest hashes and exact EI HEAD before parsing.

Reproduce both modes with local path variables (the private corpus location is intentionally not recorded here):

```sh
uv run python scripts/ei-certification/certify_wvw_export.py \
  --manifest scripts/ei-parity/corpus-manifest.json \
  --corpus "$CORPUS_ROOT" \
  --ei-source "$EI_CHECKOUT" \
  --dotnet "$DOTNET" \
  --cli "$EI_CHECKOUT/GW2EI.bin/Release/CLI/GuildWars2EliteInsights-CLI.dll" \
  --output "$REPORT_ROOT/run" \
  --replay-disabled-report "$REPORT_ROOT/aggregate-report.json"
```

## Certification result

| Mode | Schema-valid | Byte-identical repeats | Both valid and identical | Result |
| --- | ---: | ---: | ---: | --- |
| Replay enabled | 32/35 | 28/35 | 25/35 | Failed certification gate |
| Replay disabled | 32/35 | 28/35 | 25/35 | Failed certification gate |

The three invalid logs each contain exactly one `buff_remove_single` event after the exported fight duration. The exporter does not clamp the timestamp; the product validator rejects it. EI’s event timestamps use `event.Time - LogStart`, and actor awareness, ownership and positions use that same origin. All actor awareness, ownership, and position ranges are within `0..duration_ms`; event ranges are valid except for the three identified rows. Across valid events the time range was `0..455850 ms`; declared durations ranged from `10888` to `456001 ms` (median `63351 ms`). Position sample times ranged from `1` to `455877 ms`. No clamping occurred.

| Log stem | Duration ms | Event max ms | Events beyond duration | Validation |
| --- | ---: | ---: | ---: | --- |
| `20260205-231349` | 56789 | 56974 | 1 | rejected: event time exceeds fight duration |
| `20260508-001302` | 285414 | 286971 | 1 | rejected: event time exceeds fight duration |
| `20260327-223844` | 45064 | 51167 | 1 | rejected: event time exceeds fight duration |

Seven logs were not byte-deterministic. Exact structural comparison of repeated exports showed changes only at `fights[0].actors[*].instance_id`; there were no changed actor IDs, event records, ordering, or other JSON paths. A temporary local EI diagnostic correlated all 36 changed actor records with EI fake-agent metadata: none were `IsFake`. The current exporter reads `AgentItem.InstID` directly. This isolates the observed instability to EI’s parsed actor instance IDs (or their upstream assignment), not JSON serialization or exporter ordering. The precise upstream cause remains unresolved, so determinism is not certified.

Nondeterministic manifest stems: `20260125-194936`, `20260224-233019`, `20260412-220632`, `20260424-204954`, `20260519-112129`, `20260526-202841`, `20260506-211522`.

## Aggregate results and resource measurements

Peak RSS is sampled from the EI process every 10 ms; it is approximate. Wall time is the first export per log. Per-log values, exact event-kind counts, hashes, validation failures and repeat status are in the JSON report.

| Metric | Replay enabled | Replay disabled |
| --- | ---: | ---: |
| Input EVTC total bytes | 50,596,242 | 50,596,242 |
| WvwExportV1 total bytes | 448,521,474 | 364,284,538 |
| Weighted expansion ratio | 8.8647x | 7.1998x |
| Per-log output bytes median / p95 / max | 6,480,818 / 43,676,966 / 50,263,190 | 5,062,074 / 35,811,485 / 42,987,272 |
| First-run wall time total | 52.461 s | 51.726 s |
| Per-log wall time median / p95 / max | 1.185 / 3.106 / 3.421 s | 1.163 / 2.928 / 3.042 s |
| Sampled peak RSS median / p95 / max | 149.7 / 336.5 / 338.1 MB | 147.9 / 332.7 / 336.5 MB |
| Actors | 24,561 | 24,561 |
| Events | 1,260,163 | 1,260,163 |
| Ownership observations / intervals / owner changes | 326,265 / 125,604 / 2 | 326,265 / 125,604 / 2 |
| Unresolved ownership intervals | 9,061 | 9,061 |
| Position samples | 525,221 | 0 |

Replay positions added 84,236,936 bytes (23.1239%) and 525,221 position samples over 35 logs. Total observed wall time increased 0.735 s (1.42%); maximum sampled RSS increased 1.6 MB. This is acceptable for this local prototype run, but not yet a production budget.

### Event counts by kind

| Kind | Count |
| --- | ---: |
| `damage` | 202,115 |
| `buff_apply` | 412,256 |
| `buff_extension` | 22,591 |
| `buff_remove_all` | 92,720 |
| `buff_remove_single` | 163,050 |
| `buff_remove_manual` | 192,504 |
| `down` | 1,097 |
| `death` | 2,171 |
| `alive` | 861 |
| `spawn` | 6,820 |
| `despawn` | 6,827 |
| `health_update` | 157,151 |

### Per-log aggregates (replay enabled)

| Log stem | Input bytes | JSON bytes | Ratio | Wall s | RSS MB | Actors | Events | Ownership obs. / collisions / intervals | Unresolved | Positions | Repeat identical |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | :---: |
| `20260128-160105` | 65,826 | 421,954 | 6.4101x | 0.858 | 120.8 | 41 | 980 | 241 / 137 / 104 | 0 | 827 | yes |
| `20260122-223116` | 337,565 | 3,223,060 | 9.548x | 1.053 | 132.5 | 370 | 8,785 | 3,792 / 2,289 / 1,495 | 0 | 2,637 | yes |
| `20260125-194936` | 1,183,267 | 8,612,028 | 7.2782x | 1.318 | 155.0 | 824 | 19,856 | 8,803 / 5,213 / 3,577 | 0 | 15,028 | no |
| `20260129-110256` | 3,137,448 | 31,723,687 | 10.1113x | 1.979 | 240.1 | 2,055 | 93,840 | 18,596 / 11,944 / 6,641 | 198 | 30,082 | yes |
| `20260213-213832` | 71,824 | 416,896 | 5.8044x | 0.837 | 122.4 | 74 | 1,096 | 303 / 199 / 104 | 0 | 537 | yes |
| `20260210-235749` | 299,118 | 3,269,059 | 10.929x | 0.959 | 129.4 | 261 | 10,911 | 863 / 540 / 322 | 0 | 1,878 | yes |
| `20260205-231349` | 1,182,465 | 11,092,568 | 9.3809x | 1.347 | 166.1 | 466 | 34,055 | 5,200 / 3,219 / 1,973 | 19 | 10,055 | yes |
| `20260224-233019` | 3,157,410 | 26,096,759 | 8.2652x | 2.307 | 231.4 | 1,525 | 69,471 | 16,852 / 9,623 / 7,192 | 1,376 | 37,672 | no |
| `20260316-231209` | 88,660 | 459,554 | 5.1833x | 0.817 | 121.9 | 74 | 872 | 452 / 297 / 153 | 0 | 1,105 | yes |
| `20260309-233818` | 501,564 | 4,017,740 | 8.0104x | 1.072 | 135.4 | 164 | 10,801 | 3,027 / 1,589 / 1,427 | 0 | 5,429 | yes |
| `20260324-013930` | 1,800,795 | 22,304,659 | 12.386x | 1.746 | 203.7 | 1,384 | 63,395 | 27,933 / 17,231 / 10,688 | 1,218 | 15,743 | yes |
| `20260314-234454` | 3,825,189 | 34,583,630 | 9.041x | 2.380 | 280.1 | 2,136 | 98,603 | 22,894 / 13,645 / 9,213 | 258 | 39,142 | yes |
| `20260409-004339` | 71,474 | 422,859 | 5.9163x | 0.858 | 122.4 | 39 | 853 | 376 / 246 / 129 | 0 | 986 | yes |
| `20260429-222732` | 425,023 | 5,429,951 | 12.7757x | 1.145 | 137.5 | 346 | 18,106 | 2,658 / 1,776 / 881 | 0 | 2,302 | yes |
| `20260412-220632` | 1,272,900 | 11,834,842 | 9.2975x | 1.450 | 172.5 | 957 | 33,181 | 10,171 / 6,363 / 3,793 | 8 | 12,634 | no |
| `20260424-204954` | 3,172,390 | 24,210,280 | 7.6316x | 2.452 | 227.3 | 1,655 | 58,390 | 21,767 / 13,114 / 8,584 | 1,381 | 39,434 | no |
| `20260519-112129` | 85,153 | 603,587 | 7.0883x | 0.879 | 126.4 | 40 | 1,673 | 652 / 420 / 228 | 0 | 739 | no |
| `20260512-181500` | 503,413 | 3,159,654 | 6.2765x | 1.052 | 136.7 | 84 | 7,501 | 1,098 / 597 / 483 | 0 | 7,454 | yes |
| `20260526-202841` | 1,777,720 | 17,597,478 | 9.8989x | 1.686 | 196.6 | 197 | 53,123 | 12,619 / 7,980 / 4,593 | 26 | 15,700 | no |
| `20260508-001302` | 4,777,568 | 41,920,510 | 8.7744x | 2.939 | 317.9 | 2,522 | 119,185 | 20,993 / 12,546 / 8,407 | 379 | 51,433 | yes |
| `20260608-011208` | 93,682 | 534,960 | 5.7104x | 0.974 | 124.1 | 94 | 1,323 | 324 / 210 / 112 | 0 | 918 | yes |
| `20260618-182428` | 471,903 | 5,538,697 | 11.7369x | 1.129 | 137.4 | 108 | 16,677 | 5,192 / 3,227 / 1,948 | 0 | 3,982 | yes |
| `20260621-225056` | 1,748,318 | 13,564,992 | 7.7589x | 1.608 | 182.7 | 626 | 35,611 | 13,653 / 8,902 / 4,686 | 0 | 19,397 | yes |
| `20260625-215943` | 5,285,237 | 43,676,966 | 8.264x | 3.106 | 338.1 | 1,340 | 128,154 | 28,277 / 17,738 / 10,387 | 753 | 49,344 | yes |
| `20260717-225125` | 80,961 | 641,880 | 7.9283x | 0.961 | 126.0 | 149 | 1,897 | 111 / 81 / 30 | 0 | 713 | yes |
| `20260705-234656` | 301,975 | 2,029,237 | 6.7199x | 1.001 | 128.7 | 144 | 5,631 | 1,778 / 1,142 / 616 | 0 | 2,629 | yes |
| `20260712-203400` | 1,285,992 | 11,666,598 | 9.0721x | 1.831 | 172.6 | 1,005 | 35,933 | 6,814 / 4,206 / 2,560 | 0 | 10,229 | yes |
| `20260708-215736` | 3,118,363 | 19,961,023 | 6.4011x | 1.985 | 213.7 | 1,189 | 39,262 | 31,295 / 18,489 / 12,632 | 238 | 43,246 | yes |
| `20260118-020548` | 1,650,723 | 15,745,985 | 9.5388x | 1.533 | 179.8 | 1,712 | 42,314 | 9,496 / 5,551 / 3,921 | 315 | 19,254 | yes |
| `20260217-210926` | 312,088 | 1,920,847 | 6.1548x | 0.939 | 128.3 | 139 | 3,750 | 1,840 / 1,083 / 755 | 0 | 4,683 | yes |
| `20260327-223844` | 585,556 | 4,825,834 | 8.2415x | 1.072 | 136.2 | 418 | 12,445 | 2,989 / 1,793 / 1,195 | 0 | 7,300 | yes |
| `20260428-222420` | 175,661 | 1,030,279 | 5.8652x | 0.888 | 128.7 | 68 | 2,021 | 1,129 / 690 / 439 | 0 | 2,362 | yes |
| `20260506-211522` | 736,853 | 6,480,818 | 8.7953x | 1.185 | 149.7 | 542 | 17,348 | 3,978 / 2,501 / 1,471 | 233 | 8,943 | no |
| `20260610-212627` | 5,036,388 | 50,263,190 | 9.98x | 3.421 | 336.5 | 1,427 | 152,276 | 33,471 / 21,121 / 12,207 | 2,642 | 45,022 | yes |
| `20260718-154555` | 1,975,770 | 19,239,413 | 9.7377x | 1.694 | 199.7 | 386 | 60,844 | 6,628 / 3,900 / 2,658 | 17 | 16,382 | yes |

## Ownership collision audit

Across the 35 logs, EI recorded 326,265 ownership observations and the exporter produced 125,604 intervals. The sidecar reported 199,602 same-time collision records across 87,894 minion/timestamp groups; every group repeated the same owner, and zero groups contained conflicting owners. This was measured with a temporary local-only aggregate diagnostic in the EI builder, then that diagnostic was removed and the checkout restored to the pinned clean commit. The deterministic tie rule uses EI observation traversal order; observed repeated-owner groups make the tie outcome immaterial for this corpus. There were two observed owner changes in the generated interval sequences and 9,061 unresolved owner intervals across 15 logs; the sidecar preserves these as unresolved instead of inferring unowned state.

## Shipped-feature consumer audit

The audit traced parser-derived data from `parser_adapter.py` into persisted event blobs and current fight/player routes and aggregators. Key consumers include `/fights/{id}/timeline`, `/events`, target aggregates, squad/subgroup summaries, combat readout, positions, player profiles and comparisons. Persisted player summaries calculate historical metrics from event streams. The webhook dispatcher reports upload/subscription status and has no combat-derived payload consumer.

The classifications below are mutually exclusive at the requirement-row level and use the requested six categories. They describe current product requirements, not equality with the old parser.

| Requirement | Classification | Evidence / product impact |
| --- | --- | --- |
| Fight duration, outcome and actor awareness | `EI_CANONICAL_DIRECT` | Standard EI output plus WvwExportV1 fight, actor and time fields. |
| Actor, profession/spec, subgroup and target identity | `EI_CANONICAL_TRANSFORM` | EI facts are available; adapter must translate canonical identities to product actor references and join target arrays. |
| Damage event source/target/skill/time and health/shield damage | `EI_CANONICAL_DIRECT` | WvwExportV1 `damage` event. |
| Fight/player damage, strike/condition split, per-skill and per-target damage | `EI_CANONICAL_DIRECT` | Detailed-WvW EI aggregates; product may consume aggregates or derive values from exported facts where available. |
| Whole-fight outgoing/incoming healing and barrier metrics | `EI_CANONICAL_DIRECT` | EI detailed-WvW healing/barrier aggregates and distributions. |
| Event-window HPS and time-ranged per-target healing | `MISSING_EI_EXPORT` | `/timeline` and `/events` bucket `HealingEvent` by event timestamp; aggregate EI healing has no event time. |
| Buff applies, extensions and removal variants for strips/cleanses | `EI_CANONICAL_DIRECT` | WvwExportV1 exports apply, extension, remove-all, remove-single and remove-manual events with EI By/To semantics. |
| Buff stack activation and uptime | `PRODUCT_CHANGE_REQUIRED` | Standard EI buff-state/uptime projections are available, but using them changes the current product’s recomputation semantics. Decide and assess persisted/API continuity; do not require the legacy result as authority. |
| Downs/deaths and whole-fight defense counts | `EI_CANONICAL_DIRECT` | Standard EI summaries and sidecar down/death facts. |
| Rally/up transition for down-state segment construction | `MISSING_EI_EXPORT` | Current `DownContributionAggregator` consumes `UpEvent` to delimit a downed segment; WvwExportV1 has no `up` variant. |
| Per-event CC attribution in pre-down windows | `MISSING_EI_EXPORT` | Current down-contribution calculation consumes timestamped, sourced/targeted `CCEvent`; standard EI exposes whole-fight counts/duration only. |
| Whole-fight CC, interrupt, dodge, block and stun-break summaries | `EI_CANONICAL_DIRECT` | Detailed-WvW support/defense aggregates. |
| Ownership intervals and unresolved owner observations | `EI_CANONICAL_DIRECT` | WvwExportV1 intervals are sourced from EI temporal master observations; unresolved observations remain explicitly unresolved. |
| Position samples | `EI_CANONICAL_DIRECT` | WvwExportV1 exposes EI combat-replay positions; product owns subsequent downsampling and heatmap derivation. |
| DPS/HPS, squad/subgroup rollups, strips/cleanses, roles, historical and comparison metrics | `PRODUCT_DERIVED` | Gw2Analytics owns these calculations over canonical EI facts/aggregates. |
| Heatmaps and commander-distance views | `PRODUCT_DERIVED` | Position samples are canonical EI facts; bucketing, selection and presentation are product analytics. |
| Per-fight damage/strip timelines | `PRODUCT_DERIVED` | Can be bucketed from EI event facts; missing timed healing prevents complete current three-series timeline behavior. |
| Actor instance identity across repeated parses | `PRODUCT_CHANGE_REQUIRED` | Seven repeated exports vary only in actor `instance_id`; stable actor reference policy must be resolved before deterministic adapter output. |
| Cast/activation rotation timelines and effect markers | `NOT_CURRENTLY_SHIPPED` | No current production route consumes parser cast/effect events as a timeline; existing internal utility alone is not a shipped consumer. |
| Parsed combat metrics in webhooks | `NOT_CURRENTLY_SHIPPED` | Current webhook path sends upload/subscription notifications, not combat analytics. |
| Private legacy parser-only event families without a current product consumer | `NOT_CURRENTLY_SHIPPED` | Do not add export scope solely to preserve unused parser capability. |

Category counts: `EI_CANONICAL_DIRECT` 9; `EI_CANONICAL_TRANSFORM` 1; `PRODUCT_DERIVED` 3; `MISSING_EI_EXPORT` 3; `PRODUCT_CHANGE_REQUIRED` 2; `NOT_CURRENTLY_SHIPPED` 3. These counts correspond to the 21 classified rows above.

### Deferred event-family reassessment

- **Healing:** required as a timed event family for timeline and per-target event windows; standard EI aggregates do not replace those windows. Next export addition should carry EI’s parsed healing event semantics with source/target, skill and time.
- **Barrier:** whole-fight metrics are already in EI aggregates; no current event-window barrier series is exposed, so do not add a barrier stream until a shipped consumer needs it.
- **Casts/activation timing:** no current production route consumes cast rotation. Keep deferred (`NOT_CURRENTLY_SHIPPED`).
- **CC / breakbar / interrupts:** whole-fight totals are available from EI. Timestamped CC source/target is specifically needed for existing pre-down contribution attribution; add that event family if preserving this product behavior. Breakbar event-level detail is not otherwise a current consumer requirement.
- **Weapon swaps and effects:** no current parsed-event consumer was found; defer as `NOT_CURRENTLY_SHIPPED`.
- **Damage result flags:** standard EI aggregates provide shipped defense/critical summaries. No additional raw flags are needed for current summary views; preserve only if a concrete shipped event-level consumer requires them.

## Legacy-parser comparison and product impact

This slice did not run a full legacy-vs-EI metric comparison. The transport failures above are `EXPORT_GAP` / deterministic transport defects to resolve; they are not evidence that EI’s interpretation is wrong. When comparison is performed, each behavior difference must first verify faithful EI-to-JSON transport, then be classified as expected EI semantic change, product derivation change, export gap, or unknown requiring investigation. Persistence/API/frontend continuity must be assessed for any accepted behavior change.

## Cutover readiness and gates

**`NEEDS_EI_EXPORT_EXTENSION`**. This is not `BLOCKED_BY_UNRESOLVED_SEMANTICS`: the principal current gaps are identifiable. It is not ready for a process adapter prototype because the transport is not yet valid and deterministic on all 35 logs, and timed healing, rally/up, and timed CC facts required by shipped event-window behavior are absent.

Before any production cutover, require:

1. EI export covers every currently shipped parsed-data requirement or a deliberately accepted product change.
2. All 35 logs validate with no out-of-range timestamps/references and repeated byte-identical output, or a documented canonical serialization/identity contract that is deterministic without post-export normalization.
3. Multi-fight archive grouping and stable fight/segment identities are validated.
4. Ownership unresolved/collision semantics and attribution are explicit and tested.
5. Position semantics and replay resource costs meet an agreed operational budget.
6. Migration coverage and behavior-continuity are assessed, including understood canonical EI differences and persistence/API/frontend impact; equality with `gw2_evtc_parser` is not a gate.
7. Product adapter tests pass, historical data remains compatible, and API/frontend behavior has no regression.

## Recommended next slice

Extend WvwExportV1 with the minimum canonical EI facts needed by shipped event-window consumers: timed healing, rally/up lifecycle, and timed source/target CC events. In parallel, investigate the `instance_id` instability and the three buff-removal timestamps at their EI source paths. Keep the changes in the EI fork/export layer; do not reconstruct missing EVTC semantics in Python. Re-run all 35 logs with replay on and off before proposing any process adapter.
