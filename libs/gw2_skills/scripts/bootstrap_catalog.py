#!/usr/bin/env python3
"""Bootstrap the GW2 skills catalog from the official v2 API.

One-shot script that fetches all player-usable skills from
``api.guildwars2.com/v2/skills`` and writes them as NDJSON to
``libs/gw2_skills/src/gw2_skills/data/gw2_skills.ndjson``.

Usage::

    uv run python libs/gw2_skills/scripts/bootstrap_catalog.py

No API key required — the ``/v2/skills`` endpoint is public (no auth).
Rate-limit safety: 300ms delay between batch requests (~15 requests
for 3000 skills in batches of 200, ~5s total wall-clock).

The script maps API fields to :class:`gw2_skills.SkillEntry` Pydantic
shape and writes one JSON object per line (NDJSON format). The output
file is written atomically (write to temp + rename) so a concurrent
``SkillCatalog.load()`` never sees a half-written file.

Design rationale (synchronous script, NOT async):
- This is a one-shot bootstrap tool, not a production service.
  ``httpx.Client`` is simpler + the ~15 requests complete in <5s.
- The ``gw2_api_client.AsyncGuildWars2Client`` requires an API key
  and asyncio — unnecessary overhead for this use case.
- The script is self-contained: only depends on ``httpx`` (already
  in the workspace via ``gw2_api_client``) + the ``gw2_skills``
  library itself.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover — dev-only script
    print("httpx is required. Install with: uv pip install httpx", file=sys.stderr)
    raise SystemExit(1) from exc

# ---------------------------------------------------------------------------
# Resolve the data directory relative to this script's location.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PACKAGE_DATA_DIR = _SCRIPTS_DIR.parent / "src" / "gw2_skills" / "data"
_OUTPUT_FILE = _PACKAGE_DATA_DIR / "gw2_skills.ndjson"

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------
_BASE_URL = "https://api.guildwars2.com/v2"
_BATCH_SIZE = 200  # max per request per ArenaNet recommendation
_RATE_LIMIT_DELAY_S = 0.3  # ~200 req/min, well under the 300/min safe limit
_REQUEST_TIMEOUT_S = 30.0
_USER_AGENT = (    "Gw2Analytics/0.10 skills-catalog-bootstrap "
    "(https://github.com/Roddygithub/Gw2Analytics)"
)

# ---------------------------------------------------------------------------
# Profession mapping: API profession name → gw2_core.Profession enum value.
# The SkillEntry._accept_profession_aliases validator accepts both the
# uppercase enum member name AND the integer value, so we store integers.
# ---------------------------------------------------------------------------
_PROFESSION_MAP: dict[str, int] = {
    "Guardian": 1,
    "Warrior": 2,
    "Engineer": 3,
    "Ranger": 4,
    "Thief": 5,
    "Elementalist": 6,
    "Mesmer": 7,
    "Necromancer": 8,
    "Revenant": 9,
}


def _map_skill_type(api_type: str | None, slot: str | None) -> str:
    """Map the API ``type`` + ``slot`` to our ``SkillType`` literal."""
    # Use a dispatch table to keep return-count below ruff's PLR0911 threshold.
    _type_map: dict[str | None, str] = {
        "Weapon": "weapon",
        "Heal": "heal",
        "Elite": "elite",
        "Utility": "utility",
    }
    if api_type in _type_map:
        return _type_map[api_type]
    if slot and "Downed" in slot:
        return "downed"
    return "utility"  # profession mechanics / bundle / fallback


def _resolve_profession(professions: list[str] | None) -> int | None:
    """Return the primary profession int, or None for multi-profession skills."""
    if not professions:
        return None
    # If the skill belongs to exactly one profession, use it.
    mapped = [_PROFESSION_MAP.get(p) for p in professions if p in _PROFESSION_MAP]
    if len(mapped) == 1:
        return mapped[0]
    return None  # multi-profession or unknown → None


def _api_skill_to_entry(skill: dict[str, Any]) -> dict[str, Any]:
    """Transform one API skill object to a ``SkillEntry``-compatible dict."""
    professions: list[str] | None = skill.get("professions")
    return {
        "id": skill["id"],
        "name": skill["name"],
        "profession": _resolve_profession(professions),
        "is_elite": skill.get("type") == "Elite",
        "skill_type": _map_skill_type(
            skill.get("type"), skill.get("slot")
        ),
        "icon_url": skill.get("icon"),
        "description": skill.get("description"),
    }


def _fetch_all_skill_ids(client: httpx.Client) -> list[int]:
    """Fetch the full list of skill IDs from ``/v2/skills``."""
    print("Fetching skill ID list from /v2/skills ...", end=" ", flush=True)
    resp = client.get("/skills")
    resp.raise_for_status()
    ids: list[int] = resp.json()
    print(f"{len(ids)} IDs retrieved.")
    return ids


def _batch_fetch_skills(
    client: httpx.Client,
    ids: list[int],
) -> list[dict[str, Any]]:
    """Batch-fetch skill objects in groups of ``_BATCH_SIZE``."""
    all_skills: list[dict[str, Any]] = []
    total = len(ids)
    for i in range(0, total, _BATCH_SIZE):
        batch = ids[i : i + _BATCH_SIZE]
        batch_num = i // _BATCH_SIZE + 1
        total_batches = (total + _BATCH_SIZE - 1) // _BATCH_SIZE
        print(
            f"  Batch {batch_num}/{total_batches} "
            f"({len(batch)} skills, IDs {batch[0]}-{batch[-1]}) ...",
            end=" ", flush=True,
        )
        params = {"ids": ",".join(str(sid) for sid in batch)}
        resp = client.get("/skills", params=params)
        resp.raise_for_status()
        data: list[dict[str, Any]] = resp.json()
        all_skills.extend(data)
        print(f"{len(data)} retrieved.")
        if i + _BATCH_SIZE < total:
            time.sleep(_RATE_LIMIT_DELAY_S)
    return all_skills


def main() -> None:
    """Entry point: fetch all skills and write NDJSON."""
    # Ensure the data directory exists.
    _PACKAGE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": _USER_AGENT}
    with httpx.Client(
        base_url=_BASE_URL,
        timeout=_REQUEST_TIMEOUT_S,
        headers=headers,
    ) as client:
        # Step 1: get all skill IDs.
        ids = _fetch_all_skill_ids(client)

        # Step 2: batch-fetch skill details.
        print(        f"Fetching skill details in batches of {_BATCH_SIZE} ...")
        api_skills = _batch_fetch_skills(client, ids)

    # Step 3: transform to SkillEntry-compatible dicts.
    print(f"Transforming {len(api_skills)} skills to SkillEntry format ...")
    entries = [_api_skill_to_entry(s) for s in api_skills]

    # Step 4: validate via SkillEntry.model_validate (catches schema drift).
    # Deferred import so the script can run without gw2_skills installed
    # in a bare uv run context — the library is always available since
    # we're inside the monorepo.
    from gw2_skills.models import SkillEntry  # noqa: PLC0415

    valid_entries: list[dict[str, Any]] = []
    skipped = 0
    for entry_dict in entries:
        try:
            SkillEntry.model_validate(entry_dict)
            valid_entries.append(entry_dict)
        except ValueError as exc:
            skipped += 1
            if skipped <= 10:
                print(f"  SKIP skill {entry_dict.get('id', '?')}: {exc}", file=sys.stderr)

    if skipped > 0:
        print(
            f"  … {skipped} skills skipped (see above).",
            file=sys.stderr,
        )

    # Step 5: write NDJSON atomically.
    print(f"Writing {len(valid_entries)} entries to {_OUTPUT_FILE} ...")
    ndjson_content = "\n".join(json.dumps(e) for e in valid_entries) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=_PACKAGE_DATA_DIR,
        suffix=".ndjson",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(ndjson_content)
        tmp_path = Path(tmp.name)

    # Atomic rename: concurrent SkillCatalog.load() never sees a partial file.
    tmp_path.replace(_OUTPUT_FILE)

    print(f"Done. {len(valid_entries)} skills written to {_OUTPUT_FILE}")
    print("Next: run `uv run pytest libs/gw2_skills/tests/` to verify.")


if __name__ == "__main__":
    main()
