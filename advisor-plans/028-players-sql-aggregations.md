# Plan 028 — v0.10.10: SQL aggregations on `OrmFightPlayerSummary` for `/api/v1/players` + `/api/v1/players/{account_name}` + `/api/v1/players/{account_name}/timeline` (eliminates full-DB RAM load)

**Stamped at:** `f0249ef` (working-tree diff HEAD; all changes in this plan live in the uncommitted working tree)
**Severity:** HIGH (perf + tech-debt — scales linearly with dataset)
**Category:** tech-debt, perf
**Addresses finding:** `apps/api/src/gw2analytics_api/routes/players.py:380`, `routes/players.py:462`, and `routes/players.py:565` (three endpoints: `list_players`, `get_player_timeline`, `get_player`) ALL execute `select(OrmFight).order_by(OrmFight.started_at.desc()).options(selectinload(OrmFight.agents), selectinload(OrmFight.skills)).scalars().all()` — i.e. the **entire** `OrmFight` table with FULL children pre-loaded into RAM before a single Python-side aggregation runs. At 10k WvW fights with a mean of ~50 agents per fight, this loads ~500k ORM objects + the ancestry chains per request. At 100k fights, the route is functionally unusable (multi-second to tens-of-seconds response time + multi-GB RAM per concurrent request). Plan scope (per user selection): **SQL aggregations complètes** — replace the Python loop with native Postgres `GROUP BY` over `OrmFightPlayerSummary`; the `OrmFight` table becomes a metadata-only lookup for `started_at` per fight id.

---

## Finding

Evidence (current working-tree source — three near-identical query blocks):

```python
# apps/api/src/gw2analytics_api/routes/players.py:380-398 (list_players)
fights = (
    db.execute(
        select(OrmFight)
        .order_by(OrmFight.started_at.desc())
        .options(
            selectinload(OrmFight.agents),
            selectinload(OrmFight.skills),
        ),
    )
    .scalars()
    .all()
)
contributions = _compute_contributions(db, fights)
profiles = PlayerProfileAggregator().aggregate(contributions)
```

The same query appears at lines `462` (`get_player_timeline`) and `565` (`get_player`). Three endpoints, three identical full-table scans + Python aggregations.

### Why `OrmFightPlayerSummary` (the v0.8.4 materialised view) makes SQL aggregation possible

Since v0.8.4 (plan 045), every parsed fight has rows in `OrmFightPlayerSummary` with `(fight_id, account_name, name, profession, elite_spec, total_damage, total_healing, total_buff_removal, detected_role, detected_tags, power_damage, condi_damage)`. This is exactly the per-(fight, account) magnitude set that the Python loop currently rebuilds from the events blobs. The materialised view is the canonical source of truth for cross-fight aggregations; the events blobs are an audit-trail artifact, not the primary aggregation surface.

### The target query shape

For `list_players`, the goal is:

```sql
SELECT
    account_name,
    MAX(name)                  AS name,
    MODE(profession)           AS profession,        -- (requires sorted-by-count sub-query)
    MODE(elite_spec)           AS elite_spec,
    COUNT(*)                   AS fights_attended,
    SUM(total_damage)          AS total_damage,
    SUM(total_healing)         AS total_healing,
    SUM(total_buff_removal)    AS total_buff_removal
FROM fight_player_summaries
GROUP BY account_name
ORDER BY total_damage DESC
LIMIT $1 OFFSET $2
```

Translate to SQLAlchemy `select(...).group_by(account_name).limit().offset()` with a Python-side modal profession (Postgres `MODE()` is not a built-in aggregate; the canonical alternative is a window function or a subquery with `ORDER BY COUNT(*) DESC LIMIT 1`).

---

## Fix

### Step 1 — Add a new module `apps/api/src/gw2analytics_api/services/player_profiles.py`

This module owns the **SQL aggregations** behind a single function `_aggregate_player_profiles(db, *, profession_filter=None, limit, offset) -> list[PlayerProfile]`. The function:

1. Builds a SQLAlchemy aggregation query against `OrmFightPlayerSummary`.
2. For modal profession: a subquery that returns the most-common profession per `account_name`. SQL pattern:

   ```sql
   SELECT account_name, profession
   FROM (
     SELECT account_name, profession, COUNT(*) AS cnt,
            ROW_NUMBER() OVER (PARTITION BY account_name ORDER BY COUNT(*) DESC) AS rn
     FROM fight_player_summaries
     GROUP BY account_name, profession
   ) ranked
   WHERE rn = 1
   ```

   Join this back to the totals query via `account_name` as a CTE or LEFT JOIN.
3. Sort by `total_damage DESC` (matches the deterministic-ordering contract of `PlayerProfileAggregator`).
4. Apply `profession` filter via a Python-side post-filter (matches the existing `_parse_profession_filter` flow — the filter is on the modal profession, not the per-fight profession).
5. Apply `limit`/`offset` (matches the existing `?limit=&offset=` contract).

### Step 2 — Replace `_compute_contributions` calls in the 3 endpoints

For each of `list_players`, `get_player`, `get_player_timeline`:

- WHERE `?profession=` is filtered → drop the role-detection / condi-power path entirely (we already have `detected_role` + `detected_tags` from the summary table).
- DELETE the `_contributions_from_blob_walk` fallback for the modal-aggregation path (it remains in the codebase for the BLOB-SLOW-PATH use cases only — see Step 3).
- KEEP the `PlayerProfileAggregator` import and **wrap it** as a wrap layer over the SQL result (rather than replacing it). The aggregator's invariants (frozen Pydantic shape, deterministic ordering, cross-field checks) remain the wire contract. The SQL query is the SOURCE; `PlayerProfileAggregator` is the wire validator.

Concretely in `list_players`:

```python
profiles = _aggregate_player_profiles_from_sql(
    db,
    profession_filter=parsed_profession,
    limit=limit,
    offset=offset,
)
```

The signature change drops the `db.execute(select(OrmFight).all())` call.

### Step 3 — Preserve `_contributions_from_blob_walk` for the fallback path

The Python blob-walk path is correct and necessary for pre-v0.8.4 fights (the materialised view didn't yet exist). Wrap it as a conditional:

```python
def _compute_contributions_via_sql(
    db: Session, *, account_name: str | None = None
) -> list[PlayerProfileRow]:
    """SQL-only path: queries OrmFightPlayerSummary directly.

    This is the canonical v0.10.10+ codepath for `list_players`,
    `get_player`, and `get_player_timeline`. The blob-walk fallback
    is preserved for pre-v0.8.4 fights whose events blobs are
    parsed but whose summary rows are missing (legacy imports,
    re-parses that haven't backfilled yet).
    """
    ...
```

A post-aggregation completeness check verifies the materialised view is reasonably complete (e.g. >95% of fights have summary rows; the missing 5% go through the blob-walk). At 100% coverage, the blob-walk is dormant (only runs in `dry-run` mode for integration tests).

### Step 4 — Update `PlayerProfileAggregator.aggregate`

The aggregator currently takes `Iterable[FightContribution]` and folds it. Refactor to accept the SQL-result shape directly (a new `aggregate_from_summary_rows(rows)` method) OR keep the existing API and build a sync `FightContribution` iterable from the SQL query (transitional pattern). The transitional pattern is preferred — it preserves cross-field invariants without re-querying the events blobs.

---

## Tests

### Test file 1 — NEW `apps/api/tests/test_player_profiles_sql.py`

Pattern reference: `apps/api/tests/test_players.py` (existing v0.7.0 test file; many fixtures + golden-day tests).

8 hermetic + 1 e2e test (Postgres required for the e2e; CI does the heavy lifting):

1. `test_aggregate_player_profiles_returns_deterministic_order` — seed 50 accounts with varying magnitudes; assert SQL result is `total_damage DESC` sorted (matches existing Python aggregator contract).

2. `test_aggregate_player_profiles_with_profession_filter` — seed 50 accounts, 30% MESMER; assert filtered result has 15 accounts (all MESMER modal).

3. `test_aggregate_player_profiles_pagination` — assert `limit=10, offset=0` and `limit=10, offset=10` return distinct pages; both combined reproduce the unpaginated list.

4. `test_aggregate_player_profiles_modal_profession` — seed 1 account with 10 MESMER fights + 5 NECROMANCER fights; assert modal is MESMER (highest count).

5. `test_modal_profession_tiebreaker` — seed 1 account with 5 MESMER + 5 NECROMANCER fights; assert modal falls back to a deterministic tiebreaker (the SQL `ORDER BY COUNT(*) DESC, profession ASC` gives NECROMANCER; document the contract).

6. `test_aggregate_player_profiles_empty_db` — zero accounts → returns `[]`.

7. `test_aggregate_player_profiles_pre_v084_fallback_label` — assert the response tags pre-v0.8.4 fights (no summary row) with a `data_completeness == "partial"` flag (additive field; the wire surface stays 1.0-compatible if the field is `Optional`).

8. `test_pure_python_and_sql_paths_produce_byte_identical_results` — seed a tiny dataset (1 account × 3 fights); run BOTH the SQL aggregator and the legacy Python aggregator; assert the two responses are byte-identical modulo `attended_fight_ids` ordering.

9. `test_e2e_list_players_scales_to_10k_fights_under_500ms` (`@pytest.mark.integration`) — seed 10k fights × 50 agents each via a fixture helper; call `GET /api/v1/players` with `limit=50`; assert wallclock < 500ms AND peak RAM < 50MB (the SQL aggregations stay in the database; only the LIMIT 50 result is fetched).

### Test file 2 — EXTEND `apps/api/tests/test_players.py`

For each existing golden-day e2e test (4 playbook fixtures: top-Mesmer week, etc.), assert the response from `GET /api/v1/players?limit=500` is byte-identical to the pre-fix response. This is the **golden-output regression suite** — it pins the SQL refactor's correctness.

---

## Out of scope

- Caching the SQL aggregation result (Redis-backed hot-key cache for `/api/v1/players`). Out of scope per the user's "SQL aggregations complètes" preference; can be a follow-up plan if `/api/v1/players` becomes a hot path.
- Replacing `PlayerProfileAggregator` entirely (the deduplication logic + cross-field invariants stay; the SQL query is a SOURCE for the aggregator, not a replacement).
- Pagination of the per-account timeline by date range (the day-bucketed timeline already handles date-range aggregation; this plan does not change the day-bucket logic).
- `get_player_timeline`'s `?limit=&offset=` semantics — the existing 1-100 ceiling + recency-first sort is preserved.

---

## Done criteria

Run from repo root after the fix is applied:

```bash
# 1. Ruff is clean.
uv run ruff check apps/api/

# 2. mypy --strict tolerates the change (the new SQL aggregation module is fully typed).
uv run mypy libs apps --no-incremental

# 3. The new test files + extensions all pass.
uv run pytest apps/api/tests/test_player_profiles_sql.py -v
uv run pytest apps/api/tests/test_players.py -v

# 4. The 10k-fights benchmark passes in <500ms.
uv run pytest apps/api/tests/test_player_profiles_sql.py::test_e2e_list_players_scales_to_10k_fights_under_500ms -v

# 5. The legacy `select(OrmFight)...all()` pattern is gone from the 3 endpoints.
grep -nE 'select\(OrmFight\)\.order_by.*\.scalars\(\)\.all\(\)' apps/api/src/gw2analytics_api/routes/players.py
# Expected output: 1 match only at the route-level intentional repre, or (empty)

# 6. The full apps/api test suite remains green.
uv run pytest apps/api/tests/ -q
```

---

## Maintenance note

- The modal profession computation uses a window function. Postgres-specific syntax (no MySQL/SQLite fallback). If a future SQLite test-fixture environment emerges, the window function must be replaced with a Python-side pass over the per-account profession list (acceptable for tests; production uses the Postgres path).
- The 10k-fights benchmark depends on the `OrmFightPlayerSummary` row count. If the v0.8.5 backfill is not fully complete in production, the benchmark overshoots 500ms. Run twice — once aggressive (assume 100% coverage) and once conservative (assume 10% coverage) — to bound expectations.
- The `_contributions_from_blob_walk` fallback is preserved but DORMANT in production (post-v0.8.4). Don't DELETE it — the integration tests for the legacy path are still valuable; the operator's "rollback to v0.9.x" command relies on them.

---

## Escape hatches

- **Modal profession is wrong on a tied account (5 MESMER + 5 NEcro)?** The deterministic tiebreaker is `ORDER BY profession ASC` (alphabetical); but this is data-aware. If a UX-affecting complaint surfaces, change the tiebreaker to `ORDER BY SUM(total_damage) DESC` (the damage-weighted modal). 1-line SQL change; also update the test `test_modal_profession_tiebreaker`.
- **`MAX(name)` collision?** Two distinct characters with the same account_name but different char-names per fight → `MAX(name)` returns one of them, not necessarily the latest. The existing Python loop uses *last-seen-wins*. To preserve, replace `MAX(name)` with a `DISTINCT ON (account_name) ORDER BY fight_id DESC` LATERAL join. ~5 LoC.
- **STOP and report back if**: the 10k-fights benchmark overshoots 500ms by >2x. That's a Postgres-tuning issue (index on `OrmFightPlayerSummary.account_name` may be missing) — out of this plan's scope; surface for a separate audit pass.

---

## Dependency graph

- **Independent of plans 026, 027, 029, 030, 031.** Touches only `routes/players.py` + a new `services/player_profiles.py` module + 1 NEW test file + 1 EXTENDED test file.
- **Depends on the existing `OrmFightPlayerSummary` table** (introduced v0.8.4 plan 045) being populated. If a future backward-incompatible migration drops the table, this plan's SQL aggregations break.

## Cross-references

- Plan 045 (v0.8.4) — materialised `OrmFightPlayerSummary` (the prerequisite for SQL aggregations).
- Plan 047 (v0.9.14) — bulk-insert player summaries (the write-side counterpart).
- Plan 117 (v0.9.38) — per-target rollup helper extraction (a parallel refactor pattern for the routes/fights.py endpoint).
