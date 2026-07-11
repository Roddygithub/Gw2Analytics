# Plan 058 — v0.9.18: `web/scripts/dump_openapi.py` introspection + `web/scripts/screenshots.mjs` `--no-sandbox`

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`web/scripts/dump_openapi.py` (the OpenAPI codegen script),
`web/scripts/screenshots.mjs` (the Playwright screenshot tool).

## Finding (part 1: `_REQUIRED_ENV` hard-coded list)

```python
_REQUIRED_ENV: tuple[str, ...] = (
    "DATABASE_URL",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
)
```

The script's docstring explicitly documents this as a
"manually kept in sync with `Settings`" contract. A new
required field added to `apps/api/src/gw2analytics_api/config.py:Settings`
silently breaks the codegen step (the new field's `os.environ`
read raises `pydantic.ValidationError` at app import time, which
fails the `pnpm generate:api` step in CI).

Recent plans that ADD required fields to `Settings`:
- Plan 040 (db_pool_size, db_max_overflow, db_pool_timeout,
  db_pool_recycle) — all have defaults, no env-var required.
- Plan 041 (SecretStr on database_url, minio_access_key,
  minio_secret_key) — no new env vars.
- Plan 042 (enable_mcp, enable_openapi_docs) — both have
  defaults, no new env vars.

So today's Settings has NO new required fields post-v0.9.1.
But the drift risk is real: a future plan that adds a
required field (e.g., a new `webhook_signing_secret` from a
v0.9.x security hardening) would silently break the
codegen step.

## Fix (part 1)

Replace the hard-coded tuple with `Settings.model_fields`
introspection:

```python
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from gw2analytics_api.config import Settings

_REQUIRED_ENV: tuple[str, ...] = tuple(
    name.upper()
    for name, field in Settings.model_fields.items()
    if isinstance(field, FieldInfo) and field.is_required()
)
```

The introspection reads the `Settings` Pydantic v2 model's
required fields at import time. The `field.is_required()`
check matches Pydantic v2's `Field(...)` (no default) +
fields without a `default=` / `default_factory=`.

The introspection runs AFTER the `os.environ.setdefault` loop
(because the script needs the env vars set BEFORE the Settings
import). The order is:

1. Set the dummy defaults for the CURRENTLY-KNOWN required
   env vars (introspected from Settings on the first run;
   cached for subsequent runs via `functools.lru_cache`).
2. Import the FastAPI app (triggers the Pydantic validation
   that reads the env vars).
3. Write the OpenAPI JSON to stdout.

## Finding (part 2: `chromium.launch` no `--no-sandbox`)

`web/scripts/screenshots.mjs::chromium.launch({ headless: true })`
does not pass `args: ["--no-sandbox"]`. Some CI container
environments (older GitHub Actions runners, Alpine-based
images, certain Kubernetes pod security contexts) require
`--no-sandbox` to run chromium headless. The current CI
(`.github/workflows/ci.yml` + the Playwright Dockerfile) is
configured to avoid the issue, but a local dev or an
alternative CI provider (e.g., GitLab CI, Jenkins) may hit
the "Running as root without --no-sandbox is not supported"
error.

## Fix (part 2)

Add the `args` array to the `chromium.launch` call:

```javascript
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox"],
});
```

`--no-sandbox` is the canonical workaround for running
chromium as root in a container. The trade-off (disabling
the chromium sandbox) is acceptable for the screenshot
script (the script does not visit untrusted URLs; the
mock server serves only the canonical fixture JSON).

## Risks

- **`--no-sandbox` is a security trade-off**: the script
  should be explicit that the `--no-sandbox` is safe for
  the script's workload (mock server + canonical routes
  only, no untrusted input). The script's docstring
  already documents the security model (no external
  network, mock server only); the `--no-sandbox` change
  is consistent.
- **`Settings.model_fields` introspection is Pydantic v2
  API**: stable since Pydantic 2.0 (2023). The plan pins
  Pydantic v2 (no v1 fallback).
- **The introspection changes the order of import**: the
  new code imports `Settings` BEFORE the `os.environ.setdefault`
  loop (because the introspection needs Settings.model_fields).
  But Settings' import triggers the Pydantic validation that
  reads the env vars. To avoid the import-time crash, the
  `os.environ.setdefault` loop must still run BEFORE the
  Settings import. The fix is to do the introspection in
  2 passes:
    - Pass 1: import `Settings` (which will fail if env
      vars are missing — so we set dummy defaults FIRST).
    - Pass 2: call `Settings.model_fields` to compute
      the required env var names.
  But this is circular: pass 1 needs pass 2's output, and
  pass 1 triggers the validation that needs the env vars.
  The canonical solution is to maintain a small static
  list of NEW env vars (since Pydantic 2.0 stable) AND
  defer the Settings import to AFTER the defaults are set.
  The static list is just the env vars that the Settings
  constructor reads, not the model fields.

**Simpler solution**: keep `_REQUIRED_ENV` as a manually-
maintained tuple, but add a CI test that fails if a new
required field is added to `Settings` without updating
the tuple. The test reads `Settings.model_fields` at test
time, computes the expected required env var names, and
compares to the hard-coded tuple. Drift is caught in CI
before the codegen step breaks.

Even simpler: write a script-level assertion that warns
if `Settings.model_fields` has more required fields than
`_REQUIRED_ENV` lists:

```python
_RUNTIME_REQUIRED = tuple(
    name.upper()
    for name, field in Settings.model_fields.items()
    if isinstance(field, FieldInfo) and field.is_required()
)
if set(_RUNTIME_REQUIRED) != set(_REQUIRED_ENV):
    print(
        f"WARNING: _REQUIRED_ENV drift detected. "
        f"Static list: {sorted(_REQUIRED_ENV)}. "
        f"Runtime introspection: {sorted(_RUNTIME_REQUIRED)}. "
        f"Update _REQUIRED_ENV in scripts/dump_openapi.py.",
        file=sys.stderr,
    )
```

This is the canonical "detect drift" pattern: the static
list is the source of truth (the script KNOWS what env
vars to default), the runtime introspection is the safety
net (the script WARNS if the source of truth is stale).

The plan picks the warning approach (not the auto-sync
approach) because the auto-sync would silently change
behaviour when a new required field is added (the script
would self-default the new env var to "ci-dummy" without
operator awareness). The warning forces the operator to
update the static list + the `Settings` model in the same
PR.

## Tests

1. `test_required_env_tuple_matches_settings_required_fields` —
   import the script (via subprocess); assert no drift
   warning was printed to stderr.
2. `test_required_env_warning_on_drift` — monkeypatch
   `Settings.model_fields` to add a fake required field;
   import the script; assert the warning IS printed to
   stderr.
3. `test_no_sandbox_arg_passed_to_chromium` — patch
   `chromium.launch` to capture the args; run the
   screenshot script (via subprocess with a mock baseURL);
   assert the args include `--no-sandbox`.
4. `test_screenshot_script_handles_missing_persist_dir` —
   the `--persist` flag writes to `docs/screenshots/`;
   the directory may not exist; the script's `await
   mkdir(DOCS_DIR, { recursive: true })` handles this.
   Add a regression test that confirms the mkdir runs
   (mock `mkdir` and assert it was called with the
   correct path).

## Rejected alternatives

- **Auto-sync `_REQUIRED_ENV` from `Settings.model_fields`**
  (no warning, no static list): tempting (the script
  becomes self-maintaining). But the operator who adds
  a new required field to `Settings` should also update
  the script's static list (for documentation purposes);
  the auto-sync would silently change behaviour. The
  warning approach is the canonical "detect drift" pattern.
- **Move the `_REQUIRED_ENV` list to a shared
  `apps/api/scripts/_ci_env.py` module**: out of scope.
  The list is a codegen-script concern, not a
  production-runtime concern. A shared module would
  create a false sense of "single source of truth"
  (the runtime Settings and the codegen script have
  different requirements).
- **Use `pydantic-settings` to declare the env vars in
  a shared schema**: out of scope. `pydantic-settings` is
  what `Settings` already uses; the codegen script's
  `_REQUIRED_ENV` is a subset of the schema's required
  fields, maintained manually.
- **Drop the `chromium.launch` `--no-sandbox` change**
  (rely on the operator's CI environment): tempting
  (don't add a security trade-off). But the
  `--no-sandbox` is required for the canonical CI
  environments (older GitHub Actions runners, the
  project's own Playwright Docker image). The plan
  ships the change.
- **Use `puppeteer` instead of `playwright`**: out of
  scope. The project standardizes on `playwright`
  (per `web/package.json`'s `@playwright/test` dep);
  the script's choice of `chromium` from
  `@playwright/test` is consistent.
- **Add a `--screenshot-dir=` flag to the script**:
  out of scope. The hard-coded `OUT_DIR` anchors to
  the repo root (per the script's invariant comment);
  an env-var override would break the
  README-discovery invariant.
