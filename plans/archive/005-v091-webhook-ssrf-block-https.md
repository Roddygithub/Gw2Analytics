# 005-v091-webhook-ssrf-block-https

**Status**: DONE (shipped in v0.9.1 hardening slice)
**Date**: 2026-07-08 (executed as part of H1 + H2 followups)
**Drift-detection base**: `ef5e4f3`
**Addresses finding**: #2 — `_validate_webhook_url` only blocks `http://{private}`; `https://{private}` is wide open → SSRF vector

## Context

`apps/api/src/gw2analytics_api/routes/webhooks.py::_validate_webhook_url` enforces the
SSRF policy for the webhook URL subscribers register. Today it blocks `http://` to
non-loopback hosts only — the `parsed.scheme == "http"` branch — and accepts every
`https://` URL regardless of the resolved IP. An attacker who subscribes a webhook
with `https://10.0.0.1/admin` (RFC1918 internal), `https://169.254.169.254/`
(AWS IMDS), or `https://localhost:6379/` (Redis on the same host) can use this
endpoint as an SSRF vector against internal services. The validator\'s design doc
reference (`docs/v0.8.0-backend-design.md §7.3`) says the policy is
"HTTPS-or-loopback" — the loopback carve-out for `http://` is documented, but the
equivalent carve-out for `https://` was never implemented.

## Files in scope

- `apps/api/src/gw2analytics_api/routes/webhooks.py` (`_validate_webhook_url`)
- `apps/api/src/gw2analytics_api/routes/webhooks.py` (read the imports; add `socket` + `ipaddress` from stdlib if not already imported)
- `apps/api/.env.example` (one new env var documented: `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS`)
- `apps/api/tests/test_webhooks_e2e.py` (add SSRF-block tests)

## Files explicitly out of scope

- `apps/api/src/gw2analytics_api/routes/uploads.py` (separate SSRF concern for source URLs; not in v0.9.1 scope)
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (the validator gate is upstream; the worker follows the policy)

## Steps

1. **Inspect current `_validate_webhook_url` to confirm the wire shape**.
   - Verify command: `sed -n '50,80p' apps/api/src/gw2analytics_api/routes/webhooks.py`
   - Expected: shows the existing http-only loopback block, currently lines ~62-72.

2. **Add private-IP resolution check that applies to BOTH schemes** (the core change).
   - Import `socket` + `ipaddress` from stdlib.
   - Helper inline in `_validate_webhook_url`:
     ```python
     def _resolve_is_hostname_blocked(hostname: str) -> bool:
         """Return True if any resolved IP for `hostname` is private / loopback / link-local / reserved.

         Used to block SSRF against internal networks regardless of scheme.
         Operators running controlled dev environments override via
         GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1.
         """
         try:
             infos = socket.gethostbyname_ex(hostname)
         except socket.gaierror:
             return True  # unresolvable: treat as blocked (fail-closed)
         for info in infos:
             for addr in (str(info) for info in info[2] if info):
                 pass  # see helper below
         ...
     ```
   - For each resolved IPv4/IPv6 address, check `ipaddress.ip_address(addr).is_private or .is_loopback or .is_link_local or .is_reserved`.
   - Reject 422 with detail `"webhook url resolves to a private/loopback/link-local address"` if any matches and the operator-opt-in env is not set.
   - The existing `http` → only-loopback rule is preserved alongside the new universal-IP-block.

3. **Operator opt-in env var**.
   - Add `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS` (default unset = strict).
   - Read once at module import (`os.environ.get("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS")`).
   - Add to `apps/api/.env.example` with a one-line comment about operational risk.

4. **Run ruff + mypy on the touched file**.
   - Verify command: `cd apps/api && uv run ruff check src/gw2analytics_api/routes/webhooks.py && uv run mypy src/gw2analytics_api/routes/webhooks.py`
   - Expected: both clean.

5. **App boots**.
   - Verify command: `cd apps/api && uv run python -c 'from gw2analytics_api.main import app; print(\"OK routes=\", len(app.routes))'`
   - Expected: `OK routes=13`.

## Test plan

- Add tests in `apps/api/tests/test_webhooks_e2e.py` using the existing `_post_sub` helper:
  - `test_post_webhook_rejects_https_private_ip`: monkeypatch `socket.gethostbyname_ex` to return `("10.0.0.1", [], ["10.0.0.1"])`. POST with `url="https://internal.example/"` → assert 422 + new detail string.
  - `test_post_webhook_rejects_https_loopback_redis`: monkeypatch to return `("127.0.0.1", [], ["127.0.0.1"])`. POST with `url="https://localhost:6379/"` → assert 422.
  - `test_post_webhook_rejects_https_aws_imds`: monkeypatch to return `("169.254.169.254", [], ["169.254.169.254"])`. POST → assert 422.
  - `test_post_webhook_accepts_https_public_hostname`: monkeypatch to return `("93.184.216.34", [], ["93.184.216.34"])`. POST → assert 201.
  - `test_post_webhook_accepts_http_loopback_dev`: existing http://localhost behaviour preserved → 201 (regression guard).
- Verify command: `cd apps/api && uv run pytest tests/test_webhooks_e2e.py -k 'rejects_https or accepts_http_loopback' -v`
- Expected: all PASS.

## Maintenance note

This policy is security-critical. Future URL validators (e.g. v0.10 webhook signature
URLs for replay-token-bearing subscriptions, v0.10 self-hosted deploy hooks) MUST run
the same private-IP check. Consider extracting `_resolve_is_hostname_blocked(hostname)` to a small helper module
so future URL validators can reuse without copy-paste. A short list of patterns to flag in review:
- `"127."`, `"10."`, `"172.16."`–`"172.31."`, `"192.168."` IPv4 ranges.
- IPv6 `::1`, `fc00::/7`, `fe80::/10`.

## Escape hatches

- **STOP** if `ipaddress.is_private` is unavailable on Python < 3.10. The minimum Python is documented as 3.11+ (verify in `apps/api/pyproject.toml`); flag any pre-3.10 compat requirement as a separate plan.
- **STOP** if the operator\'s `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS` is needed in dev. Document the operational risk in CHANGELOG `(a public subscriber could exploit if the env is leaked)` and consider requiring an out-of-band confirmation for any production deployments that set the flag.
- **STOP** if `socket.gethostbyname_ex` returns A-record aliases that the IP-block misses. Add a manual CRT-check via `getaddrinfo` with `AI_CANONNAME` and `AF_INET6` if high-risk production traffic is expected.
