"""v0.10.2 hotfix regression: NUMERIC(20,0) holds arcdps uint64 agent IDs.

Pre-v0.10.2, the v0.5 baseline declared ``fight_agents.agent_id`` as
``BIGINT`` (Postgres signed 64-bit, max ``2^63 - 1`` = 9.2e18).
arcdps emits ``agent_id`` as uint64 (range ``0 .. 2^64 - 1`` = 1.8e19).
WvW logs routinely contain agents (turrets, siege engines, players)
with ``agent_id >= 2^63`` which overflow ``BIGINT`` and raise
``psycopg.errors.NumericValueOutOfRange: bigint out of range`` on
the INSERT into ``fight_agents``.

Post-v0.10.2, ``fight_agents.agent_id`` is ``NUMERIC(20, 0)`` which
holds the full uint64 range in 20 digits. The matching alembic is
``0010_agent_id_numeric``; the matching ``OrmFightAgent.agent_id``
mapping uses ``Numeric(20, 0)``.
"""

from __future__ import annotations

import time
import uuid as _uuid
from datetime import UTC, datetime

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient
from sqlalchemy import Numeric as SANumeric
from sqlalchemy import cast

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import OrmFight, OrmFightAgent, Upload

# 2^64 - 1 = 18,446,744,073,709,551,615 (max uint64). Picked as the
# boundary value because it is the LEAST likely to be representable
# in any signed-integer column (signed 64-bit BIGINT can hold at
# most 2^63 - 1, so 2^64 - 1 is exactly 1 beyond the overflow
# boundary). If NUMERIC(20, 0) holds this, it holds the entire
# uint64 range.
MAX_UINT64: int = 2**64 - 1

client: TestClient = TestClient(app)


def test_max_uint64_agent_id_persists_without_overflow() -> None:
    """A 1-agent zevtc with ``agent_id = 2^64 - 1`` parses and persists cleanly.

    Pre-v0.10.2: the INSERT into ``fight_agents`` raises
    ``psycopg.errors.NumericValueOutOfRange: bigint out of range``
    because ``2^64 - 1 > 2^63 - 1``. The error propagates through
    ``process_parse``; the upload row's status flips to "failed";
    the test fails at the status == "completed" assertion.

    Post-v0.10.2: ``fight_agents.agent_id`` is ``NUMERIC(20, 0)``
    which holds ``2^64 - 1`` in 20 digits. The INSERT succeeds;
    the row is queryable; the ``agent_id`` round-trips through
    the DB as a ``Decimal`` and re-evaluates to the original
    integer via ``int()``.

    Implementation note: the SELECT WHERE clause uses
    ``OrmFightAgent.agent_id == cast(MAX_UINT64, SANumeric)``
    because psycopg2's default Python-int bind cast is
    ``::BIGINT`` (which overflows for MAX_UINT64). Casting the
    bind parameter to ``NUMERIC`` explicitly bypasses the
    ``::BIGINT`` cast and routes the comparison through the
    NUMERIC type family, which handles the full uint64 range.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    blob = make_minimal_zevtc(
        agents=[(MAX_UINT64, 2, 18, f"V102 Warrior {suffix}", True)],
        build=build,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("overflow.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    else:
        pytest.fail(
            f"upload {upload_id} did not reach 'completed' within 5s "
            f"(pre-v0.10.2 would surface as 'failed' with NumericValueOutOfRange)"
        )
    final_status = upload_resp.json()["status"]
    assert final_status == "completed", (
        f"expected 'completed', got {final_status!r}; "
        f"error_message: {upload_resp.json().get('error_message')!r}"
    )

    with get_sessionmaker()() as db:
        agents = (
            db.query(OrmFightAgent)
            .filter(OrmFightAgent.agent_id == cast(MAX_UINT64, SANumeric))
            .all()
        )
        assert len(agents) == 1, (
            f"expected exactly 1 fight_agent with agent_id = 2^64 - 1, "
            f"got {len(agents)}"
        )
        assert int(agents[0].agent_id) == MAX_UINT64
        assert agents[0].name == f"V102 Warrior {suffix}"
        assert agents[0].profession == 2
        assert agents[0].elite_spec == 18
        assert agents[0].is_player is True


def test_max_uint64_agent_id_inserted_via_orm_directly() -> None:
    """Direct ``session.add(OrmFightAgent(..., agent_id=2**64-1, ...))`` commits cleanly.

    Isolates the column-type invariant from the parser + Arq +
    route-handler machinery. Pre-v0.10.2 the INSERT raises
    ``NumericValueOutOfRange`` at the SQLAlchemy flush;
    post-v0.10.2 the commit succeeds.

    Creates a real ``Upload`` row first (the FK target for
    ``OrmFight.upload_id``) so the direct INSERT path is
    exercised end-to-end without the route handler. The
    upload row is unique per test run via the uuid suffix
    in ``sha256`` (the unique index column).
    """
    suffix = _uuid.uuid4().hex[:8]

    with get_sessionmaker()() as db:
        upload = Upload(
            id=_uuid.uuid4(),
            sha256=f"v102-direct-{suffix}-placeholder-sha256-value",
            original_filename="test.zevtc",
            size_bytes=0,
            status="completed",
            parser_version="v0.10.2",
        )
        db.add(upload)
        db.flush()

        fight = OrmFight(
            id=f"v102-test-{suffix}",
            upload_id=upload.id,
            build_version="20250101",
            encounter_id=0,
            agent_count=1,
            started_at=datetime.now(UTC),
            game_type=1,
        )
        db.add(fight)
        db.flush()

        agent = OrmFightAgent(
            fight_id=fight.id,
            agent_id=MAX_UINT64,
            name=f"V102 Direct {suffix}",
            profession=2,
            elite_spec=18,
            is_player=True,
        )
        db.add(agent)
        # The pre-v0.10.2 failure surfaces HERE: flush (or
        # commit) raises ``DataError: bigint out of range``.
        # Post-v0.10.2: the commit succeeds.
        db.commit()

        roundtripped = (
            db.query(OrmFightAgent)
            .filter(OrmFightAgent.fight_id == fight.id)
            .one()
        )
        assert int(roundtripped.agent_id) == MAX_UINT64
        assert roundtripped.name == f"V102 Direct {suffix}"
