"""Seed a small demo dataset to the LIVE ``/api/v1/uploads`` endpoint.

Why this exists
===============
The v0.8.4 fast-path (:class:`~gw2analytics_api.models.OrmFightPlayerSummary`)
+ the v0.8.5 backfill script close the slow-path latency debt, but a
fresh clone + dev-stack bring-up has an EMPTY database. Visiting
``/fights`` + ``/players`` therefore renders an empty-state panel
that hides the visualisation surface from a first-time analyst --
they have to upload a real arcdps log before they can see what the
charts look like. This CLI seeds a deterministic 3-fight dataset
(structurally canonical but synth-generated) so the dev stack
shows real charts within seconds of ``uvicorn`` + ``pnpm dev``
booting, without requiring the analyst to bring their own
``.zevtc`` to the first session.

Usage
=====
Run AFTER ``docker compose up -d`` + the FastAPI dev server + the
Next.js dev server. The script POSTs each fight + polls the upload
status until the background parser flips ``status`` to
``"completed"`` -- the same pattern :func:`apps.api.tests._fixtures.wait_for_upload_completion`
uses for e2e tests, but against the live :8000 server via ``httpx``.

::

    uv run python -m gw2analytics_api.scripts.seed_demo
    uv run python -m gw2analytics_api.scripts.seed_demo --num-fights 5
    uv run python -m gw2analytics_api.scripts.seed_demo --api-url http://api.example.com

Output
======
The script prints each seeded ``fight_id`` + the canonical URLs
the analyst should visit (``/fights``, ``/players``, each
``/fights/{id}``) so the dev loop is self-documenting from the
terminal output.

Idempotency
===========
Each invocation seeds ``--num-fights`` NEW fights with fresh
uuid suffixes. Re-running doubles the dataset; there is no
UPSERT semantics because the parser-side write-path is
DELETE+INSERT (a re-upload of the same SHA replaces the
existing rows, but different SHAs produce different fights).
De-duplication is intentionally NOT the script's job -- the
operator can drop the rows via the v0.8.5 backfill CLI's
``--fight-id`` flag + ``Clear()`` if they want a clean slate.

Round-trip integrity
====================
The seeded fights use the canonical V1.3 25-byte header + 96-byte
agent records + variable-size skill records + 64-byte cbtevent
records (the struct layouts match ``libs/gw2_evtc_parser/src/
gw2_evtc_parser/parser.py``). The ``Phase 7 v2`` heterogeneous
event streams use the Convention A treatment (``is_nondamage > 0``
+ ``value > 0`` = heal; ``buff_dmg > 0`` = strip) so the seeded
data exercises the SAME surface the e2e test fixtures exercise.

v0.9.0 of the seed script ships the canonical form. Future
cycles can extend the agent pool (add WvW squads, mixed
profession combinations) without changing the CLI surface --
the ``--num-fights`` flag is the only knob.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
import uuid as _uuid
import zipfile
from io import BytesIO

import httpx

# V1.3 EVTC layout (matches ``libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py``):
#   24-byte header (magic + 8B build + rev + combat + unused
#                  + agent_count + map_id)
#   + 4-byte skill_count (at bytes 24-27)
#   + ``agent_count`` x 96-byte agent records
#   + ``skill_count`` x variable-size skill records
#   + ``N`` x 64-byte cbtevent records (Phase 7 v1)
_HEADER_FMT = "<4s8sBHBI I"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 24
_AGENT_RECORD_FMT = "<QIIhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)  # 24
_AGENT_NAME_SIZE = 72
_AGENT_SIZE = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96
_SKILL_HEADER_FMT = "<II"
_SKILL_HEADER_SIZE = struct.calcsize(_SKILL_HEADER_FMT)  # 8
_EVENT_FMT = "<QQQiiIIHHHbbbbbbbbIIbb"
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)  # 64


def make_cbtevent(
    time_ms: int,
    src: int,
    dst: int,
    value: int,
    skill_id: int,
    *,
    is_statechange: int = 0,
    is_nondamage: int = 0,
    buff_dmg: int = 0,
) -> bytes:
    """Pack one 64-byte cbtevent record matching the parser's struct layout.

    Mirrors :func:`apps.api.tests._fixtures.make_cbtevent` byte-for-byte;
    inlined here so the seed script does not have a cross-package
    import on the test fixtures module.
    """
    return struct.pack(
        _EVENT_FMT,
        time_ms,  # uint64 time
        src,  # uint64 src_agent
        dst,  # uint64 dst_agent
        value,  # int32 value
        buff_dmg,  # int32 buff_dmg
        0,  # uint32 overstack_value
        skill_id,  # uint32 skillid
        0,  # uint16 src_instid
        0,  # uint16 dst_instid
        0,  # uint16 translocated
        0,  # uint8 is_cleanup
        is_nondamage,  # uint8 is_nondamage
        is_statechange,  # uint8 is_statechange
        0,  # uint8 is_flanking
        0,  # uint8 is_shields
        0,  # uint8 is_offcycle
        0,  # uint8 pad61
        0,  # uint8 pad62
        0,  # uint32 pad63
        0,  # uint32 pad64
        0,  # uint8 pad65
        0,  # uint8 pad66
    )[:_EVENT_SIZE]


def make_minimal_zevtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str,
    skills: list[tuple[int, str]] | None = None,
    events: list[bytes] | None = None,
) -> bytes:
    """Build a synthetic ``.zevtc`` blob (zip wrapper around EVTC).

    Inlined from :func:`apps.api.tests._fixtures.make_minimal_zevtc` (a
    privacy-of-API stance: the test fixtures module is for tests
    only; the seed script imports its own copy so test+seed paths
    do not couple).

    Player agents carry the combo string ``name\\0:demo.<id>\\0`` (the
    ``:demo.`` prefix mirrors the test fixture's ``:synth.`` prefix
    but the tag distinguishes seeded data from uploaded data on a
    debugging walkthrough). NPCs carry a single null-terminated
    name null-padded to 72 bytes.
    """
    if skills is None:
        skills = []
    if events is None:
        events = []
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        header = struct.pack(
            _HEADER_FMT,
            b"EVTC",
            build.encode("ascii"),
            0,
            0,
            0,
            len(agents),
            0,  # map_id
        )
        if len(header) != _HEADER_SIZE:
            msg = f"header size {len(header)} != {_HEADER_SIZE}"
            raise RuntimeError(msg)
        body = bytearray()
        for aid, prof, elite, name, is_player in agents:
            prefix = struct.pack(
                _AGENT_RECORD_FMT,
                aid,
                prof,
                elite,
                0,
                0,
                0,
                0,
            )
            if len(prefix) != _AGENT_PREFIX_SIZE:
                msg = f"agent prefix size {len(prefix)} != {_AGENT_PREFIX_SIZE}"
                raise RuntimeError(msg)
            if is_player:
                raw = name.encode() + b"\x00" + f":demo.{aid}".encode() + b"\x00\x00"
            else:
                raw = name.encode() + b"\x00"
            if len(raw) > _AGENT_NAME_SIZE:
                msg = f"agent name region {len(raw)} > {_AGENT_NAME_SIZE}"
                raise ValueError(msg)
            name_buf = raw + b"\x00" * (_AGENT_NAME_SIZE - len(raw))
            if len(name_buf) != _AGENT_NAME_SIZE:
                msg = f"agent name buf size {len(name_buf)} != {_AGENT_NAME_SIZE}"
                raise RuntimeError(msg)
            body += prefix + name_buf
        for skill_id, skill_name in skills:
            name_bytes = skill_name.encode("utf-8")
            skill_record = (
                struct.pack(_SKILL_HEADER_FMT, skill_id, len(name_bytes)) + name_bytes + b"\x00"
            )
            body += skill_record
        for ev in events:
            body += ev
        zf.writestr("fight.evtc", header + bytes(body))
    return buf.getvalue()


def _post_and_wait(
    client: httpx.Client,
    blob: bytes,
) -> str:
    """POST a ``.zevtc`` blob and poll until the parser completes; return fight_id."""
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("demo.zevtc", blob, "application/octet-stream")},
    )
    resp.raise_for_status()
    upload_id = resp.json()["id"]
    for _ in range(50):
        r = client.get(f"/api/v1/uploads/{upload_id}")
        r.raise_for_status()
        if r.json()["status"] == "completed":
            # Same post-completion sleep as
            # :func:`apps.api.tests._fixtures.wait_for_upload_completion`
            # -- the BackgroundTasks runner fires after the POST
            # response, so a tight loop races the task startup.
            time.sleep(0.1)
            return str(r.json()["fight_id"])
        time.sleep(0.1)
    msg = f"upload {upload_id} never reached 'completed' status"
    raise RuntimeError(msg)


def _seed_one_fight(
    client: httpx.Client,
    suffix: str,
    *,
    fight_index: int,
) -> str:
    """Build + POST + wait for one demo fight; return its ``fight_id``."""
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    # The magnitudes scale linearly with ``fight_index`` so a
    # multi-fight seed produces a non-monotonic per-fight timeline
    # (a useful visual property when the seed populates the
    # player timeline -- the analysts sees a TREND, not a flat
    # line). The +100 damage and +70 healing steps give a
    # visible trajectory without requiring the analyst to
    # scroll-tool the numbers.
    damage_a = 1_234 + fight_index * 100
    damage_b = 567 + fight_index * 50
    healing_a = 800 + fight_index * 70
    strip_a = 200 + fight_index * 25
    events = [
        # 2 damage events A -> B (occupy different 1-second buckets
        # so the per-bucket event windows shape is non-trivial).
        make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=damage_a,
            skill_id=base_skill_a,
        ),
        make_cbtevent(
            time_ms=2_500,
            src=base_id_a,
            dst=base_id_b,
            value=damage_b,
            skill_id=base_skill_b,
        ),
        # 1 heal event B -> A (Convention A: is_nondamage > 0).
        make_cbtevent(
            time_ms=1_500,
            src=base_id_b,
            dst=base_id_a,
            value=healing_a,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
        # 1 strip event B -> A (Phase 8 pure-strip path: value=0,
        # buff_dmg>0, is_nondamage>0). Exercises the same-record
        # dual-emit alternative the e2e fixtures exercise.
        make_cbtevent(
            time_ms=2_000,
            src=base_id_b,
            dst=base_id_a,
            value=0,
            buff_dmg=strip_a,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
    ]
    blob = make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"Demo Warrior {suffix}", True),
            (base_id_b, 1, 27, f"Demo Guard {suffix}", True),
        ],
        build=f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925",
        skills=[
            (base_skill_a, f"Whirlwind {suffix}"),
            (base_skill_b, f"Burning Precision {suffix}"),
        ],
        events=events,
    )
    return _post_and_wait(client, blob)


def main(argv: list[str] | None = None) -> int:
    """Seed ``--num-fights`` demo fights to the LIVE :8000 server."""
    parser = argparse.ArgumentParser(
        prog="seed_demo",
        description=(
            "Seed a deterministic 3-fight demo dataset against the LIVE "
            "/api/v1/uploads endpoint. Idempotent across re-runs (fresh "
            "uuid suffixes produce fresh fight_ids). Run AFTER docker "
            "compose up -d + uvicorn + pnpm dev."
        ),
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://127.0.0.1:8000",
        help=(
            "Base URL of the FastAPI app. Default http://127.0.0.1:8000 "
            "(the local dev stack). Override for staging deployments."
        ),
    )
    parser.add_argument(
        "--num-fights",
        type=int,
        default=3,
        help=(
            "Number of distinct fights to seed. The default 3 is enough "
            "to populate the per-account timeline with a visible TREND "
            "(the magnitudes scale with fight_index so the day-bucketed "
            "timeline shows non-flat data). 5-10 fills a fuller demo."
        ),
    )
    args = parser.parse_args(argv)
    print(f"Seeding {args.num_fights} demo fights to {args.api_url} ...")
    try:
        with httpx.Client(base_url=args.api_url, timeout=30.0) as client:
            fight_ids: list[str] = []
            for n in range(args.num_fights):
                suffix = _uuid.uuid4().hex[:8]
                fight_id = _seed_one_fight(client, suffix, fight_index=n)
                fight_ids.append(fight_id)
                print(f"  fight {n + 1}/{args.num_fights}: id={fight_id} suffix={suffix}")
    except httpx.HTTPError as exc:
        print(f"\nFAIL: HTTP error during seed: {exc}")
        print(
            "Is the dev stack up? `docker compose ps` + `tmux ls` "
            "(both 'fastapi' and 'gw2a-postgres' / 'gw2a-minio' "
            "should be running)."
        )
        return 1
    print("\nSeeding complete. Open these URLs:")
    print("  http://127.0.0.1:3000/fights      (fights list)")
    print("  http://127.0.0.1:3000/players    (players list)")
    print("  http://127.0.0.1:3000/players/:demo.<id>      (a player profile)")
    print("  http://127.0.0.1:3000/fights/<fight_id>      (any fight drilldown)")
    print("\nFights seeded:")
    for fid in fight_ids:
        print(f"  - http://127.0.0.1:3000/fights/{fid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
