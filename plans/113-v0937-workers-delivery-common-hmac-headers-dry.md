# Plan 113 (v0.9.37) — `workers/_delivery_common.py` HMAC + headers DRY consolidation

## Files touched
- NEW `apps/api/src/gw2analytics_api/workers/_delivery_common.py` (canonical builder for signed request headers + the 3 shared constants)
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (replace inline `hmac.new(...) + headers dict construction` with `_delivery_common.build_signed_request_headers(...)`)
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (same — replace the parallel inline construction in `_attempt_retry`)

## Findings (audit)

- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py::_dispatch_single` (lines ~125-145) hard-codes:
  ```python
  signature = hmac.new(
      sub.secret.encode("utf-8"),
      body_bytes,
      hashlib.sha256,
  ).hexdigest()
  headers = {
      "Content-Type": "application/json",
      "X-Gw2Analytics-Signature": f"sha256={signature}",
      "X-Gw2Analytics-Delivery": delivery_id,
      "User-Agent": _USER_AGENT,
  }
  ```
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py::_attempt_retry` (lines ~140-160) hard-codes the SAME construction with the SAME shape:
  ```python
  body_bytes = delivery.payload
  signature = hmac.new(
      subscription.secret.encode("utf-8"),
      body_bytes,
      hashlib.sha256,
  ).hexdigest()
  headers = {
      "Content-Type": "application/json",
      "X-Gw2Analytics-Signature": f"sha256={signature}",
      "X-Gw2Analytics-Delivery": delivery.id,
      "User-Agent": _USER_AGENT,
  }
  ```
- The 2 implementations differ ONLY in:
  - `delivery_id` variable: `_dispatch_single` uses the local `delivery_id`; `_attempt_retry` uses `delivery.id` (the existing row's id).
  - `_USER_AGENT` value: `"Gw2Analytics-Webhook/0.9.0"` in dispatch vs `"Gw2Analytics-Webhook/0.9.1"` in scheduler.
  - `_REQUEST_TIMEOUT_S`: identical (`10.0` in both files) — already a duplicated literal but a single value.
- Real-world risk: a new header (e.g. `X-Gw2Analytics-Webhook-Scheme: json`) added to one file is silently missed by the other. The integrator's HMAC verification would see the missing header on some attempts but not others — a debug nightmare.
- The `_USER_AGENT` literal divergence is its OWN bug: an integrator logging the User-Agent for forensics sees `0.9.0` for initial POSTs and `0.9.1` for retries. The historical narrative is "v0.9.1 ships the retry scheduler", so the retry path's User-Agent IS `0.9.1` (correct) — but the initial dispatch's `0.9.0` was never bumped when the v0.9.1 worker was added. The schema's integrator-facing contract is one-version-per-consumer; the v0.9.0/0.9.1 split is a real surface anomaly.
- The HMAC `body_bytes` argument is byte-for-byte identical between initial POST and retry (the 0008 plan enshrined that, and the comment on the retry line explicitly cites "byte-for-byte identical HMAC"). The header dictionary should also be byte-for-byte identical for the integrator's verification to be unambiguous.

## Fix

1. NEW `apps/api/src/gw2analytics_api/workers/_delivery_common.py`:

   ```python
   """Shared constants + builder for the webhook delivery request envelope.

   Both the initial POST (:mod:`webhook_dispatch`) and the retry path
   (:mod:`webhook_scheduler`) build IDENTICAL canonical request headers.
   This module is the canonical source -- the dispatch + scheduler
   import from here. Touching this module is required for any new
   canonical header (e.g. ``X-Gw2Analytics-Webhook-Scheme``).

   The integrator-facing contract (the wire shape of every webhook
   POST + retry): HMAC-SHA-256 over ``body_bytes`` with ``secret``
   as the key, hex digest, prefixed with ``sha256=`` in the
   ``X-Gw2Analytics-Signature`` header. The header set:

   - ``Content-Type: application/json``
   - ``X-Gw2Analytics-Signature: sha256=<digest>``
   - ``X-Gw2Analytics-Delivery: dly_<uuid>``
   - ``User-Agent: Gw2Analytics-Webhook/<version>``

   :::note
   The ``User-Agent`` version string is bumped ONCE across the
   workspace when a breaking-version release ships. Today the
   version is a workspace-level constant (the v0.9.x release
   that introduced the retry surface).
   :::
   """
   from __future__ import annotations

   import hashlib
   import hmac
   from typing import Final

   # ---------------------------------------------------------------------
   # Workspace-level request-envelope constants.
   # ---------------------------------------------------------------------

   # Per design doc §5: 10s timeout per outbound POST. Used by BOTH
   # ``webhook_dispatch.AsyncClient`` and ``webhook_scheduler.AsyncClient``.
   REQUEST_TIMEOUT_S: Final[float] = 10.0

   # Canonical User-Agent prefix. The v0.9.x release bumped the value
   # to a single string (no version-splits across initial vs retry);
   # the historical divergence ("0.9.0" for initial, "0.9.1" for
   # retry) was a bug-class surface per plan 113 v0.9.37.
   USER_AGENT: Final[str] = "Gw2Analytics-Webhook/0.9.2"

   # ---------------------------------------------------------------------
   # Builder
   # ---------------------------------------------------------------------


   def build_signed_request_headers(
       secret: str,
       body_bytes: bytes,
       delivery_id: str,
   ) -> dict[str, str]:
       """Return the canonical signed-request headers for one delivery.

       - ``secret``: the webhook subscription's shared secret
         (``OrmWebhookSubscription.secret``). HMAC-SHA-256 with the
         secret as the key.
       - ``body_bytes``: the canonical outbound body bytes. The
         caller is responsible for byte-for-byte integrity
         (post-plan-009 the body is a JSON string with
         ``separators=(",", ":")`` encoded as UTF-8).
       - ``delivery_id``: the ``dly_<uuid>`` discriminator on the
         integration side per design doc §3.4.

       Returns
       -------
       A ``dict[str, str]`` mapping canonical header name -> value.
       Suitable as the ``headers=`` kwarg of
       :meth:`httpx.Client.post` (cross-key string-only —
       ``httpx`` requires the kwarg to be a ``dict[str, str]``).

       Invariants (enforced by tests):
       - ``Content-Type`` is always ``application/json``.
       - ``X-Gw2Analytics-Signature`` is always ``sha256=<digest>``
         with a 64-char lowercase hex digest.
       - ``X-Gw2Analytics-Delivery`` matches the ``delivery_id``
         argument byte-for-byte.
       - ``User-Agent`` matches the canonical constant.
       """
       signature = hmac.new(
           secret.encode("utf-8"),
           body_bytes,
           hashlib.sha256,
       ).hexdigest()
       return {
           "Content-Type": "application/json",
           "X-Gw2Analytics-Signature": f"sha256={signature}",
           "X-Gw2Analytics-Delivery": delivery_id,
           "User-Agent": USER_AGENT,
       }
   ```

2. `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`:

   - Remove the module-level `_USER_AGENT = "Gw2Analytics-Webhook/0.9.0"`.
   - In `_dispatch_single`, replace the inline `hmac.new(...) + headers = {...}` block with a single function call:

     ```python
     from gw2analytics_api.workers._delivery_common import (
         REQUEST_TIMEOUT_S,
         build_signed_request_headers,
     )

     # ... inside _dispatch_single, after the `delivery_id = _generate_delivery_id()` line:
     headers = build_signed_request_headers(
         secret=sub.secret,
         body_bytes=body_bytes,
         delivery_id=delivery_id,
     )
     ```

   - The `httpx.Client(timeout=...)` constructor at the top of `dispatch_for_upload` is updated to use the shared `REQUEST_TIMEOUT_S` constant.

3. `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py`:

   - Remove the module-level `_USER_AGENT = "Gw2Analytics-Webhook/0.9.1"` + `_REQUEST_TIMEOUT_S = 10.0`.
   - In `_attempt_retry`, replace the inline `hmac.new(...) + headers = {...}` block with a single function call:

     ```python
     from gw2analytics_api.workers._delivery_common import (
         REQUEST_TIMEOUT_S,
         build_signed_request_headers,
     )

     # ... inside _attempt_retry, after the `body_bytes = delivery.payload` line:
     headers = build_signed_request_headers(
         secret=subscription.secret,
         body_bytes=body_bytes,
         delivery_id=delivery.id,
     )
     ```

   - The `httpx.Client(timeout=...)` constructor at the top of `process_scheduled_retries` is updated to use the shared `REQUEST_TIMEOUT_S` constant.

## Tests (5, NEW file `apps/api/tests/workers/test_delivery_common.py`)

- `test_build_signed_request_headers_emits_canonical_headers` — invoke with a known `secret=whsec_test1234`, a fixed `body_bytes=b'{"foo":"bar"}'`, a known `delivery_id='dly_xxx'`; assert ALL 4 canonical header names are present with the expected values (regex on the HMAC digest; literal match on the constants).
- `test_signature_is_lowercase_hex_sha256_of_body_with_secret_key` — independent HMAC computation in the test (the test computes sha256(secret, body) and asserts the canonical builder produced the same digest).
- `test_different_secrets_produce_different_signatures_for_same_body` — same `body_bytes` + 2 different `secret` strings → 2 different `X-Gw2Analytics-Signature` digests (the HMAC key isolation contract).
- `test_user_agent_is_canonical_across_callers` — `USER_AGENT` constant equals `"Gw2Analytics-Webhook/0.9.2"` and matches the value used in BOTH the dispatch + scheduler modules (read via `inspect.getsource` or a re-export check).
- `test_dispatch_and_scheduler_headers_match_for_same_inputs` — `_dispatch_single`-built headers (via the importer stub) and `_attempt_retry`-built headers are byte-equal for the same `secret` + `body_bytes` + `delivery_id` inputs.

## Rejected alternatives

- **Inline the canonical builder into BOTH files via a shared `_helpers.py` module** — convention drift here would re-create the divergence. The single canonical module is the right pattern. REJECTED.
- **Move the headers to a Pydantic `BaseModel` with `model_dump()`** — overkill for a `dict[str, str]` shape; the integration with `httpx.Client.post(headers=...)` is the right ergonomics. Pydantic is the schema-validation layer; HTTP headers aren't schemas. REJECTED.
- **Keep the `_USER_AGENT` divergence ("initial=0.9.0, retry=0.9.1") as a forensic signal** — the integrator's User-Agent parsing is the canonical contract for version-detection; a divergence is a bug-class surface, not a feature. REJECTED.
- **Hoist `build_signed_request_headers` into `workers/webhook_helpers.py` (NOT `_delivery_common.py`)** — `_` prefix denotes "this is an internal module, not exported via `__all__` or the package's public surface". The prefix is the canonical Python convention for "shared but private". REJECTED.
- **Pass `body_bytes` as a `Read` argument (content streaming) instead of bytes** — `httpx.Client.post(content=body_bytes, headers=...)` is the documented pattern for small JSON payloads. Streaming would complicate the HMAC computation (the signature would have to be computed BEFORE the first byte is sent). REJECTED.

## Dependency graph

- Independent: NEW `_delivery_common.py` + 2 modified worker files. No production schema or route changes.
- Parallel-safe with plans 114 / 115.
- Pattern-aligns with the v0.9.x workspace convention: private (`_` prefix) shared module adjacent to its consumers (cf. `_cache_reset.py` from plan 095 v0.9.31, `_fixtures.py` / `_event_fixtures.py` from plans 110/111 v0.9.36).
- Bumps the canonical User-Agent to the v0.9.2 release (the post-plan-009 byte-canonical webhook surface). Integrator-facing stripe; subsequent v0.9.x series bumps move the version monotonically.
