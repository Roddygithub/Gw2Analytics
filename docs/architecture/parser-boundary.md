# Parser boundary

Product **runtime** code depends on one adapter, not on any concrete parser. That
claim is enforced, not asserted — see "Enforcement" below.

```
.zevtc upload
  -> services.parser_adapter.parse_archive(raw) -> (evtc_bytes, fight iterator)
  -> services.event_blob / services.parse
  -> persistence / analytics / API / frontend
```

## Contract

`gw2analytics_api.services.parser_adapter` is the only product runtime module
allowed to import a parser implementation. It owns:

- the concrete parser implementation (today `gw2_evtc_parser`, later the Elite
  Insights process boundary);
- `.zevtc` archive unpacking;
- the parser error type exposed to product code (`EvtcParseError`);
- the parser provenance recorded on `Upload.parser_version`.

Product services, workers, routes and repositories must not import
`gw2_evtc_parser` directly, and must not import domain concepts *from* it.

## Enforcement

`tests/scripts/test_parser_boundary.py` walks every product source root
(`apps/api/src`, `libs/gw2_core/src`, `libs/gw2_analytics/src`,
`libs/gw2_api_client/src`) and parses each module with `ast`, so docstring and
comment references to the parser — of which the codebase legitimately has many —
do not read as imports. It fails if any module outside the adapter imports
`gw2_evtc_parser` or any submodule.

`apps/api/tests/test_parser_adapter.py` additionally checks that nothing under
`apps/api/src` constructs the concrete parser directly.

The permitted-import list is `CONCRETE_PARSER_ALLOWLIST` in that test, and it may
only shrink. Two tests keep it honest: a stale entry (a file that no longer
imports the parser, or no longer exists) fails, and the end state is an empty
set once the EI boundary lands.

## Domain ownership

`gw2_core` owns the product's domain vocabulary, including the types a parser
produces. `OwnershipInterval` used to live in `gw2_evtc_parser` while
`libs/gw2_analytics/temporal_identity.py` and `ei_compare.py` imported it — a
product analytics package reaching into a parser package for a domain concept.
It now lives in `gw2_core.models`; the parser re-exports it so existing import
sites keep working. `test_parser_boundary.py` asserts the two are the *same
object* (a re-export, not a duplicate) and that no product module names the
parser as the source of the type.

## Migration to Elite Insights

The intended end state is:

```
.zevtc
  -> maintained WvW-focused Elite Insights fork (pinned CLI + config)
  -> EI detailed-WvW JSON
  -> this adapter (schema/version validation, enum/unit mapping, actor slices,
     awareness windows, ownership attribution, error mapping)
  -> narrow normalized product DTOs
  -> persistence / analytics / API / frontend
```

When that lands, only `parser_adapter.py` changes: `parse_archive` becomes an EI
process invocation and `parse_events` returns the normalized product event
contract. No product service, route, schema or frontend file should need to
change.

The adapter must refuse unsupported EI schema/version combinations loudly rather
than guessing, and must record upstream/fork/commit/config identity in the
provenance.

## Current event contract — transitional, not final

The adapter still exposes the old-parser-shaped surface:

```python
parse_archive(raw_bytes) -> (evtc_bytes, fight iterator)
parse_events(evtc_bytes) -> Iterator[Event]
```

That was a deliberate transition step and is **not** the final boundary. The
product-owned result shape the EI boundary should expose is shaped by product
needs rather than by either parser's internals:

```python
parse_upload(raw_upload) -> ParserResult(
    fights,                     # product fight identity
    actors,                     # accounts / characters / specs / subgroup / team
    normalized_events,          # or explicit per-consumer projections
    warnings,
    provenance,                 # EI version, fork commit, config identity
    source_schema_version,
)
```

Raw EI JSON must not be exposed throughout the product.

## What the EI field-coverage gate says about this

The gate has been executed (`docs/validation/ei-field-coverage-gate.md`).
62 of 82 product fields are serviceable from the pinned EI detailed-WvW export.
The remaining rows — above all the **generic raw event stream**, the time-ranged
`OwnershipInterval`, agent positions/replay, and per-target buff removal —
require an EI export change or a product redesign.

**Consequence:** there is nothing for an EI process adapter to normalize the
event stream *from* yet, and `parse_events` has no source to stand on. That is
why the candidate contains no runtime EI adapter and why the custom parser is
still installed behind the adapter. Writing the adapter now would produce dead
code with no consumer on either side.

The gate itself is a real, executed integration with EI — it reads the exports
produced by the pinned CLI over the real 35-log corpus. What is missing is the
runtime path, and it is blocked on the export change, not on this repository.

## Not yet done

- The custom parser is still present; the EI process boundary is not implemented.
- Provenance still records only the home-grown parser version.
- `parse_archive` / `parse_events` still carry the old parser's shape.
- How EI is packaged for local dev, CI, Docker and the Arq worker is undecided.
  `.tooling/` is a developer-local cache and must not become a production
  dependency.
