#!/usr/bin/env python3
"""Report backend response fields the web app never receives or never reads.

Two independent checks:

1. **Client drift.** ``web/src/lib/api/*.ts`` carries hand-written interfaces
   that shadow the generated ``schema.d.ts``. They are maintained by hand, so
   they drift: a field the backend added is invisible to every page until
   someone remembers to copy it across, and TypeScript reports the *page* as
   wrong rather than the type. This compares each hand-written interface
   against the schema component of the same name.

2. **Unused fields.** For fields that do reach the client, grep ``web/src`` for
   the name. A field that appears nowhere is produced and dropped.

Both are name-based and err toward under-reporting: treat a hit as "probably
wired" and a miss as "definitely not wired".
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = ROOT / "web" / "src"
API_DIR = WEB_SRC / "lib" / "api"

IGNORED = {
    "detail",
    "loc",
    "msg",
    "type",
    "ctx",
    "url",
    "input",
    "limit",
    "offset",
    "total",
    "page",
    "size",
    "items",
}

#: Hand-written interface -> the OpenAPI component it mirrors.
MIRRORED = {
    "PlayerProfile": "PlayerProfileOut",
    "PlayerTimelinePoint": "PlayerTimelinePointOut",
    "PerFightBreakdownRow": "PerFightBreakdownRowOut",
}


def openapi_spec() -> dict:
    out = subprocess.run(
        ["uv", "run", "python", "web/scripts/dump_openapi.py"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def leaf_fields(schema: dict, spec: dict, seen: set[str] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    fields: set[str] = set()
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            return fields
        seen.add(name)
        return leaf_fields(spec["components"]["schemas"].get(name, {}), spec, seen)
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, []):
            fields |= leaf_fields(sub, spec, seen)
    if schema.get("type") == "array":
        fields |= leaf_fields(schema.get("items", {}), spec, seen)
    for prop, sub in (schema.get("properties") or {}).items():
        fields.add(prop)
        fields |= leaf_fields(sub, spec, seen)
    return fields


def _mapped_type_fields(source: str) -> dict[str, set[str]]:
    """Expand mapped-type helpers over a string union into real field names.

    The client declares the 28 boon columns as two mapped types over a union
    rather than 28 literal properties, so a body-only scan would report every
    one of them as missing.
    """
    union_re = re.compile(r"export type (\w+) =\s*((?:\s*\|\s*'[^']+')+)".replace("'", '"'))
    unions = {name: set(re.findall(r'"(\w+)"', body)) for name, body in union_re.findall(source)}
    mapped_re = re.compile(r"export type (\w+) = \{\s*\[K in (\w+) as `([^`]+)`\]")
    return {
        name: {template.replace("${K}", member) for member in unions.get(union, set())}
        for name, union, template in mapped_re.findall(source)
    }


def handwritten_interfaces() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    pattern = re.compile(r"export interface (\w+)([^{]*)\{(.*?)\n\}", re.S)
    for path in API_DIR.glob("*.ts"):
        source = path.read_text()
        mapped = _mapped_type_fields(source)
        for name, heritage, body in pattern.findall(source):
            fields = set(re.findall(r"^\s*(\w+)\??\s*:", body, re.M))
            for parent in re.findall(r"\w+", heritage.replace("extends", " ")):
                fields |= mapped.get(parent, set())
            out[name] = fields
    return out


def main() -> int:
    spec = openapi_spec()
    components = spec.get("components", {}).get("schemas", {})
    drifted = 0

    print("=== 1. hand-written client interfaces vs the OpenAPI schema ===")
    interfaces = handwritten_interfaces()
    for ts_name, component in sorted(MIRRORED.items()):
        declared = interfaces.get(ts_name)
        if declared is None or component not in components:
            print(f"  {ts_name}: SKIPPED (interface or component {component} not found)")
            continue
        expected = {f for f in (components[component].get("properties") or {}) if f not in IGNORED}
        missing = sorted(expected - declared)
        if missing:
            drifted += len(missing)
            print(f"  {ts_name} is missing {len(missing)}: {', '.join(missing)}")
        else:
            print(f"  {ts_name}: in sync")

    print()
    print("=== 2. response fields never referenced anywhere in web/src ===")
    web_text = "\n".join(
        p.read_text(errors="ignore")
        for p in WEB_SRC.rglob("*")
        if p.suffix in {".ts", ".tsx"} and "schema.d.ts" not in p.name
    )
    by_route: dict[str, set[str]] = defaultdict(set)
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for code, resp in (op.get("responses") or {}).items():
                if not code.startswith("2"):
                    continue
                schema = (resp.get("content") or {}).get("application/json", {}).get("schema")
                if schema:
                    by_route[f"{method.upper()} {path}"] |= leaf_fields(schema, spec)

    unused_total: set[str] = set()
    for route in sorted(by_route):
        fields = {f for f in by_route[route] if f not in IGNORED}
        unused = sorted(f for f in fields if not re.search(rf"\b{re.escape(f)}\b", web_text))
        if unused:
            unused_total |= set(unused)
            print(f"  {route}\n      {', '.join(unused)}")

    print()
    print(f"drifted client fields: {drifted}")
    print(f"distinct unused response fields: {len(unused_total)}")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
