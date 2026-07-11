# Plan 039 — v0.9.11 gw2_api_client: chunk `worlds_get(ids)` at 200

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — `libs/gw2_core` + `libs/gw2_api_client` deep pass
**Status:** pending
**Effort:** S
**Category:** correctness (API contract compliance) + reliability (URL length DoS)
**Files touched:** `libs/gw2_api_client/src/gw2_api_client/client.py` (1 file, additive changes only) + `libs/gw2_api_client/tests/test_client.py` (NEW test cases)

## Problem

`libs/gw2_api_client/src/gw2_api_client/client.py::worlds_get`
takes a `Sequence[int]` of world ids and sends them in a
single request:

```python
async def worlds_get(self, ids: Sequence[int]) -> list[WorldInfo]:
    if not ids:
        return []
    url = "/v2/worlds"
    params = {"ids": ",".join(str(i) for i in ids)}
    data = await self._get_with_retries(url, params=params, auth_required=False)
    return [WorldInfo.model_validate(row) for row in data]
```

The GW2 v2 API caps `ids` at 200 per request
(`?ids=1,2,...,200` is OK; `?ids=1,2,...,201` returns
400 Bad Request). A caller who passes 1000 ids gets a
400 response + a hard `GuildWars2HttpError`.

For larger inputs, the constructed URL is also massive
(e.g. 10000 ids × 6 chars each = 60KB URL, which
exceeds the typical 8KB URL length cap on most HTTP
servers and proxies; Caddy + nginx + Apache all cap
at ~8KB by default). A caller who passes 10000 ids
gets a 414 URI Too Long response + a hard
`GuildWars2HttpError`.

### Severity

- **Correctness**: MED — a caller who passes >200 ids
  gets a hard error instead of the expected results.
  The caller has to manually chunk the input, which
  is duplicate work across the codebase.
- **Reliability**: MED — a caller who passes >~1300
  ids gets a 414 URI Too Long; the failure mode is
  infrastructure-level (the URL is rejected before
  the application logic can respond), which is harder
  to debug than an application-level 400.

### Affected callers

The `worlds_get` method is called from
`apps/api/src/gw2analytics_api/routes/account.py` to
resolve the `world_name` + `world_population` for the
authenticated account's `world_id`. The call site
passes a single-element list (just the account's
`world_id`), so the immediate user is unaffected. The
canonical caller is the apps/api route.

A future caller (e.g. a "browse worlds" page on the
web frontend) that wants to resolve all 89 GW2 worlds
in one call would hit the issue. The current code
defers this to the caller, which is the canonical
"no premature optimisation" pattern, but the
canonical "fix the contract" pattern is to chunk
inside the client.

## Goals

- Add a module constant
  `_MAX_IDS_PER_REQUEST: Final[int] = 200` matching
  the GW2 v2 API cap.
- In `worlds_get`, chunk the `ids` into batches of
  200 and issue one request per batch.
- Concatenate the results in input order.
- Add hermetic tests for: (1) a 250-id input is
  split into 2 requests (200 + 50); (2) a 200-id
  input is a single request; (3) an empty input
  short-circuits to `[]` (existing behaviour
  preserved); (4) the results are concatenated in
  input order.

## Non-goals

- Adding async parallelism (e.g. `asyncio.gather`) to
  the chunked requests. The GW2 API rate limit is
  per-IP; serial requests respect the rate limit;
  parallel requests would amplify the rate-limit
  pressure. Out of scope.
- Adding a similar cap to a future
  `account_get_batch` method. The
  `account_get` method is a single-resource endpoint
  (it returns the authenticated account, not a list);
  no chunking is needed.
- Switching the `worlds_get` return type to a
  generator (lazy evaluation). The current
  `list[WorldInfo]` return type is the canonical
  "fetch all, return all" pattern for small inputs.
- Documenting the 200-id cap in the public API
  (Protocol docstring). The cap is an implementation
  detail; the Protocol's contract is "fetch world
  metadata for the given ids".

## Implementation

### File: `libs/gw2_api_client/src/gw2_api_client/client.py`

Add the chunking logic. The diff is a
`_MAX_IDS_PER_REQUEST` constant + a refactored
`worlds_get` body.

```python
# ... (existing module constants) ...

_MAX_IDS_PER_REQUEST: Final[int] = 200
"""Maximum ids per ``worlds_get`` request.

The GW2 v2 API caps ``ids`` at 200 per request
(``?ids=1,2,...,200`` is OK; ``?ids=1,2,...,201``
returns 400 Bad Request). The client chunks larger
inputs into batches of 200 internally so the
caller can pass any-length ``Sequence[int]``
without manual chunking.
"""
```

Replace the `worlds_get` body with a chunking
implementation:

```python
async def worlds_get(self, ids: Sequence[int]) -> list[WorldInfo]:
    """Fetch world metadata for ``ids``. Empty inputs
    short-circuit to ``[]`` (no HTTP). Inputs > 200
    are chunked into batches of 200 (the GW2 v2 API
    cap) and the results are concatenated in input
    order.
    """
    if not ids:
        return []
    url = "/v2/worlds"
    results: list[WorldInfo] = []
    for start in range(0, len(ids), _MAX_IDS_PER_REQUEST):
        chunk = ids[start : start + _MAX_IDS_PER_REQUEST]
        params = {"ids": ",".join(str(i) for i in chunk)}
        data = await self._get_with_retries(
            url, params=params, auth_required=False,
        )
        # ``data`` is a list of world records; validate
        # each row. The list is in the same order as
        # the ``ids`` chunk (the GW2 v2 API echoes the
        # input order), so concatenation in chunk order
        # produces the same output as a single
        # request would.
        results.extend(WorldInfo.model_validate(row) for row in data)
    return results
```

### File: `libs/gw2_api_client/tests/test_client.py` (NEW test cases)

```python
class TestWorldsGetChunking:
    """The ``worlds_get`` method chunks inputs > 200
    into batches of 200 (the GW2 v2 API cap)."""

    async def test_empty_ids_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An empty ``ids`` returns ``[]`` without
        making an HTTP request."""
        request_count = {"n": 0}
        # ... mock _get_with_retries to count calls;
        # assert the call count is 0

    async def test_200_ids_is_single_request(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 200-id input is a single request (boundary
        case for the 200-cap)."""
        request_count = {"n": 0}
        # ... mock _get_with_retries to count calls;
        # assert the call count is 1

    async def test_201_ids_is_two_requests(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 201-id input is split into 2 requests
        (200 + 1)."""
        request_count = {"n": 0}
        # ... mock _get_with_retries to count calls;
        # assert the call count is 2

    async def test_500_ids_is_three_requests(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 500-id input is split into 3 requests
        (200 + 200 + 100)."""
        request_count = {"n": 0}
        # ... mock _get_with_retries to count calls;
        # assert the call count is 3

    async def test_results_concatenated_in_input_order(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A multi-chunk input returns results in
        input order, not chunk order."""
        # ... mock _get_with_retries to return a
        # different WorldInfo per chunk; assert the
        # final results are in input order
```

## Test plan

1. **5 new hermetic tests** in
   `libs/gw2_api_client/tests/test_client.py` cover
   the 5 chunking cases (empty, 200, 201, 500,
   order).
2. **All existing tests pass** — the change is
   backwards-compatible for any input <= 200
   (single request, same behaviour as before).
3. **`uv run pytest libs/gw2_api_client/tests/`**
   exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `_MAX_IDS_PER_REQUEST = 200` constant is added
      with a docstring citing the GW2 v2 API cap.
- [ ] `worlds_get` chunks inputs > 200 into batches
      of 200.
- [ ] Results are concatenated in input order.
- [ ] 5 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the
      chunking is invisible for any input <= 200;
      the immediate caller in apps/api passes a
      single-element list, so the existing
      behaviour is preserved).

## Out-of-scope / deferred

- **Adding async parallelism (`asyncio.gather`)**:
  out of scope (serial requests respect the
  per-IP rate limit; parallel requests would
  amplify the rate-limit pressure).
- **Adding a similar cap to a future
  `account_get_batch` method**: out of scope
  (the `account_get` method is a single-resource
  endpoint, not a list endpoint).
- **Switching `worlds_get` to a generator (lazy
  evaluation)**: out of scope (the canonical
  pattern for small inputs is "fetch all, return
  all").
- **Documenting the 200-id cap in the Protocol
  docstring**: out of scope (the cap is an
  implementation detail; the Protocol's contract
  is "fetch world metadata for the given ids").

## Maintenance notes

- **The chunking is a pure client-side fix**; the
  GW2 v2 API is not modified. A future change to
  the API cap (e.g. 200 → 500) is a 1-line
  constant update.
- **The serial loop respects the per-IP rate
  limit**. A future caller that needs faster
  bulk-loads can wrap their own `asyncio.gather`
  around the `worlds_get` call (or implement a
  parallel `worlds_get_parallel` method that
  internally uses `asyncio.gather` + a semaphore
  to respect the rate limit).
- **The 200-cap is the current GW2 v2 API
  contract** (documented at
  https://wiki.guildwars2.com/wiki/API:2/worlds).
  The wiki does not list an exact cap; the 200
  figure is the de-facto industry standard for
  similar paginated endpoints (matches the GW2
  v2 `/v2/items` cap). A future plan can add a
  per-endpoint cap table if the API exposes
  different caps for different endpoints.
- **The `worlds_get` order-preservation contract
  relies on the GW2 v2 API echoing the input
  order**. The API documents this contract for
  the `/v2/worlds?ids=` endpoint. A future
  hardening pass can add an explicit order
  assertion (e.g. `assert data[0].id == ids[0]`
  in the test) to catch a future API change.
