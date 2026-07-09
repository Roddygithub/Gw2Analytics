# Plan 038 — v0.9.11 gw2_api_client: respect `Retry-After` + jittered backoff

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — `libs/gw2_core` + `libs/gw2_api_client` deep pass
**Status:** pending
**Effort:** S
**Category:** reliability (DoS amplification + thundering herd)
**Files touched:** `libs/gw2_api_client/src/gw2_api_client/client.py` (1 file, additive changes only) + `libs/gw2_api_client/tests/test_client.py` (NEW test cases)

## Problem

`libs/gw2_api_client/src/gw2_api_client/client.py::_get_with_retries`
handles 429 responses with a fixed exponential backoff:

```python
if response.status_code == 429:
    if attempt >= _MAX_RATE_LIMIT_RETRIES:
        msg = f"{url}: rate-limited after {attempt} attempts"
        raise GuildWars2RateLimitError(msg)
    # Exponential backoff: 0.5, 1.0, 2.0, ...
    delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
    await asyncio.sleep(delay)
    continue
```

The Guild Wars 2 v2 API sends a `Retry-After` header on
429 responses (HTTP RFC 7231 §7.1.3) that indicates the
canonical backoff duration in seconds. The current code
ignores the header and uses the fixed 0.5/1.0/2.0 second
backoff regardless. The canonical pattern is to respect
`Retry-After` (server-specified) over local policy
(client-specified).

### Severity

- **Reliability**: MED — a server that says "retry in
  30s" via `Retry-After` is bypassed by the fixed 1.0s
  backoff. The client retries too soon, gets 429 again,
  retries again at 2.0s, gets 429 again, and exhausts
  the 3-attempt budget in ~3.5 seconds instead of
  respecting the server's request. The caller sees a
  `GuildWars2RateLimitError` that the server would
  have happily served after the prescribed 30s.
- **DoS amplification**: LOW — the client's premature
  retries add load to the server (3 requests in 3.5s
  instead of 1 request after 30s). The server's
  per-IP rate limiter is the right defence; the
  client should respect it.
- **Thundering herd**: LOW — multiple concurrent
  callers (e.g. 8 webhook workers processing 8
  parallel account resolutions) all hit the same
  429 at the same moment, all back off for the same
  deterministic duration (0.5s, 1.0s, 2.0s), all
  retry at the same moment, all get 429 again. The
  canonical pattern is to add ±20% jitter to the
  backoff so the retries are spread out.

## Goals

- Respect the `Retry-After` header on 429 responses:
  if present, use its value (in seconds) as the sleep
  duration; if absent, fall back to the existing
  exponential backoff.
- Add ±20% jitter to the backoff duration (whether
  from `Retry-After` or from the exponential
  fallback) to avoid thundering herd.
- Add hermetic tests for: (1) `Retry-After` header
  is respected; (2) jitter is applied to both
  `Retry-After`-derived and exponential-fallback
  delays; (3) jitter is bounded to ±20%.

## Non-goals

- Switching to a different retry library (e.g.
  `tenacity`, `backoff`). The current
  hand-rolled retry loop is sufficient; the
  library would add a dep for the same
  behaviour.
- Adding a circuit breaker (N failures → open
  for M seconds). Out of scope (too complex
  for a small library; the canonical pattern
  is for the caller to add a circuit breaker
  on top of this client).
- Respecting the `Retry-After` header on 503
  Service Unavailable responses. The current
  503 handling raises `GuildWars2HttpError`
  immediately (no retry). A future plan can
  add 503-with-Retry-After retry support.
- Parsing HTTP-date format for `Retry-After`
  (the RFC allows either seconds OR HTTP-date
  format). The GW2 v2 API uses seconds-only;
  parsing HTTP-date would be over-engineered.

## Implementation

### File: `libs/gw2_api_client/src/gw2_api_client/client.py`

Replace the 429 handling block with a version that
respects `Retry-After` + applies jitter. The diff is
a 10-line replacement of the 429 branch + a new
module-level helper.

```python
import random

# ... (existing imports) ...

# ±20% jitter on the backoff duration. The canonical
# pattern to avoid thundering herd when multiple
# concurrent callers hit the same 429 at the same
# moment. The jitter is applied to BOTH the
# `Retry-After`-derived delay AND the exponential
# fallback delay.
_JITTER_FRACTION: Final[float] = 0.2


def _apply_jitter(delay: float) -> float:
    """Apply ±20% uniform jitter to a backoff delay.

    The canonical pattern to avoid thundering herd.
    Multiple concurrent callers hitting the same 429
    at the same moment would otherwise all back off
    for the same deterministic duration and retry at
    the same moment, amplifying the load on the
    server. The ±20% jitter spreads the retries
    uniformly over ``[delay * 0.8, delay * 1.2]``.

    Examples
    --------
    >>> _apply_jitter(1.0)  # doctest: +SKIP
    0.95  # or 1.13, or any value in [0.8, 1.2]
    """
    jitter_range = delay * _JITTER_FRACTION
    return delay + random.uniform(-jitter_range, +jitter_range)
```

Update the 429 handling block:

```python
if response.status_code == 429:
    if attempt >= _MAX_RATE_LIMIT_RETRIES:
        msg = f"{url}: rate-limited after {attempt} attempts"
        raise GuildWars2RateLimitError(msg)
    # Respect the server-specified ``Retry-After``
    # header (HTTP RFC 7231 §7.1.3) when present;
    # fall back to the exponential backoff when
    # absent. The header value is in seconds (the
    # GW2 v2 API uses seconds-only; HTTP-date format
    # is not used by the GW2 API and is intentionally
    # not parsed here).
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            delay = float(retry_after)
        except ValueError:
            # Malformed ``Retry-After`` header -- fall
            # back to the exponential backoff. A
            # malformed header is a server bug; the
            # canonical fallback is the client's
            # local policy.
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
    else:
        # No ``Retry-After`` header -- use the
        # exponential backoff (0.5, 1.0, 2.0, ...).
        delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
    # Apply ±20% jitter to avoid thundering herd.
    delay = _apply_jitter(delay)
    await asyncio.sleep(delay)
    continue
```

### File: `libs/gw2_api_client/tests/test_client.py` (NEW test cases)

```python
class TestRetryAfterRespect:
    """The client respects the server-specified
    ``Retry-After`` header on 429 responses."""

    async def test_retry_after_header_respected(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 429 with ``Retry-After: 5`` sleeps for ~5
        seconds (not the 0.5s exponential backoff)."""
        sleep_calls: list[float] = []
        async def fake_sleep(d: float) -> None:
            sleep_calls.append(d)
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        # Disable jitter for determinism.
        monkeypatch.setattr(
            "gw2_api_client.client._apply_jitter",
            lambda d: d,
        )
        # ... build a mock client that returns 429 with
        # ``Retry-After: 5`` then 200; assert sleep_calls
        # == [5.0]

    async def test_retry_after_missing_falls_back_to_exponential(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 429 without ``Retry-After`` uses the
        exponential backoff (0.5, 1.0, 2.0, ...)."""
        # ... build a mock client that returns 429 without
        # ``Retry-After``; assert sleep_calls[0] is in
        # [0.4, 0.6] (jittered 0.5)

    async def test_retry_after_malformed_falls_back_to_exponential(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 429 with a malformed ``Retry-After`` (e.g.
        ``Retry-After: tomorrow``) falls back to the
        exponential backoff."""
        # ... build a mock client that returns 429 with
        # ``Retry-After: not-a-number``; assert
        # sleep_calls[0] is in [0.4, 0.6]


class TestJitter:
    """The ±20% jitter is applied to both
    ``Retry-After``-derived and exponential-fallback
    delays."""

    def test_jitter_bounded_to_20_percent(self) -> None:
        """`_apply_jitter(1.0)` returns a value in
        ``[0.8, 1.2]``."""
        for _ in range(1000):
            d = _apply_jitter(1.0)
            assert 0.8 <= d <= 1.2

    def test_jitter_mean_is_unchanged(self) -> None:
        """The mean of 10000 `_apply_jitter(1.0)` calls
        is within 5% of 1.0 (the canonical
        "jitter doesn't change the expected backoff"
        property)."""
        samples = [_apply_jitter(1.0) for _ in range(10000)]
        mean = sum(samples) / len(samples)
        assert 0.95 <= mean <= 1.05
```

## Test plan

1. **3 new hermetic tests** in
   `libs/gw2_api_client/tests/test_client.py` cover
   the 3 Retry-After paths (present + valid, missing,
   malformed).
2. **2 new jitter tests** cover the bounded-jitter
   property + the mean-unchanged property.
3. **All existing tests pass** — the change is
   backwards-compatible for any 429 without
   `Retry-After` (the existing exponential backoff
   is preserved with jitter).
4. **`uv run pytest libs/gw2_api_client/tests/`**
   exits 0.
5. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `_apply_jitter(delay)` function is added with
      the ±20% uniform jitter contract.
- [ ] The 429 handling block respects the
      `Retry-After` header (with a fallback to
      exponential backoff for missing/malformed
      headers).
- [ ] 5 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the new
      `Retry-After` respect + jitter are
      backwards-compatible for any 429 without
      `Retry-After`).

## Out-of-scope / deferred

- **Switching to `tenacity` / `backoff`**: out of
  scope (the hand-rolled retry loop is sufficient;
  a library would add a dep for the same
  behaviour).
- **Adding a circuit breaker**: out of scope (too
  complex for a small library; the canonical
  pattern is for the caller to add a circuit
  breaker on top).
- **Respecting `Retry-After` on 503 Service
  Unavailable**: out of scope (the current 503
  handling raises `GuildWars2HttpError`
  immediately; a future plan can add
  503-with-Retry-After retry support).
- **Parsing HTTP-date format for `Retry-After`**: out
  of scope (the GW2 v2 API uses seconds-only;
  HTTP-date parsing would be over-engineered).

## Maintenance notes

- **The `_apply_jitter` function uses
  `random.uniform`** (not `secrets.uniform`). The
  jitter is not security-sensitive; a cryptographic
  PRNG is unnecessary.
- **The jitter is applied to BOTH
  `Retry-After`-derived and exponential-fallback
  delays**. The 20% jitter bound is the canonical
  default per AWS architecture guidance
  ("Exponential Backoff And Jitter"); a future
  plan can add a `--jitter-fraction` constructor
  parameter for callers that want a different
  bound.
- **The `Retry-After` header is parsed via
  `float()`**. A malformed value (e.g.
  `Retry-After: tomorrow`) raises `ValueError`;
  the function falls back to the exponential
  backoff. A future hardening pass can add a
  warning log for malformed headers.
- **The 3-attempt retry budget is preserved**. A
  server-specified `Retry-After` of 30s + 3
  attempts means the client could wait 30s + 30s
  + 30s = 90s in the worst case. This is the
  canonical pattern; the caller can shorten the
  budget by wrapping their own policy layer.
