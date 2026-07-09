# Plan 094 (v0.9.30) — `_BASE_URL` /v2 strip single-source-of-truth + per-request `Authorization` header

## Files touched
- `libs/gw2_api_client/src/gw2_api_client/client.py` (constants region near line 41-55 + `__init__` constructor at line ~125 + `account_get` / `worlds_get` near lines 167-188)

## Findings (audit)

- `client.py` line ~41: `_BASE_URL: Final[str] = "https://api.guildwars2.com/v2"` — the API version (`/v2`) is BAKED INTO `_BASE_URL`.
- `client.py` line ~167: `account_get` uses `url = "/v2/account"`.
- `client.py` line ~178: `worlds_get` uses `url = "/v2/worlds"`.
- The `/v2` segment is REPEATED on both sides (base + per-call URLs). httpx's URL join resolves the duplication in the right direction today (per-call `/v2/foo` REPLACES the base path, NOT concatenates), but the duplication is fragile:
  - If a future contributor strips `/v2` from `_BASE_URL` (e.g. "make base just the host"), the per-call URLs continue working because THEY carry `/v2`. Silent OK.
  - Conversely, if they strip `/v2` from one per-call URL ("make this endpoint cleaner"), the base-URL joiner still resolves to `/v2/foo` because `base_url` provides it. ALSO Silent OK.
  - But the test at `inspect.getsource(AsyncGuildWars2Client)` is brittle in BOTH directions — neither version of the URL is the "canonical" one. The next maintainer trying to add a v2 v3 endpoint (e.g. `account_get_v3`) has no single-source-of-truth to copy from.
- Single-source-of-truth rule: the API version segment should live in exactly one place. The per-call URL constant is more discoverable for the caller ("I want the account endpoint, let me look at `account_get`'s constant") and matches the pattern of well-known HTTP clients (httpx, aiohttp, requests-cache) which all use pluggable base URL + version-aware endpoint paths.

- `client.py` line ~130 (in `__init__`): `httpx.AsyncClient(headers={"Authorization": f"Bearer {api_key}"})` — the `Authorization` header is attached ONCE at the underlying httpx client's construction and persists across EVERY request, INCLUDING the `worlds_get` calls on a public endpoint.
  - `worlds_get` is documented in the Protocol as "auth optional" (line 96-104: "Empty `ids` returns `[]` WITHOUT making a request -- the v2 API rejects `ids=` (empty) with a 400 so we short-circuit client-side."). The auth-optional contract is a real semantic claim: the caller can pass a NO-account-scope key (`account: false` permission) or a read-only `worlds` key and expect that key to NOT be reused on requests that don't need auth.
  - But the current implementation BLEEDS the key onto every request. From a security/least-privilege standpoint, that's a violation: the key is logged by any HTTP proxy in the path (CDN logs, ArenaNet's own request logs, observability stacks). Worlds responses are cacheable by ArenaNet's CDN with the request Authorization HTTP-EQUIV header for some configurations (depends on CDN config), potentially pinning the key into a Cache-Control-Vary response.
  - The fix is also a future-proof: when the v2 API eventually ships an additional auth-required endpoint, the per-request auth-header pattern scales naturally (`Authorization` attached per call) without re-engineering the constructor.
- Multi-scope key caveat worth documenting: in practice, ArenaNet's `/v2/worlds` ignores the `Authorization` header (it's a public endpoint). BUT future ArenaNet endpoints (e.g. potentially-authenticated guild-specific views in upcoming v2 expansions) might NOT ignore it. The per-request pattern eliminates the assumption.

## Fix

1. `client.py` line ~41 — strip the `/v2`:

   ```python
   _BASE_URL: Final[str] = "https://api.guildwars2.com"
   """Base host for the Guild Wars 2 v2 REST API.

   The API version (``/v2``) lives on the per-call URL constants
   (``/v2/account`` / ``/v2/worlds``) so that adding a v3 endpoint
   later doesn't require a base-URL bump. httpx joins ``base_url +
   absolute-path`` by replacing the base path entirely, so the
   leading ``/v2`` in the per-call URL is what selects v2.
   """
   ```

2. `client.py` line ~167 / ~178 — leave the existing `url = "/v2/account"` / `url = "/v2/worlds"` constants as-is. They are now the SINGLE SOURCE of truth for the API version.

3. `client.py` line ~125 — DROP the `headers={"Authorization": ...}` from the `AsyncClient` constructor:

   ```python
   self._client = httpx.AsyncClient(
       base_url=_BASE_URL,
       timeout=timeout,
       # NOTE: the Authorization header is attached PER-REQUEST by
       # `_auth_headers(self, required)` so the API key never reaches
       # the public /v2/worlds endpoint (it's documented as
       # auth-optional in the Protocol).
   )
   ```

4. `client.py` — add a tiny helper next to `_get_with_retries`:

   ```python
   def _auth_headers(self) -> dict[str, str]:
       """Return the per-request Authorization header.

       Attached only by GETs against auth-required endpoints so a
       read-only / no-account-scope key never reaches public
       endpoints like /v2/worlds.
       """
       return {"Authorization": f"Bearer {self._api_key}"}
   ```

5. `client.py::_get_with_retries` — accept the per-request headers kwarg and merge with the constructor-fixed `self._client.get(...)` call:

   ```python
   async def _get_with_retries(
       self,
       url: str,
       *,
       params: dict[str, str] | None = None,
       headers: dict[str, str] | None = None,
   ) -> Any:
       """GET with 429 retry + non-2xx -> typed-error mapping.

       Returns the parsed JSON body.
       """
       request_headers = {**(headers or {})}
       attempt = 0
       while True:
           attempt += 1
           try:
               response = await self._client.get(
                   url, params=params, headers=request_headers or None
               )
           except httpx.HTTPError as exc:
               msg = f"{url}: transport error: {exc}"
               raise GuildWars2HttpError(msg) from exc

           if response.status_code == 429:
               if attempt >= _MAX_RATE_LIMIT_ATTEMPTS:
                   msg = f"{url}: rate-limited after {attempt} attempts"
                   raise GuildWars2RateLimitError(msg)
               delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
               await asyncio.sleep(delay)
               continue

           if response.status_code >= 400:
               msg = f"{url}: HTTP {response.status_code}: {response.text[:200]}"
               raise GuildWars2HttpError(msg)

           return response.json()
   ```

6. `client.py::account_get` and `client.py::worlds_get` — pass the per-request Auth header only from `account_get`:

   ```python
   async def account_get(self) -> AccountInfo:
       url = "/v2/account"
       data = await self._get_with_retries(url, headers=self._auth_headers())
       return AccountInfo.model_validate(data)

   async def worlds_get(self, ids: Sequence[int]) -> list[WorldInfo]:
       if not ids:
           return []
       url = "/v2/worlds"
       params = {"ids": ",".join(str(i) for i in ids)}
       # Public endpoint — do NOT send Authorization (least-privilege).
       data = await self._get_with_retries(url, params=params)
       return [WorldInfo.model_validate(row) for row in data]
   ```

## Tests (7 hermetic, NEW file `libs/gw2_api_client/tests/test_gw2_api_client_auth.py`)

- `test_base_url_strips_v2_segment` — `AsyncGuildWars2Client._BASE_URL == "https://api.guildwars2.com"` (defensive against re-add).
- `test_account_get_url_uses_v2_prefix` — `inspect.getsource(AsyncGuildWars2Client.account_get)` regex finds `"url = \"/v2/account\""` OR static URL capture (confirming the per-call URL is the canonical owner of the version).
- `test_worlds_get_url_uses_v2_prefix` — same for `worlds_get`.
- `test_async_client_constructor_does_not_attach_authorization_header` — instantiate `AsyncGuildWars2Client("test-key")`, inspect `client._client.headers` → dict does NOT contain `"Authorization"`. Defensive against re-add of the constructor-level auth header.
- `test_auth_headers_helper_returns_bearer_token` — `client._auth_headers() == {"Authorization": "Bearer test-key"}` (unit-level sanity).
- `test_account_get_sends_authorization_header` — monkeypatch `client._client.get` to capture kwargs, call `await client.account_get()`, assert `kwargs["headers"]["Authorization"] == "Bearer test-key"`.
- `test_worlds_get_does_not_send_authorization_header` — same pattern, call `await client.worlds_get([1001, 1002])`, assert `kwargs["headers"]` is empty (`None` after the empty-dict strip) or does NOT contain `"Authorization"`.

## Rejected alternatives

- **Keep the constructor-level `Authorization` header and add a header-stripping mechanism for `worlds_get`** (e.g. an opt-out flag) — couples the leak to the consumer (every call site has to remember the opt-out flag) instead of fixing it in the implementation. The per-request attachment is the cleaner abstraction. REJECTED.
- **Drop `_BASE_URL` entirely and inline `https://api.guildwars2.com/v2` into per-call URLs** — couples the host URL to every per-call constant. If the host ever changes (e.g. mirror / staging / mockserver), every per-call string changes. The base URL is the right abstraction. REJECTED.
- **Build two httpx clients (one with Authorization, one without) and pick per-request** — doubles the connection pool, complicates the `aclose` lifecycle, and adds memory overhead per client instance. Per-request header attachment is the simpler fix. REJECTED.
- **Hoist the API version (`/v2`) into a NEW constant `_API_VERSION = "v2"` used in BOTH `_BASE_URL` AND per-call URLs** — doubles up the constant surface without changing the fragility. The single-source-of-truth fix is to put the version in ONE place (the per-call URL is the more discoverable one). REJECTED.
- **Add `httpx.Transport` middleware to strip the Authorization header at the wire layer** — invisible-to-the-caller; surprising for future contributors reading the code (`Authorization` header is set but isn't sent on some requests). The per-request dictionary kwarg is the standard httpx pattern. REJECTED.
- **Leave `_BASE_URL` + per-call URLs with the duplicated `/v2`** — fine today but tech debt; the moment someone adds a v3 endpoint or a parameterized URL helper, the duplication bites. The strip is a 1-line fix with a 6-line test payoff. REJECTED.
- **Drop `worlds_get`'s "auth optional" Protocol claim and require auth on all calls** — would break read-only-keys (consumer keys without `account` scope). The minimum-disruption fix is to honour the existing protocol contract. REJECTED.

## Dependency graph

- Independent from plans 092 / 093 (different file regions: 094 touches the `__init__` constructor plus the URL constants region; 092 touches `__init__.py`; 093 touches the private `_get_with_retries` helper).
- Pair-suggested ordering with plan 093: BOTH touch `client.py`. Single PR recommended to avoid two PRs editing the same file in the same release window.
- No downstream effect on the Protocol `GuildWars2Client` — `account_get` and `worlds_get` signatures are unchanged. The Protocol remains satisfied by the class.
