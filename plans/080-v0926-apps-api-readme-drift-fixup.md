# Plan 080 — v0.9.26 — `apps/api/README.md` "Layout" + "Local bring-up" drift fixup

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (LOW DX + correctness):** `apps/api/README.md` "Layout" section is significantly STALE vs the current codebase. The Layout tree, written at v0.7.0, lists 3 alembic migrations, 4 test files, and 3 route modules. The truth as of v0.9.2 + the 25 audit cycles (v0.9.1 → v0.9.25):

| Claim in `apps/api/README.md` | Reality |
|---|---|
| `alembic/versions/` has 3 migrations (`0001_v0_5_baseline.py` + `0002_agent_identity_columns.py` + `0003_fight_skills.py`) | 8 migrations: `0001` through `0008_payload_bytes.py` (plan 029 pre-pending would add `0009_check_constraints.py` if/when shipped) |
| `tests/` has 4 files (`test_healthz.py` + `test_uploads_e2e.py` + `test_account.py` + `test_config.py`) | 10 files (per `apps/api/tests/test_*.py` glob): `test_healthz.py` + `test_health_summary.py` + `test_account.py` + `test_config.py` + `test_backfill.py` + `test_ci_health_gate.py` + `test_webhooks_e2e.py` + `test_webhooks_e2e_scheduler.py` + `test_players.py` + `test_uploads_e2e.py` |
| Source layout ends with `routes/uploads.py` + `routes/fights.py` + `routes/account.py` (3 route modules) | 6 route modules: `routes/uploads.py` + `routes/fights.py` + `routes/account.py` + `routes/health.py` + `routes/players.py` + `routes/webhooks.py` |
| `services.py` exists without comment about its audit-pass provenance | Has been the v0.9.14 deep-pass target; cite plans 045 + 047 explicitly in the README body |

The Layout section drift is benign (a future operator who greps the actual filesystem sees the truth) but confusing (a new contributor trusts the README tree). Plan 074 (v0.9.24 README fix ship a "Release Tags table" + "Phase history" refresh at the PROJECT root level; this plan ships the per-package drift fixup at `apps/api/README.md`).

## File changes

### 1 file edited + 1 NEW test file

**`apps/api/README.md`** — the existing "Layout" section (lines ~50-90 of the file) is rewritten to match the current 8-migration / 10-test-file / 6-route-module reality + the services.py is referenced by its audit pass:

```diff
 app/
 ├── pyproject.toml          # 0.2.0 — depends on gw2_api_client>=0.1.0
 ├── alembic.ini             # script_location = alembic (relative to apps/api)
 ├── alembic/                # Alembic migration scripts + env.py
 │   ├── env.py
 │   └── versions/
-│       ├── 0001_v0_5_baseline.py
-│       ├── 0002_agent_identity_columns.py
-│       └── 0003_fight_skills.py
+│       ├── env.py                            # (covered by plan 061: compare_type=True + workspace source)
+│       └── versions/
+│           ├── 0001_v0_5_baseline.py         # v0.5 schema
+│           ├── 0002_agent_identity_columns.py
+│           ├── 0003_fight_skills.py
+│           ├── 0004_fight_events_blob_uri.py # v0.5.1 events blob storage layer
+│           ├── 0005_fight_player_summaries.py # v0.8.4 fast-path rollup
+│           ├── 0006_webhooks.py              # v0.9.0 webhook subscription table
+│           ├── 0007_webhook_retry.py         # v0.9.1 retry + DLQ
+│           └── 0008_payload_bytes.py         # v0.9.2 webhook LargeBinary payload bytes
+│           # plan 029 (pending): 0009_check_constraints.py — CHECK constraints
+│           # on uploads.status, webhook_deliveries.attempt, status_code, fight_player_summaries magnitudes
 ├── src/gw2analytics_api/
 │   ├── __init__.py         # re-exports __version__ + app
 │   ├── __main__.py         # `python -m gw2analytics_api` entry
 │   ├── main.py             # FastAPI app + middleware + include_router + FastApiMCP
 │   ├── config.py           # env-driven Settings (no hardcoded credentials)
 │   ├── database.py         # SQLAlchemy engine + get_session dependency
 │   ├── storage.py          # MinIO client + put_zevtc helper
-│   ├── services.py         # process_parse background task
+│   ├── services.py         # process_parse background task (plan 045 commit-failure + plan 047 bulk INSERT)
 │   ├── models.py           # ORM models for fights / agents / skills / uploads
 │   ├── schemas.py          # Pydantic v2 response/request schemas
+│   ├── health.py           # /api/v1/health/summary probe (operational drift detection)
+│   ├── backfill.py         # one-shot per-fight summary re-materialisation (v0.8.5)
 │   └── routes/
 │       ├── uploads.py      # POST /api/v1/uploads + GET /api/v1/uploads/{id}
 │       ├── fights.py       # GET /api/v1/fights + GET /api/v1/fights/{id}
-│       └── account.py      # GET /api/v1/account (Bearer-protected)
+│       ├── account.py      # GET /api/v1/account (Bearer-protected)
+│       ├── health.py       # GET /healthz + GET /api/v1/health/summary
+│       ├── players.py      # GET /api/v1/players + GET /api/v1/players/{name}[/timeline]
+│       └── webhooks.py     # POST/GET/DELETE /api/v1/webhooks + POST /api/v1/webhooks/dlq/{id}/replay (plan 079 commit-failure)
 └── tests/
     ├── test_healthz.py
+│   ├── test_health_summary.py
+│   ├── test_backfill.py
     ├── test_uploads_e2e.py # 2 e2e tests (Postgres-required)
     ├── test_account.py     # 11 respx-mocked tests
-│   └── test_config.py      # 9 regression tests for Settings env parser
+│   ├── test_config.py      # 9 regression tests for Settings env parser
+│   ├── test_ci_health_gate.py
+│   ├── test_webhooks_e2e.py
+│   ├── test_webhooks_e2e_scheduler.py
+│   ├── test_players.py
+│   └── conftest.py         # test isolation fixtures (plan 005 conftest + plans 043/044 test cleanup)
```

The "Endpoints" table at the top of the README is similarly patched to add the 4 undocumented endpoints (the original table has 6 rows; reality is 10):

```diff
 | Method | Path                               | Auth                | Purpose                                         |
 |--------|------------------------------------|---------------------|-------------------------------------------------|
 | `GET`  | `/healthz`                         | —                   | Liveness probe                                  |
 | `POST` | `/api/v1/uploads`                  | —                   | Ingest a `.zevtc` blob → enqueue parse          |
 | `GET`  | `/api/v1/uploads/{id}`             | —                   | Inspect an upload row (sha256 + status + fight) |
 | `GET`  | `/api/v1/fights`                   | —                   | Paginated list of parsed fights                 |
 | `GET`  | `/api/v1/fights/{id}`              | —                   | One parsed fight with agents + skills           |
-| `GET`  | `/api/v1/account`                  | `Bearer <GW2_API_KEY>` | Resolve the authenticated account to a `(world_id, world_name, world_population)` triple |
+| `GET`  | `/api/v1/account`                  | `Bearer <GW2_API_KEY>` | Resolve the authenticated account to a `(world_id, world_name, world_population)` triple |
+| `GET`  | `/api/v1/health/summary`           | —                   | Operational drift probe (`drift_count` + `status`) |
+| `GET`  | `/api/v1/players`                  | — (?profession= filter, server-side) | Cross-fight player rollup + profession filter |
+| `GET`  | `/api/v1/players/{name}`           | —                   | Per-account profile + per-fight breakdown |
+| `GET`  | `/api/v1/players/{name}/timeline`  | — (?bucket=day, ?tz=Continent/City) | Per-account fight history (paginated) |
+| `POST` | `/api/v1/webhooks`                 | —                   | Register a webhook subscription (secret returned ONCE) |
+| `GET`  | `/api/v1/webhooks`                 | —                   | List active webhook subscriptions (no secret) |
+| `GET`  | `/api/v1/webhooks/{id}`            | —                   | Inspect a single webhook subscription (no secret) |
+| `DELETE` | `/api/v1/webhooks/{id}`          | —                   | Revoke a webhook subscription (idempotent) |
+| `POST` | `/api/v1/webhooks/dlq/{id}/replay` | —                   | Replay a DLQ delivery (atomic: creates fresh delivery + deletes DLQ row) |
```

### NEW `apps/api/tests/test_readme_drift.py` — 4 hermetic tests

| # | Test | Asserts |
|---|---|---|
| 1 | README's "Layout" tree lists 8 alembic migrations (not 3) | The fixed-line comment block enumerates 8 filenames + the optional `0009_check_constraints.py` |
| 2 | README's "Layout" tree lists 10 test files (not 4) | The fixed-line comment block enumerates the 10 filenames |
| 3 | README's "Layout" tree lists 6 route modules (not 3) | The fixed-line comment block enumerates the 6 routes |
| 4 | README's "Endpoints" table has 14 rows | The patched Endpoints table contains 14 routes (6 original + 8 added in the v0.9.x cycles) |

The tests pattern-match on the markdown text (no DOM / no Python parsing, just substring assertions on the rendered README string).

## Considered and rejected

- **Alternative: delete the Layout section entirely** (the canonical source of truth is `find apps/api -type f`) — assumes every operator runs `find` to discover the layout; the README's tree is the canonical "first impression" for new contributors.
- **Alternative: auto-generate the Layout section via a `scripts/gen_readme_layout.py`** — over-engineered for a 1-time drift fixup; a future maintainer who adds a new file can update the README in the same PR.
- **Alternative: add `plan/080`-derived comments ALONGSIDE the layout** (annotate the tree with the audit plan numbers) — adds noise; the README is the canonical source of "what files exist", not "what audit cycle added them". The audit-pass provenance is in the plans directory.
- **Alternative: rewrite the README from scratch** (`apps/api/README.md` + plan 074 root README both touched in the same cycle) — out of scope (the root README refresh is plan 074 v0.9.24, which already landed).

## Effort

`S` — 1 file edit (the Layout tree + the Endpoints table) + 1 NEW test file (4 substring-based regression tests). All additive (the existing section structure is preserved, only the content is enriched). Backwards-compatible (no external contract). Independent of plans 081 + 082.
