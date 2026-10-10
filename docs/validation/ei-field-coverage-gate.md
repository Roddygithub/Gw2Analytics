# Elite Insights field-coverage gate

**Status: EXECUTED — 2026-10-10. Verdict: the gate does NOT yet permit removing
the custom parser.**

| | |
| --- | --- |
| Generator | `scripts/ei-parity/field_coverage.py` |
| Machine-readable result | `docs/validation/ei-field-coverage.json` |
| Human-readable result | `docs/validation/ei-field-coverage-matrix.md` |
| EI baseline | Elite Insights `3.26.0.0` (see `ei-baseline.md`) |
| Corpus | 35 logs, `scripts/ei-parity/corpus.txt`, SHA-256 manifests in the recovery root |
| EI key paths observed | 70 271 distinct paths |
| Fields classified | 82 |

## Why this gate exists

The product reads typed, raw-ish event JSONL sources for timelines, readout,
positions/heatmaps, damage windows, buff events, rotation and time-aware
identity. EI detailed-WvW JSON is a different shape. Deleting the old event path
before proving each consumer can be fed from EI would silently change product
behaviour.

## How the gate is made trustworthy

`field_coverage.py` is **self-verifying**. Its `MAPPING` table is curated, but
every claimed `ei` path is resolved against the real 35-log corpus before the
matrix is written. A claim about a path the corpus does not contain fails the
gate (exit 1) instead of being published. A run without the private corpus exits
2 (INCOMPLETE) rather than reporting a pass.

Three claims were rejected by that check during development
(`players[].statsTargets[].totalDmg`, `players[].totalDamageDist[].totalDamage`,
`players[].dpsTargets[].damage` — each one array level short), which is the
mechanism working as intended.

The generator also refuses to write if the rendered artifacts contain anything
resembling an account name or an instance IP, so no private identity can leak
into the tracked matrix.

## Result

| status | fields |
| --- | ---: |
| `EXACT` | 50 |
| `TRANSFORMABLE` | 12 |
| `AGGREGATED_BUT_SUFFICIENT` | 7 |
| `AMBIGUOUS` | 3 |
| `MISSING` | 4 |
| `REQUIRES_EI_EXPORT_CHANGE` | 4 |
| `PRODUCT_REDUNDANT` | 2 |

62 of 82 fields (76 %) are directly serviceable from the pinned EI export,
either verbatim or after a documented transformation. Damage, strike/condition
split, healing, barrier, cleanses, strips, CC, downs/deaths, interrupts,
dodges/blocks, awareness windows, subgroup/team, per-target stats and the fight
envelope are all covered.

## What EI cannot supply today

These four rows are why the custom parser cannot be deleted yet:

| product need | why EI cannot serve it |
| --- | --- |
| **raw event stream (generic)** | EI publishes aggregates and per-second series only. Every `gw2_analytics` aggregator consumes a normalized event stream (`gw2_evtc_parser.PythonEvtcParser.parse_events` -> `event_blob`). This single row gates the migration. |
| **`OwnershipInterval` (time-ranged)** | EI nests each minion under its owner (recoverable) but publishes no `[start,end)` ownership interval. `temporal_identity` is time-parameterised. |
| **agent positions / combat replay** | The pinned config runs `ParseCombatReplay=false`, so no position samples are emitted at all. |
| **per-target buff removal** | Needs the raw buff-removal stream. |

Plus `AMBIGUOUS`: the multi-fight archive contract (EI takes one log per
invocation and merges nothing across fights, while an upload may yield N
fights), instant-vs-cast distinctions inside EI's rotation list, and
`players[].minions[].isUniquePerTimeFrame` (a temporal hint with no bounds).

## Deliberate decision required before the old path is deleted

Per the task, each `MISSING` / `AMBIGUOUS` / `REQUIRES_EI_EXPORT_CHANGE` row
needs an explicit decision recorded. The candidate decision is:

1. **Add a narrow WvW export to the EI fork** carrying the normalized event
   stream (or an equivalent per-event projection), the time-ranged ownership
   intervals and position samples. This is the only option that preserves
   product behaviour without rewriting every aggregator.
2. **Enable `ParseCombatReplay=true`** for the position/replay row, after
   budgeting its cost (it dominates export size) and re-certifying.
3. **Accept EI's own buff semantics** only where the product agrees to adopt
   them (`AGGREGATED_BUT_SUFFICIENT` rows). `scripts/ei-parity/corpus-baseline.json`
   already records where the two disagree — e.g. 190 `buffUptimes.uptime`
   deltas — so this is a product decision, not a mechanical one.
4. **Redesign the multi-fight contract** in the adapter rather than in EI; a
   stable product fight identity is the adapter's job.

Until (1) exists there is nothing for an EI process adapter to normalize the
event stream *from*, which is why no runtime EI adapter has been written. See
`docs/architecture/parser-boundary.md`.

## Measured cost (2026-10-10)

Timed with the pinned single-threaded CLI (`SingleThreaded=true`,
`ParseCombatReplay=false`), wall clock per fight, on this host:

| log | `.zevtc` | inner EVTC | EI wall | export |
| --- | ---: | ---: | ---: | ---: |
| `20260128-160105` | 64 KB | 0.30 MB | 1.03 s | 0.37 MB |
| `20260224-233019` | 3.03 MB | 14.82 MB | 3.19 s | 13.02 MB |
| `20260314-234454` | 3.65 MB | 16.50 MB | 3.98 s | 20.21 MB |

Roughly 4 MB of EVTC per second, and the export is consistently ~1.2-1.4x the
uncompressed input. Across the whole 35-log certification set that is 305.7 MB
of JSON (min 0.37 MB, max 29.88 MB, mean 8.73 MB) and on the order of two
minutes of CPU.

Two consequences for the migration design, neither of which is settled yet:

- **Storage, not time, is the cost.** A few megabytes of JSON per fight per
  upload is a real retention question; the export should not be persisted
  verbatim.
- **Enabling `ParseCombatReplay=true` multiplies the export**, which is the
  same flag the positions/replay row requires. Budget it before turning it on.

No memory measurement was taken, and no multi-log throughput run.

## How to re-run the gate

```bash
uv run python scripts/ei-parity/field_coverage.py \
    --corpus "<dir with the 35 .zevtc logs>" \
    --ei-out "<dir with <id>_detailed_wvw_kill.json>" \
    --write
```

Exit codes: `0` gate passed and (with `--write`) artifacts rewritten, `1` a
claimed EI path is not in the corpus, `2` the corpus or an EI export is
incomplete, `3` the privacy guard fired.

## Related

- `docs/architecture/parser-boundary.md` — the adapter the EI boundary will land in.
- `docs/validation/ei-baseline.md` — which EI is pinned, and why.
- `docs/validation/regeneration-decision.md` — the uptime/ownership semantic
  knowledge this gate forces us to treat as implementation-independent.
- `docs/validation/ei-parity-certification/` — SPEC, certification matrix and stories.
