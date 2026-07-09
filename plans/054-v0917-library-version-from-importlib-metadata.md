# Plan 054 — v0.9.17: library `__version__` from `importlib.metadata.version()` + `EVENT_SIZE` cleanup

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`libs/gw2_core/src/gw2_core/__init__.py` (hard-coded `__version__ = "0.5.0"`),
`libs/gw2_analytics/src/gw2_analytics/__init__.py` (hard-coded `__version__ = "0.7.0"`),
`libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py` (hard-coded `__version__ = "0.5.0"` +
`EVENT_SIZE` re-exported in `__all__`).

## Finding (part 1: hard-coded versions)

All 3 `__init__.py` files hard-code `__version__` as a string literal
that drifts from the corresponding `pyproject.toml`'s `version = "..."`
field on every release. Operators running forensic queries
(`gw2_analytics.__version__`) get a stale string instead of the
actually-installed version.

This is the same anti-pattern as plan 053 (which fixes
`Upload.parser_version`'s `"0"` default) but applied to the
libraries' own `__version__` strings. Plan 053 covers the API
package; plan 054 covers the 3 library packages.

## Fix (part 1)

Each `__init__.py` replaces the literal with:

```python
from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("<package-dist-name>")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"  # explicit sentinel, NOT a real version
```

- `gw2_core` package distribution name: `"gw2_core"` (matches
  `libs/gw2_core/pyproject.toml` `[project] name`).
- `gw2_analytics` package distribution name: `"gw2_analytics"`.
- `gw2_evtc_parser` package distribution name: `"gw2_evtc_parser"`.

The `PackageNotFoundError` fallback uses the `"0.0.0+unknown"`
sentinel (PEP 440-compliant dev/release marker) so a
`gw2_analytics.__version__` query in editable-mode CI does NOT
return a value that looks like a real release. This is the
canonical pattern per the Python Packaging User Guide §"install
requirements".

## Finding (part 2: `EVENT_SIZE` leak)

`gw2_evtc_parser/__init__.py` re-exports `EVENT_SIZE` (a parser-
internal constant) in `__all__`. `EVENT_SIZE` is the byte-size of
one EVTC cbtevent struct record (used by `parser.py`'s tight
inner loop). It's not part of the library's public contract;
re-exporting it invites downstream code to import
`from gw2_evtc_parser import EVENT_SIZE` and break when the
parser is re-implemented in Rust (the Rust binding may use a
struct descriptor instead of a constant).

## Fix (part 2)

Drop `EVENT_SIZE` from the `from gw2_evtc_parser.parser import (...)`
line + from `__all__`. The constant stays accessible to the parser
internals via the fully-qualified `from gw2_evtc_parser.parser
import EVENT_SIZE` path (the canonical "internal" import).

## Risks

- `importlib.metadata.version()` is the canonical Python 3.8+
  pattern. The `PackageNotFoundError` fallback covers editable
  installs. The `__version__` semantic is preserved: it's still a
  string that downstream consumers can compare / log.
- An integrator who imported `from gw2_evtc_parser import EVENT_SIZE`
  will see `ImportError` after the plan ships. Mitigation: search
  the codebase for this import; the only call sites are internal
  (`parser.py` itself + the v0.9.6 plan 020's zip-bomb protection
  test which already imports via the fully-qualified path). The
  `__init__.py` `__all__` is the canonical re-export surface;
  dropping a name from `__all__` is the API contract.
- The 3 `__version__` strings change at runtime (from `"0.5.0"` /
  `"0.7.0"` to the actually-installed version). A test that
  asserted the literal string `"0.5.0"` will need to be updated
  to assert the package is installed + the helper returns a
  PEP 440-compliant string.

## Tests

1. `test_gw2_core_version_is_from_metadata` — import
   `gw2_core.__version__`; assert it equals
   `importlib.metadata.version("gw2_core")`.
2. `test_gw2_analytics_version_is_from_metadata` — same for
   `gw2_analytics`.
3. `test_gw2_evtc_parser_version_is_from_metadata` — same for
   `gw2_evtc_parser`.
4. `test_version_fallback_on_missing_package` — monkeypatch
   `importlib.metadata.version` to raise
   `PackageNotFoundError`; assert `__version__ == "0.0.0+unknown"`.
5. `test_event_size_not_in_dunder_all` — assert
   `"EVENT_SIZE" not in gw2_evtc_parser.__all__`.
6. `test_event_size_still_importable_via_qualified_path` —
   assert `from gw2_evtc_parser.parser import EVENT_SIZE`
   still works (the parser internals still have access).
7. `test_event_size_not_in_namespace` — assert
   `hasattr(gw2_evtc_parser, "EVENT_SIZE")` is False (the
   `__all__` no longer re-exports it AND the
   `from ... import ...` line in `__init__.py` no longer
   pulls it into the module's namespace).

## Rejected alternatives

- **Drop `__version__` entirely from the 3 packages**: the
  library consumers (apps/api in `services.py`, future external
  integrators) use `__version__` for forensic logging. PEP 396
  is informational, not mandatory, but the pattern is canonical
  in the Python ecosystem.
- **Read the version from `pyproject.toml` at import time via
  `tomllib`**: requires `pyproject.toml` to be in the import
  path (it isn't at runtime) + adds a `tomllib` dep (Python 3.11+).
  `importlib.metadata` is the canonical, no-dep pattern.
- **Bundle the version into a single `_version.py` file**: a
  PEP 440-compliant single-source-of-truth pattern but requires
  the build system (`hatch` / `setuptools-scm`) to write the
  file at build time. The current `pyproject.toml` is plain
  static-version (no `dynamic = ["version"]`); the
  `importlib.metadata.version()` approach is the v0.9.17 minimum.
- **Keep `EVENT_SIZE` in `__all__` with a `# public-API` docstring**:
  the constant is genuinely internal; documenting it as public
  doesn't change the implementation coupling. The plan drops it
  from the re-export.
- **Add `EVENT_SIZE` to a new `gw2_evtc_parser._internals` submodule**:
  the parser already has full access via the qualified import.
  Adding a new submodule is over-engineering for a 1-line cleanup.
