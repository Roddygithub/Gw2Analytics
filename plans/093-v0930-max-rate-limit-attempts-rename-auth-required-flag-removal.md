# Plan 093 (v0.9.30) — `_MAX_RATE_LIMIT_RETRIES` rename + dead `auth_required` flag removal

## Files touched
- `libs/gw2_api_client/src/gw2_api_client/client.py` (constant rename + private helper signature change + `account_get` / `worlds_get` call-site adjustment)

## Findings (audit)

- `client.py` line 36: `_MAX_RATE_LIMIT_RETRIES: Final[int] = 3` — variable name says `RETRIES` but the docstring (line 37-38) says `"""Number of attempts (including the first) before giving up on a 429."""`. The code behaviour (`attempt >= 3`) is consistent with the docstring (3 attempts TOTAL: 1 initial + 2 retries).
- A future contributor who reads the variable name alone would mentally model "3 retries beyond the first" → 4 attempts total. If they then edited the value to `_MAX_RATE_LIMIT_RETRIES = 5` with that mental model, the code would actually do 5 attempts total (1 initial + 4 retries), off-by-one with their intent.
- The docstring versus name divergence is also a smell for static analysers and IDE autocomplete (the human-readable intent is encoded only in the docstring; the symbol autocomplete / go-to-definition shows just `RETRIES`).

- `client.py::_get_with_retries` line ~155 — the `auth_required: bool = True` parameter is semantically DEAD:
  ```python
  if response.status_code == 401 and auth_required:
      msg = f"{url}: 401 unauthorized (check GW2_API_KEY scope)"
      raise GuildWars2HttpError(msg)

  if response.status_code >= 400:
      msg = f"{url}: HTTP {response.status_code}: {response.text[:200]}"
      raise GuildWars2HttpError(msg)
  ```
  Whether `auth_required` is `True` (called by `account_get`) or `False` (called by `worlds_get`), a 401 raises the same exception class `GuildWars2HttpError` from BOTH branches. The flag changes the error MESSAGE TEXT for the auth-required-401 case, but does NOT change the exception type, the HTTP status code in the logs, or the retry behaviour. Since `worlds_get` is documented as "auth optional" and a 401 from a public endpoint is essentially impossible, the flag's only behavioural effect is to swap the error message string in a vanishingly rare case. It's a soft-dead flag.
- The downstream Protocol `GuildWars2Client` (lines 84-115) has `auth_required` propagation BURIED INSIDE the private helper (`_get_with_retries`). The Protocol contract never mentions `auth_required`; the flag never escapes the helper. It was likely added defensively when `worlds_get` was added but never wired through to the contract.

## Fix

1. `client.py` line 36 — rename:

   ```python
   _MAX_RATE_LIMIT_RETRIES: Final[int] = 3
   """Number of attempts (including the first) before giving up on a 429."""
   ```

   to:

   ```python
   _MAX_RATE_LIMIT_ATTEMPTS: Final[int] = 3
   """Number of attempts (including the first) before giving up on a 429.

   Renamed from ``_MAX_RATE_LIMIT_RETRIES`` for semantic clarity --
   "retries" suggests "retries BEYOND the first attempt" which off-by-
   one-foots the next contributor. The value is the TOTAL attempt
   count (initial + retries). The exponential backoff sequence for a
   429 storm is therefore ``_MAX_RATE_LIMIT_ATTEMPTS - 1`` sleep
   periods: 0.5s, 1.0s, 2.0s for the default value of 3.
   """
   ```

2. `client.py` line ~155 — rename the usage:

   ```python
   if attempt >= _MAX_RATE_LIMIT_ATTEMPTS:
       msg = f"{url}: rate-limited after {attempt} attempts"
       raise GuildWars2RateLimitError(msg)
   ```

3. `exceptions.py` — update the cross-reference on `GuildWars2RateLimitError`:

   ```python
   class GuildWars2RateLimitError(GuildWars2ClientError):
       """429 was hit and the client's local retry policy was exhausted.

       The client retries up to :data:`AsyncGuildWars2Client._MAX_RATE_LIMIT_ATTEMPTS`
       times total (initial + retries) before giving up...
       """
   ```

4. `client.py::_get_with_retries` — REMOVE the `auth_required` parameter (it's soft-dead: both 401 code paths raise the same exception). The function signature becomes:

   ```python
   async def _get_with_retries(
       self,
       url: str,
       *,
       params: dict[str, str] | None = None,
   ) -> Any:
       """GET with 429 retry + non-2xx -> typed-error mapping.

       Returns the parsed JSON body.
       """
       attempt = 0
       while True:
           attempt += 1
           try:
               response = await self._client.get(url, params=params)
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

5. `client.py::account_get` and `client.py::worlds_get` — drop the now-removed `auth_required=` kwarg from both call sites:

   ```python
   async def account_get(self) -> AccountInfo:
       url = "/v2/account"
       data = await self._get_with_retries(url)
       return AccountInfo.model_validate(data)

   async def worlds_get(self, ids: Sequence[int]) -> list[WorldInfo]:
       if not ids:
           return []
       url = "/v2/worlds"
       params = {"ids": ",".join(str(i) for i in ids)}
       data = await self._get_with_retries(url, params=params)
       return [WorldInfo.model_validate(row) for row in data]
   ```

## Tests (6 hermetic, NEW file `libs/gw2_api_client/tests/test_gw2_api_client_internals.py` + UPDATE to `tests/test_client.py`)

- `test_max_rate_limit_attempts_constant_present` — `AsyncGuildWars2Client._MAX_RATE_LIMIT_ATTEMPTS == 3` and the old `_MAX_RATE_LIMIT_RETRIES` is gone (defensive: catches accidental re-add).
- `test_max_rate_limit_attempts_default_value_still_three` — the value didn't change during the rename (catches a copy-paste edit accident like `=5`).
- `test_get_with_retries_signature_drops_auth_required_kwarg` — `inspect.signature(AsyncGuildWars2Client._get_with_retries).parameters` does NOT contain `"auth_required"`. Defensive against a future re-add.
- `test_account_get_signature_unchanged` — `inspect.signature(AsyncGuildWars2Client.account_get).parameters == {"self", "return"}`. Confirm the public surface didn't break; `account_get` is part of the `GuildWars2Client` Protocol (referenced by `apps/api` integration tests).
- `test_worlds_get_signature_unchanged` — same for `worlds_get`. Both methods remain Protocol-conformant to `GuildWars2Client`.
- `test_protocol_guildwars2client_still_satisfied` — `isinstance(AsyncGuildWars2Client.__init__...)` attr check via `runtime_checkable`: instantiate a stub that implements `supported_endpoints + account_get + worlds_get` and confirm `isinstance(stub, GuildWars2Client)` (regression: confirm the Protocol itself wasn't touched).

## Rejected alternatives

- **Keep `_MAX_RATE_LIMIT_RETRIES` with a longer docstring explaining the off-by-one hazard** — idiomatic Python (PEP 8: short, meaningful names) prefers the rename to the LLM-eating docstring. The replacement name is self-explanatory. REJECTED.
- **Just remove the `auth_required` param without renaming `_MAX_RATE_LIMIT_RETRIES`** — leaves the off-by-one footgun in place. Combining both cleanups in one PR keeps the diff audit-friendly. REJECTED.
- **Add a typed `GuildWars2AuthError` exception subclass to make the `auth_required` distinction meaningful** — bigger design change (new public exception surface), cross-library impact (consumer `apps/api` would need to update `except` clauses). Out of scope for this audit pass; the minimal fix is to drop the soft-dead flag. REJECTED.
- **Wire `auth_required` into the Protocol `GuildWars2Client` as an explicit method-level attribute** — couples a soft-dead flag to the public contract; the minimal fix is to drop the flag entirely (the wire-level distinction is what would matter, not a Python keyword). REJECTED.
- **Use `warnings.warn(DeprecationWarning, "auth_required is removed; the helper no longer distinguishes 401 sources")`** — there's no consumer outside the library; the helper is private (`_` prefix). The deprecation warning would never be seen outside the unit tests. Skip. REJECTED.
- **Leave `_MAX_RATE_LIMIT_RETRIES` as an alias + add `_MAX_RATE_LIMIT_ATTEMPTS`** — two-name aliasing is the kind of subtle-bug surface this plan is trying to REMOVE (cf. the python-elite-spec `UNKNOWN = BASE = 0` issue that plan 090 fixes). Don't introduce what we're removing. REJECTED.

## Dependency graph

- Independent from plan 092 (different file: `__init__.py` vs `client.py`).
- Parallel-safe with plan 094 (different regions of `client.py`: plan 093 touches the helper signature; plan 094 touches the constructor `AsyncClient(...)` invocation + `_BASE_URL` constant).
- No downstream effect — `_get_with_retries` is private (`_` prefix), never exported via `__init__.py` or `__all__`. The public Protocol surface (`account_get`, `worlds_get`, `supported_endpoints`) is byte-identical at the signature level.
