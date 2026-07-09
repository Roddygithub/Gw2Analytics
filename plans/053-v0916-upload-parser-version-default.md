# Plan 053 — v0.9.16: `Upload.parser_version` default → package version

## Drift base

`44ea862`. Drift cleanup only — additive, no migration (the existing
`server_default="0"` literal is migrated; new rows use the package
version via SQLAlchemy `default=` callable).

## Surface

`apps/api/src/gw2analytics_api/models.py::Upload.parser_version`.

## Finding

```python
parser_version: Mapped[str] = mapped_column(String(64), default="0", nullable=False)
```

The default is the magic literal `"0"`. A row written by v0.8.6 of
the parser, then later a row written by v0.9.0, both store `"0"`.
The column is supposed to surface which parser wrote the row (for
re-parse decisions + operator forensics) but today every row
displays as `"0"` regardless of which `gw2_evtc_parser` build wrote
it.

## Fix

1. Add `_resolve_parser_version() -> str` to `models.py` (or import
   from a new shared `_version.py` helper, see below). The helper
   uses `importlib.metadata.version("gw2_analytics")` (the library
   that ships the parser, not the API package) to get the canonical
   version. Cached at module level so the `metadata.version` lookup
   runs once per process (avoids a 5-10ms pkg_resources scan per
   upload).
2. Change the column default:

   ```python
   parser_version: Mapped[str] = mapped_column(
       String(64),
       default=_resolve_parser_version,
       nullable=False,
   )
   ```

3. Defensive fallback: if `importlib.metadata.PackageNotFoundError`
   is raised (e.g., the package was installed in editable mode with
   no `dist-info`), fall back to the string literal `"unknown"`. The
   fallback is logged once at WARNING level so the operator notices
   the misconfiguration.

## Why `gw2_analytics` (not `gw2analytics_api`)

The parser lives in `libs/gw2_evtc_parser/` (PyPI name
`gw2-evtc-parser`, distribution name `gw2_analytics` — see the
`pyproject.toml` `name = "gw2_analytics"` field, the API consumes
it as the `gw2_analytics` Python package). The `gw2analytics_api`
package version is the API version (post-plan 042 it's exposed via
`_resolve_app_version()`), which is independent of the parser
version. The column is `parser_version` — it must reflect the
parser.

## Why not the design-doc §3.6 "parser_version = API version"

The design doc spec is wrong on this point (it pre-dates the
`gw2_analytics` library split). Plan 053 is a spec correction. The
CHANGELOG entry under `[Unreleased]` notes the spec deviation.

## Risks

- Existing rows keep their `parser_version="0"` value. The migration
  is additive (no backfill of historical rows). Operators running
  forensic queries will see `parser_version="0"` for historical rows
  and a real version for new rows. Documented in the migration
  notes + the plan's CHANGELOG entry.
- `importlib.metadata.version` requires the package to be installed
  (no source-tree-only deployments). The `PackageNotFoundError`
  fallback covers this.
- The `default=` callable runs at INSERT time, not at table creation
  time. A migration using `server_default="0"` would override the
  application default. Plan 053 keeps the `server_default="0"` for
  raw-SQL inserts (e.g., the alembic baseline backfill) and adds
  the `default=` for ORM writes. Both are correct.

## Tests

1. `test_parser_version_default_is_package_version` — insert one
   `Upload` row via the ORM; assert `parser_version` is the value
   returned by `importlib.metadata.version("gw2_analytics")`.
2. `test_parser_version_fallback_on_missing_package` — monkeypatch
   `importlib.metadata.version` to raise `PackageNotFoundError`;
   assert the column default is `"unknown"` and a WARNING is logged.
3. `test_parser_version_is_cached` — patch
   `importlib.metadata.version` to count calls; insert 2 rows;
   assert the helper was called once (cached).
4. `test_parser_version_existing_rows_unchanged` — insert a row
   with explicit `parser_version="legacy"`; assert the value is
   preserved (the `default=` is a default, not an override).

## Rejected alternatives

- **Hard-code `parser_version="0.9.6"` in the model**: drifts on
  every release; the next release forgets to bump it.
- **Read from `os.environ.get("GW2_ANALYTICS_PARSER_VERSION")`**:
  adds a deployment-time config knob; the version is intrinsic to
  the installed package, not to the deployment.
- **Backfill the historical rows** (UPDATE all `parser_version="0"`
  to the current version): lies about history (the historical
  rows were parsed by older versions; we don't know which).
- **Drop the column** (since we don't have historical data): the
  plan-015 re-parse logic uses `parser_version != current_version`
  as the trigger; dropping it would force a full-table scan for the
  re-parse gate.
