# Plan 049 — v0.9.15 `account.py` 401 detection via exception attribute

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/src/gw2analytics_api/routes/*` deep pass
**Status:** pending
**Effort:** S
**Category:** reliability (brittle string dispatch)
**Files touched:** `libs/gw2_api_client/src/gw2_api_client/exceptions.py` (1 file, additive change only) + `libs/gw2_api_client/src/gw2_api_client/client.py` (1-line change to pass the status code) + `apps/api/src/gw2analytics_api/routes/account.py` (replace the string-based dispatch with attribute-based dispatch) + `apps/api/tests/test_account.py` (1 NEW test case) + `libs/gw2_api_client/tests/test_client.py` (1 NEW test case)

## Problem

`apps/api/src/gw2analytics_api/routes/account.py::get_account_enriched`
detects an upstream 401 (invalid API key) by parsing
the error message string from
`GuildWars2HttpError`:

```python
except GuildWars2HttpError as exc:
    logger.warning("/api/v1/account upstream http error: %s", exc)
    msg = str(exc)
    if "401 unauthorized" in msg or "HTTP 401:" in msg:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid api key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "upstream error",
    ) from exc
```

The two message forms come from the two branches in
`libs/gw2_api_client/src/gw2_api_client/client.py::_get_with_retries`:

```python
if response.status_code == 401 and auth_required:
    msg = f"{url}: 401 unauthorized (check GW2_API_KEY scope)"
    raise GuildWars2HttpError(msg)
# ...
if response.status_code >= 400:
    msg = f"{url}: HTTP {response.status_code}: {response.text[:200]}"
    raise GuildWars2HttpError(msg)
```

A future refactor of the client's error message
format (e.g. changing "401 unauthorized" to
"Unauthorized" or "HTTP 401:" to "status: 401")
would silently break the route's 401 detection. A
5xx response whose body happens to contain the
literal "401" would also be misrouted to the 401
branch (the comment acknowledges this risk).

The canonical fix is to add a `status_code: int`
attribute to `GuildWars2HttpError` so the route
can dispatch on `exc.status_code` (an int) instead
of `str(exc)` (a string with the status code
embedded as a substring).

### Severity

- **Reliability**: MED — a future refactor of the
  gw2_api_client error message format would
  silently break the 401 detection. The route
  would misroute 401 responses to 502 (upstream
  error) instead of 401 (invalid API key). The
  user sees a misleading "upstream error" message
  instead of "invalid api key".
- **DX**: MED — the string-based dispatch is
  fragile + the comment acknowledges the
  misrouting risk.

## Goals

- Add a `status_code: int` attribute to
  `GuildWars2HttpError` (set in the constructor).
- Update the gw2_api_client to pass the status
  code when raising `GuildWars2HttpError`.
- Update `account.py` to dispatch on
  `exc.status_code == 401` (an int comparison)
  instead of `"401 unauthorized" in msg` (a
  string substring match).
- Add 2 hermetic tests: (1) the exception's
  `status_code` attribute is set correctly;
  (2) the route dispatches to 401 on
  `exc.status_code == 401` regardless of the
  error message string.

## Non-goals

- Refactoring the gw2_api_client's error message
  format. The message format stays as-is; the
  canonical addition is the `status_code`
  attribute.
- Adding a `status_code` attribute to the
  `GuildWars2RateLimitError` exception (the
  rate-limit path is always 429; no need for a
  per-instance attribute).
- Removing the string-based dispatch as a
  defence-in-depth fallback. The string-based
  check is preserved in the route for clients
  that raise `GuildWars2HttpError` without a
  `status_code` attribute (a future
  backwards-compat shim).

## Implementation

### File: `libs/gw2_api_client/src/gw2_api_client/exceptions.py`

Add a `status_code: int` attribute to
`GuildWars2HttpError`.

```python
class GuildWars2HttpError(GuildWars2ClientError):
    """A non-2xx response from the v2 API was received.

    Separate from :class:`GuildWars2RateLimitError` so callers can
    choose to retry on rate-limit while surfacing other HTTP errors
    (401, 403, 404, 5xx) directly to the user.

    v0.9.15 plan 049: the ``status_code`` attribute
    carries the upstream HTTP status code (401, 403,
    404, 5xx, etc.) so callers can dispatch on the
    status code (an int) instead of parsing the
    error message string. The attribute is set in
    the constructor; the ``message`` argument is
    the canonical error message (preserved for
    logging + backwards compat with callers that
    parse the message).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
```

### File: `libs/gw2_api_client/src/gw2_api_client/client.py`

Update the 2 `GuildWars2HttpError` raise sites to
pass the status code.

```python
# BEFORE (in _get_with_retries):
if response.status_code == 401 and auth_required:
    msg = f"{url}: 401 unauthorized (check GW2_API_KEY scope)"
    raise GuildWars2HttpError(msg)

# AFTER:
if response.status_code == 401 and auth_required:
    msg = f"{url}: 401 unauthorized (check GW2_API_KEY scope)"
    raise GuildWars2HttpError(msg, status_code=response.status_code)


# BEFORE:
if response.status_code >= 400:
    msg = f"{url}: HTTP {response.status_code}: {response.text[:200]}"
    raise GuildWars2HttpError(msg)

# AFTER:
if response.status_code >= 400:
    msg = f"{url}: HTTP {response.status_code}: {response.text[:200]}"
    raise GuildWars2HttpError(msg, status_code=response.status_code)
```

### File: `apps/api/src/gw2analytics_api/routes/account.py`

Replace the string-based dispatch with
attribute-based dispatch. The string-based check
is preserved as a defence-in-depth fallback (a
`GuildWars2HttpError` raised without a
`status_code` attribute still falls through to
the string-based check).

```python
except GuildWars2HttpError as exc:
    # v0.9.15 plan 049: dispatch on the
    # ``status_code`` attribute (an int) instead
    # of parsing the error message string. The
    # string-based check is preserved as a
    # defence-in-depth fallback for backwards
    # compat with callers that raise
    # ``GuildWars2HttpError`` without a
    # ``status_code`` attribute.
    logger.warning("/api/v1/account upstream http error: %s", exc)
    is_401 = (
        exc.status_code == 401
        if exc.status_code is not None
        else "401 unauthorized" in str(exc) or "HTTP 401:" in str(exc)
    )
    if is_401:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid api key",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "upstream error",
    ) from exc
```

### File: `apps/api/tests/test_account.py` (1 NEW test case)

```python
def test_401_detection_via_status_code_attribute() -> None:
    """The route dispatches to 401 on
    ``exc.status_code == 401`` regardless of the
    error message string.

    A future refactor of the gw2_api_client
    error message format (e.g. changing "401
    unauthorized" to "Unauthorized") would
    silently break the string-based dispatch.
    The attribute-based dispatch is the canonical
    defence in depth.
    """
    from gw2_api_client import GuildWars2HttpError
    from unittest.mock import patch

    # Patch the gw2_api_client to raise a
    # GuildWars2HttpError with a non-canonical
    # message but a status_code=401.
    with patch("gw2_api_client.AsyncGuildWars2Client.account_get") as mock_get:
        mock_get.side_effect = GuildWars2HttpError(
            "weirdly-formatted error",
            status_code=401,
        )
        resp = client.get(
            "/api/v1/account",
            headers={"Authorization": "Bearer fake-key"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "invalid api key"
```

### File: `libs/gw2_api_client/tests/test_client.py` (1 NEW test case)

```python
def test_guild_wars_2_http_error_has_status_code() -> None:
    """The ``status_code`` attribute is set
    correctly on the exception."""
    from gw2_api_client.exceptions import GuildWars2HttpError

    exc = GuildWars2HttpError("test", status_code=401)
    assert exc.status_code == 401
    assert "test" in str(exc)

    # Backwards compat: a GuildWars2HttpError
    # raised without a status_code is still
    # valid (the attribute is None).
    exc_no_code = GuildWars2HttpError("no code")
    assert exc_no_code.status_code is None
```

## Test plan

1. **1 new hermetic test** in
   `libs/gw2_api_client/tests/test_client.py`
   covers the `status_code` attribute contract.
2. **1 new hermetic test** in
   `apps/api/tests/test_account.py` covers the
   route's attribute-based dispatch.
3. **All existing tests pass** — the change is
   backwards-compatible for any code that doesn't
   use the new attribute (the string-based
   dispatch is preserved as a fallback).
4. **`uv run pytest libs/gw2_api_client/tests/ apps/api/tests/`**
   exits 0.
5. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `GuildWars2HttpError.__init__` accepts a
      `status_code: int | None` keyword argument.
- [ ] The 2 `GuildWars2HttpError` raise sites in
      `client.py` pass the status code.
- [ ] `account.py` dispatches on
      `exc.status_code == 401` (attribute-based)
      with a string-based fallback for backwards
      compat.
- [ ] 2 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the
      attribute is additive; the existing
      message-based behaviour is preserved as a
      fallback).

## Out-of-scope / deferred

- **Refactoring the gw2_api_client's error
  message format**: out of scope (the message
  format stays as-is; the canonical addition is
  the `status_code` attribute).
- **Adding a `status_code` attribute to
  `GuildWars2RateLimitError`**: out of scope (the
  rate-limit path is always 429; no need for a
  per-instance attribute).
- **Removing the string-based dispatch as a
  defence-in-depth fallback**: out of scope (the
  fallback is preserved for backwards compat with
  callers that raise `GuildWars2HttpError`
  without a `status_code` attribute).

## Maintenance notes

- **The `status_code: int | None` attribute** is
  optional (defaults to `None` for backwards
  compat with callers that raise
  `GuildWars2HttpError` without a status code).
  A future hardening pass can make the attribute
  required (the 2 internal call sites in
  `client.py` always pass a status code; the
  external API is the only consumer of the
  `None` path).
- **The string-based dispatch is preserved** in
  `account.py` as a defence-in-depth fallback.
  A future plan can remove the fallback once all
  callers have migrated to the attribute-based
  dispatch.
- **The attribute name `status_code` is
  consistent with the HTTP `Response.status_code`
  attribute** (the httpx convention). A future
  plan that adds a `headers` attribute to
  `GuildWars2HttpError` can use the same naming
  convention.
- **The error message format stays as-is** for
  backwards compat with logging + alerting
  pipelines that parse the message string. A
  future plan can refactor the format to
  structured logging (e.g. JSON) once all
  consumers are migrated.
