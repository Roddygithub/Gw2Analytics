# Plan 144 (v0.10.9) — fix `KeyError` crash in `GET /compare/timeline`

**Severity:** CRITICAL (finding C1 of [AUDIT-2026-07-10](./AUDIT-2026-07-10-79c4501.md)).
**Origin:** shipped broken in the original plan 032 (v0.10.0, commit `651ff70`); the later lint commit `d4dc6f4` only touched the type annotation, not the defect.

## The bug

`apps/api/src/gw2analytics_api/routes/player_compare.py::get_compare_timeline`:

```python
per_account_contributions: dict[str, list[FightContribution]] = {}
for c in contributions:
    per_account_contributions[c.account_name].append(c)   # KeyError
```

`per_account_contributions` is a plain `dict`, so `[c.account_name].append(c)` raises
`KeyError` on the first contribution of every account. Since `_compute_contributions`
rolls up **all** accounts across **all** fights, `contributions` is non-empty whenever
the database holds any player data, so `GET /api/v1/players/compare/timeline` returns
**500 for any real dataset**. It only survives the empty-DB path.

There is a **second** defect hidden behind the first: even with a `defaultdict`, the loop
would key the dict by *every* account that has contributions, not by the *requested*
accounts. But `CrossAccountTimelineAggregator.aggregate` emits exactly one series per
dict key (see its docstring), and the endpoint contract (docstring +
`test_compare_unknown_account_returns_empty_points_series`) requires:

- one series per **requested** (deduped) account, and
- an account with no contributions still gets a series with empty `points`.

So the dict must be **pre-seeded from `deduped_accounts`** and only requested accounts'
contributions appended. The current code delivers neither.

## Fix

Extract the grouping into a small, pure, hermetically-testable helper and pre-seed it
from the requested accounts:

```python
def _group_contributions_by_account(
    contributions: Iterable[FightContribution],
    requested_accounts: Iterable[str],
) -> dict[str, list[FightContribution]]:
    grouped: dict[str, list[FightContribution]] = {a: [] for a in requested_accounts}
    for c in contributions:
        bucket = grouped.get(c.account_name)
        if bucket is not None:
            bucket.append(c)
    return grouped
```

The route calls `_group_contributions_by_account(contributions, deduped_accounts)`.
This: (1) never `KeyError`s, (2) yields exactly the requested accounts as keys (so the
aggregator emits one series per requested account), (3) gives unknown/no-contribution
accounts an empty list (→ empty-`points` series), and (4) drops contributions from
non-requested accounts.

## Tests

- NEW `apps/api/tests/test_player_compare_grouping.py` (hermetic, no DB): 4 cases —
  empty contributions pre-seed all requested accounts to empty lists; contributions
  routed to the right requested account; non-requested-account contributions dropped;
  unknown requested account gets an empty list. These pin the fix without Postgres.
- The existing Postgres-backed `test_player_compare.py` contract suite (2/3/4-account
  success, unknown-account-empty, day-bucket) validates the end-to-end path on CI.

## Effort

`S` — 1 helper + 1 call-site edit + 1 import + 1 NEW hermetic test file.

## Verification note

The Postgres-backed route tests were NOT run locally (no Docker in the dev env); the fix
was verified via ruff, mypy, and the new hermetic grouping tests, and will be validated
end-to-end by `test_player_compare.py` on CI.
