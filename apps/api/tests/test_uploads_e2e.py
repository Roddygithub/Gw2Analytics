"""End-to-end POST /uploads test against a real Postgres.

Builds a synthetic ``.zevtc`` in-memory (using :pymod:`struct` to
mimic the arcdps layout), POSTs it through the public API, then
queries GET /uploads and GET /fights to verify the schema is wired
correctly.

Requires a Postgres server reachable at the ``DATABASE_URL`` declared
in ``pyproject.toml`` / ``.env``. Run ``docker compose up -d
gw2a-postgres`` first if your local environment does not already
expose Postgres on port 5432.

The test is **idempotent** by design: each run injects a uuid-derived
suffix into ``agent_id``, ``name``, the build string, and the skill
``id``s so the ``fight_agents (fight_id, agent_id)`` PK, the
``fight_skills (fight_id, skill_id)`` PK and the ``fights.id`` are
unique per invocation. No CASCADE truncate needed.

See ``apps/api/README.md`` for how to bring up the upstream Postgres
dependency locally + in CI.
"""

from __future__ import annotations

import struct
import uuid as _uuid
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from gw2analytics_api.main import app

client = TestClient(app)

# V1.3 EVTC layout (matches libs/gw2_evtc_parser parser.py):
#   25-byte header (magic + 8B build + rev + encounter + unused
#                   + agent_count + skill_count + language)
#   + agent_count x 96-byte agent records
#   + skill_count x variable-size skill records
_HEADER_FMT = "<4s8sBHBI IB"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 25
_AGENT_RECORD_FMT = "<QIIhhhhhh"
_AGENT_PREFIX_SIZE = struct.calcsize(_AGENT_RECORD_FMT)  # 28
_AGENT_NAME_SIZE = 68
_AGENT_SIZE = _AGENT_PREFIX_SIZE + _AGENT_NAME_SIZE  # 96
_SKILL_HEADER_FMT = "<II"
_SKILL_HEADER_SIZE = struct.calcsize(_SKILL_HEADER_FMT)  # 8


def _make_minimal_zevtc(
    agents: list[tuple[int, int, int, str, bool]],
    build: str,
    skills: list[tuple[int, str]] | None = None,
) -> bytes:
    """Build a synthetic .zevtc blob (zip wrapper around EVTC).

    Uses the V1.3 25-byte header + 96-byte agent records + variable
    skill records. For player agents the combo string
    ``name\\0:synth.<id>\\0`` is null-padded to 68 bytes; NPCs get a
    single null-terminated name null-padded to 68 bytes. Skill records
    are ``<II`` (skill_id + name_len) + UTF-8 name + 1 byte null.
    """
    if skills is None:
        skills = []
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
            len(skills),
            0,  # language
        )
        assert len(header) == _HEADER_SIZE
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
                0,
                0,
            )
            assert len(prefix) == _AGENT_PREFIX_SIZE
            if is_player:
                raw = name.encode() + b"\x00" + f":synth.{aid}".encode() + b"\x00\x00"
            else:
                raw = name.encode() + b"\x00"
            if len(raw) > _AGENT_NAME_SIZE:
                msg = f"agent name region {len(raw)} > {_AGENT_NAME_SIZE}"
                raise ValueError(msg)
            name_buf = raw + b"\x00" * (_AGENT_NAME_SIZE - len(raw))
            assert len(name_buf) == _AGENT_NAME_SIZE
            body += prefix + name_buf
        for skill_id, skill_name in skills:
            name_bytes = skill_name.encode("utf-8")
            skill_record = (
                struct.pack(_SKILL_HEADER_FMT, skill_id, len(name_bytes)) + name_bytes + b"\x00"
            )
            body += skill_record
        zf.writestr("fight.evtc", header + bytes(body))
    return buf.getvalue()


def test_uploads_e2e_happy_path() -> None:
    # Per-run uuid suffix keeps fights.id, fight_agents (fight_id,
    # agent_id) and fight_skills (fight_id, skill_id) unique across
    # re-runs, so no CASCADE truncate is required.
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1

    blob = _make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"E2E Warrior {suffix}", True),
            (base_id_b, 1, 27, f"E2E Guard {suffix}", True),
        ],
        build=build,
        skills=[
            (base_skill_a, f"Whirlwind {suffix}"),
            (base_skill_b, f"Burning Precision {suffix}"),
        ],
    )

    # POST a synthetic .zevtc
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert "id" in created
    assert "sha256" in created
    assert created["status"] in {"pending", "completed", "failed"}

    # GET /uploads/{id} returns the persisted row
    upload_resp = client.get(f"/api/v1/uploads/{created['id']}")
    assert upload_resp.status_code == 200
    payload = upload_resp.json()
    assert payload["sha256"] == created["sha256"]
    assert payload["status"] == "completed"
    assert payload["parser_version"]  # non-empty
    assert payload["fight_id"] is not None

    # GET /fights/{id} returns the parsed fight with 2 agents + 2 skills
    fight_resp = client.get(f"/api/v1/fights/{payload['fight_id']}")
    assert fight_resp.status_code == 200
    fight = fight_resp.json()
    assert fight["agent_count"] == 2
    assert len(fight["agents"]) == 2
    names = {a["name"] for a in fight["agents"]}
    assert names == {f"E2E Warrior {suffix}", f"E2E Guard {suffix}"}
    for a in fight["agents"]:
        assert a["is_player"] is True
        assert a["account_name"] is not None
        assert a["account_name"].startswith(":synth.")
        assert a["subgroup"] == ""
    # V1.3: skills round-trip
    assert len(fight["skills"]) == 2
    skill_names = {s["name"] for s in fight["skills"]}
    assert skill_names == {f"Whirlwind {suffix}", f"Burning Precision {suffix}"}
    skill_ids = {s["id"] for s in fight["skills"]}
    assert skill_ids == {base_skill_a, base_skill_b}


def test_healthz_responds() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
