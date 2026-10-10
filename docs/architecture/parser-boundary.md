# Parser boundary

The product depends on **one** parser adapter, not on any concrete parser.

```
.zevtc upload
  -> services.parser_adapter.parse_archive(raw) -> (evtc_bytes, fight iterator)
  -> services.parser_event_blob / services.parse
  -> persistence / analytics / API / frontend
```

## Contract

`gw2analytics_api.services.parser_adapter` is the only module allowed to import
the parser implementation. It owns:

- the concrete parser implementation (today `gw2_evtc_parser`, later the Elite
  Insights process boundary);
- `.zevtc` archive unpacking;
- the parser error type exposed to product code (`EvtcParseError`);
- the parser provenance recorded on `Upload.parser_version`.

Product code (services, workers, routes, repositories) must not import
`gw2_evtc_parser` directly. `tests/test_parser_adapter.py` enforces this by
failing if any other module in `apps/api/src` constructs the concrete parser.

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

## Not yet done

- The custom parser is still present; the EI process boundary is not implemented
  yet. See the EI field-coverage gate in the migration baseline before removing
  the old event path.
- Provenance still records only the home-grown parser version.
