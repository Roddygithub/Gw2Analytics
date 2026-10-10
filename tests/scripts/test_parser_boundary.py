"""Architecture boundary: the product does not import the concrete parser.

``docs/architecture/parser-boundary.md`` claims the product depends on one
adapter rather than on a parser implementation. ``apps/api/tests/
test_parser_adapter.py`` only checks that no module under ``apps/api/src``
*constructs* ``PythonEvtcParser`` -- a string scan of one package. A library
import, a type-only import, or an import in ``libs/`` slipped straight past it.

This test enforces the real rule over every product source root, parsed with
AST so docstring and comment references to the parser (of which the codebase
legitimately has many) do not read as imports.

The allowlist may only shrink. Its end state is empty, once the Elite Insights
process adapter replaces the custom parser.
"""

from __future__ import annotations

import ast
from pathlib import Path

import gw2_core
import gw2_evtc_parser

ROOT = Path(__file__).resolve().parents[2]

#: Every Python source root that ships product runtime code.
PRODUCT_SRC_ROOTS = (
    "apps/api/src",
    "libs/gw2_core/src",
    "libs/gw2_analytics/src",
    "libs/gw2_api_client/src",
)

#: The concrete parser implementation this refoundation replaces.
PARSER_PACKAGE = "gw2_evtc_parser"

#: Production modules still permitted to import the concrete parser. The
#: adapter owns the implementation so it can be swapped for the Elite Insights
#: process without touching product composition. This set must only shrink.
CONCRETE_PARSER_ALLOWLIST = frozenset({"apps/api/src/gw2analytics_api/services/parser_adapter.py"})


def _imported_modules(path: Path) -> set[str]:
    """Return every module named by an ``import``/``from ... import`` statement."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _product_modules() -> list[Path]:
    modules: list[Path] = []
    for root in PRODUCT_SRC_ROOTS:
        base = ROOT / root
        if base.is_dir():
            modules.extend(base.rglob("*.py"))
    return sorted(modules)


def test_no_product_module_imports_the_concrete_parser() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _product_modules():
        relpath = path.relative_to(ROOT).as_posix()
        if relpath in CONCRETE_PARSER_ALLOWLIST:
            continue
        imported = {
            module
            for module in _imported_modules(path)
            if module == PARSER_PACKAGE or module.startswith(f"{PARSER_PACKAGE}.")
        }
        if imported:
            offenders[relpath] = sorted(imported)

    assert offenders == {}, (
        "product code must reach the parser through "
        "gw2analytics_api.services.parser_adapter, not by importing "
        f"{PARSER_PACKAGE!r} directly: {offenders}"
    )


def test_the_parser_allowlist_is_a_shrinking_exception_list() -> None:
    """Only the adapter may be grandfathered, and stale entries must be pruned."""
    for relpath in CONCRETE_PARSER_ALLOWLIST:
        path = ROOT / relpath
        assert path.is_file(), (
            f"{relpath!r} is on the concrete-parser allowlist but does not exist; "
            "delete the stale entry so the exception list keeps shrinking."
        )
        assert any(
            module == PARSER_PACKAGE or module.startswith(f"{PARSER_PACKAGE}.")
            for module in _imported_modules(path)
        ), (
            f"{relpath!r} no longer imports {PARSER_PACKAGE!r}; remove it from "
            "CONCRETE_PARSER_ALLOWLIST so the exception list keeps shrinking."
        )


def test_ownership_interval_is_owned_by_the_product_not_the_parser() -> None:
    """The domain type must live in gw2_core, not be duplicated in the parser."""
    assert gw2_evtc_parser.OwnershipInterval is gw2_core.OwnershipInterval, (
        "gw2_evtc_parser must re-export gw2_core.OwnershipInterval rather than "
        "declare its own copy; the product owns the 'ownership interval' concept."
    )


def test_product_domain_does_not_import_the_parser_for_ownership() -> None:
    """No analytics/core module may name the parser as the source of the type."""
    for path in _product_modules():
        relpath = path.relative_to(ROOT).as_posix()
        if relpath in CONCRETE_PARSER_ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8")
        assert "from gw2_evtc_parser import OwnershipInterval" not in source, (
            f"{relpath} imports OwnershipInterval from the parser; import it from gw2_core."
        )
