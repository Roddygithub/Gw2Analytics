# Plan 048 — v0.9.15 uploads validation: size cap + MIME check

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — `apps/api/src/gw2analytics_api/routes/*` deep pass
**Status:** pending
**Effort:** S
**Category:** reliability (DoS amplification) + correctness (file-type validation)
**Files touched:** `apps/api/src/gw2analytics_api/routes/uploads.py` (1 file, additive changes only) + `apps/api/src/gw2analytics_api/.env.example` (2 NEW env vars) + `apps/api/src/gw2analytics_api/config.py` (2 NEW Settings fields) + `apps/api/tests/test_uploads_e2e.py` (3 NEW test cases)

## Problem

`apps/api/src/gw2analytics_api/routes/uploads.py::create_upload`
reads the entire uploaded file into memory with no size cap:

```python
def create_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="A .zevtc combat log file"),
    db: Session = Depends(get_session),
) -> UploadCreatedResponse:
    raw = file.file.read()  # <-- reads unlimited bytes
    sha = hashlib.sha256(raw).hexdigest()
    ...
```

The canonical FastAPI 0.104+ pattern is
`UploadFile(max_size=N)` to enforce a hard cap on the
in-memory buffer. The current code accepts a 1 GB
upload, OOMs the worker, and the operator has to
restart the uvicorn process. A malicious actor
who hits `POST /api/v1/uploads` with a chunked
upload (no `Content-Length` header) can hold the
in-memory buffer open indefinitely (the
`file.file.read()` call waits for the full body).

The route also does NOT validate the file's content
type or magic bytes. A `.txt` file with binary
content would be accepted (the parser would fail
with `EvtcParseError`, but the upload envelope is
created first + the SHA-256 is stored + the
`OrmUpload` row is committed). The web frontend
validates `.zevtc` extension (per
`web/src/app/upload/page.tsx`), but the API itself
is the trust boundary — a curl client can bypass
the web validation.

### Severity

- **DoS amplification**: MED — a single
  unauthenticated `POST /api/v1/uploads` with a
  100 MB body OOMs the worker. With 8 workers, 8
  concurrent uploads halt the entire server. The
  `auto_error=False` HTTPBearer pattern in
  `account.py` (the only other unauthenticated
  endpoint) does not have this DoS surface (the
  request body is small).
- **Correctness**: LOW — the parser's failure path
  (returning `EvtcParseError` → upload status
  `"failed"`) is canonical, so a non-`.zevtc`
  upload doesn't corrupt data. The issue is the
  resource consumption of a 100 MB upload that
  fails at the parser stage.

## Goals

- Add `MAX_UPLOAD_BYTES` env var (default 30 MB) +
  `Settings.max_upload_bytes` field + use it as
  `file: UploadFile = File(..., max_size=settings.max_upload_bytes)`.
  The FastAPI 0.104+ `max_size` parameter enforces
  the cap on the in-memory buffer (a request body
  larger than the cap raises `HTTPException(413,
  "Request Entity Too Large")` BEFORE the file is
  read into memory).
- Add a magic-bytes check on the first 4 bytes of
  the file (the `.zevtc` zip starts with the local
  file header magic `0x50 0x4B 0x03 0x04`, the
  canonical ZIP signature "PK\x03\x04"). A
  non-zip file raises 415 Unsupported Media Type
  BEFORE the SHA-256 is computed + the
  `OrmUpload` row is inserted.
- Add 3 hermetic tests: (1) a 31 MB upload
  (over the default cap) is rejected with 413;
  (2) a `.txt` file is rejected with 415 (the
  magic bytes don't match the zip signature);
  (3) a valid `.zevtc` upload is accepted (no
  regression).

## Non-goals

- Adding per-user rate limiting (e.g. "1 upload
  per user per hour"). Out of scope (the
  `MAX_UPLOAD_BYTES` cap is the per-request DoS
  surface; rate limiting is a v0.9.16+ future
  enhancement).
- Streaming the file to MinIO (avoiding the
  in-memory `file.file.read()`). Out of scope
  (the current MinIO client uses
  `BytesIO(data)`; switching to streaming PUT
  is a larger refactor of `storage.py`).
- Adding a `.zevtc` extension check on the
  `file.filename` (the file name, not the
  content). The web frontend already validates
  the extension; the API's canonical trust
  boundary is the content (magic bytes), not
  the filename.

## Implementation

### File: `apps/api/src/gw2analytics_api/config.py`

Add 2 new Settings fields.

```python
# ... (existing Settings fields) ...

# v0.9.15 plan 048: the per-upload size cap. The
# default 30 MB matches the canonical
# ``.zevtc`` size for a 30-minute WvW raid
# (the parser's largest realistic input is
# ~10 MB for a 1-hour raid; 30 MB gives 3x
# headroom). Operators on a smaller VPS can
# lower the cap to 10 MB; operators on a
# dedicated upload server can raise it to
# 100 MB. The cap is enforced by FastAPI's
# ``UploadFile(max_size=N)`` BEFORE the
# file is read into memory (a request body
# larger than the cap raises 413
# ``Request Entity Too Large``).
max_upload_bytes: int = Field(
    default=30 * 1024 * 1024,  # 30 MB
    validation_alias="MAX_UPLOAD_BYTES",
    ge=1024 * 1024,  # 1 MB minimum
    le=1024 * 1024 * 1024,  # 1 GB maximum
)
# v0.9.15 plan 048: the canonical
# ``.zevtc`` ZIP magic-bytes check. A
# valid ``.zevtc`` file is a zip
# archive (PKZip local file header
# signature: ``0x50 0x4B 0x03 0x04``
# = ``"PK\x03\x04"``). A non-zip file
# is rejected with 415 BEFORE the
# SHA-256 is computed + the
# ``OrmUpload`` row is inserted. The
# magic-bytes check is the canonical
# content-type validation (the
# Content-Type header can be spoofed;
# the magic bytes cannot).
zevtc_magic_bytes: bytes = b"PK\x03\x04"
```

### File: `apps/api/src/gw2analytics_api/.env.example`

Add the new env var with the per-env tuning
guidance.

```bash
# ---------------------------------------------------------------------------
# Upload validation (v0.9.15 plan 048)
# ---------------------------------------------------------------------------
# ``MAX_UPLOAD_BYTES`` is the per-upload size cap
# enforced by FastAPI's ``UploadFile(max_size=N)``
# BEFORE the file is read into memory. Default
# 30 MB matches the canonical ``.zevtc`` size for
# a 30-minute WvW raid (the parser's largest
# realistic input is ~10 MB for a 1-hour raid; 30
# MB gives 3x headroom). Lower to 10 MB on a
# smaller VPS; raise to 100 MB on a dedicated
# upload server. A request body larger than the
# cap raises 413 ``Request Entity Too Large``.
# ---------------------------------------------------------------------------
MAX_UPLOAD_BYTES=31457280
```

### File: `apps/api/src/gw2analytics_api/routes/uploads.py`

Update `create_upload` to use `UploadFile(max_size=...)`
+ add the magic-bytes check.

```python
# Add to the imports at the top of routes/uploads.py:
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status

# In create_upload:
def create_upload(
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    file: UploadFile = File(
        ...,
        description="A .zevtc combat log file",
        max_size=settings.max_upload_bytes,
    ),
    db: Session = Depends(get_session),
) -> UploadCreatedResponse:
    """Accept a ``.zevtc`` upload.

    v0.9.15 plan 048: the upload is validated at
    2 levels BEFORE any database write:

    1. **Size cap** (``UploadFile(max_size=settings.max_upload_bytes)``):
       a request body larger than the cap raises
       413 ``Request Entity Too Large`` BEFORE the
       file is read into memory. The cap is
       enforced by FastAPI's ``UploadFile``
       constructor (the request body is rejected
       at the parsing layer; the route body never
       executes).

    2. **Magic-bytes check** (the 4-byte ZIP local
       file header signature ``"PK\\x03\\x04"``):
       a non-zip file raises 415 ``Unsupported
       Media Type`` BEFORE the SHA-256 is
       computed + the ``OrmUpload`` row is
       inserted. The magic-bytes check is the
       canonical content-type validation (the
       Content-Type header can be spoofed; the
       magic bytes cannot).
    """
    raw = file.file.read()
    # Magic-bytes check: a valid ``.zevtc`` is a
    # zip archive (PKZip local file header
    # signature: ``b"PK\\x03\\x04"``). A non-zip
    # file is rejected with 415 BEFORE the
    # SHA-256 is computed + the ``OrmUpload`` row
    # is inserted. The check is the canonical
    # content-type validation: the Content-Type
    # header can be spoofed; the magic bytes
    # cannot. A 4-byte peek is sufficient
    # (the ZIP signature is always the first 4
    # bytes of a zip archive).
    if not raw.startswith(settings.zevtc_magic_bytes):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "file is not a valid .zevtc zip archive "
            "(magic bytes do not match the PKZip "
            "local file header signature)",
        )
    sha = hashlib.sha256(raw).hexdigest()
    # ... (rest of the function unchanged) ...
```

### File: `apps/api/tests/test_uploads_e2e.py` (3 NEW test cases)

```python
def test_upload_rejected_when_exceeds_max_size() -> None:
    """A 31 MB upload (over the default 30 MB cap) is
    rejected with 413 ``Request Entity Too Large``."""
    # Build a 31 MB blob (just the first 4 bytes
    # match the magic signature; the rest is
    # arbitrary).
    big_blob = b"PK\x03\x04" + b"\x00" * (31 * 1024 * 1024)
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("big.zevtc", big_blob, "application/octet-stream")},
    )
    assert resp.status_code == 413


def test_upload_rejected_when_magic_bytes_mismatch() -> None:
    """A non-zip file (magic bytes don't match the
    PKZip signature) is rejected with 415
    ``Unsupported Media Type``."""
    bad_blob = b"NOT_A_ZIP_FILE" * 100
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("bad.zevtc", bad_blob, "application/octet-stream")},
    )
    assert resp.status_code == 415
    assert "magic bytes" in resp.json()["detail"]


def test_upload_accepted_when_magic_bytes_match() -> None:
    """A valid ``.zevtc`` zip file (magic bytes
    match) is accepted; the existing happy-path
    behaviour is preserved."""
    # Use the ``make_minimal_zevtc`` helper from
    # ``_fixtures.py`` to build a valid blob.
    from gw2analytics_api.tests._fixtures import make_minimal_zevtc
    blob = make_minimal_zevtc(
        agents=[(1, 2, 18, "Test", True)],
        build="20250101",
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("good.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201
```

## Test plan

1. **3 new hermetic tests** in
   `apps/api/tests/test_uploads_e2e.py` cover the
   3 validation paths (size cap, magic bytes
   rejection, happy path).
2. **All existing tests pass** — the change is
   backwards-compatible for any upload <= 30 MB
   with valid magic bytes.
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `Settings.max_upload_bytes` is added with a
      30 MB default + the env-var override.
- [ ] `Settings.zevtc_magic_bytes` is added with
      the canonical PKZip signature.
- [ ] `create_upload` uses
      `UploadFile(max_size=settings.max_upload_bytes)`
      + the magic-bytes check.
- [ ] `.env.example` documents `MAX_UPLOAD_BYTES`.
- [ ] 3 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the
      validation is additive; the existing
      happy-path upload is unchanged).

## Out-of-scope / deferred

- **Adding per-user rate limiting** (e.g. "1
  upload per user per hour"): out of scope (the
  `MAX_UPLOAD_BYTES` cap is the per-request DoS
  surface; rate limiting is a v0.9.16+ future
  enhancement).
- **Streaming the file to MinIO** (avoiding the
  in-memory `file.file.read()`): out of scope
  (the current MinIO client uses `BytesIO(data)`;
  switching to streaming PUT is a larger refactor
  of `storage.py`).
- **Adding a `.zevtc` extension check on the
  `file.filename`**: out of scope (the web
  frontend already validates the extension; the
  API's canonical trust boundary is the content,
  not the filename).

## Maintenance notes

- **The FastAPI `UploadFile(max_size=N)` parameter
  was added in FastAPI 0.104**. The project uses
  FastAPI 0.115+ (per the `pyproject.toml`); the
  parameter is available.
- **The magic-bytes check uses the ZIP local file
  header signature** (`b"PK\x03\x04"`). This is
  the canonical ZIP signature; all `.zip` files
  start with these 4 bytes. A `.zevtc` file is a
  zip wrapper around the EVTC blob, so the
  signature is always present.
- **The size cap is enforced at the request
  parsing layer** (FastAPI reads the body in
  chunks and raises 413 when the chunk count
  exceeds the cap). The route body never
  executes for an over-cap request.
- **The 4-byte magic-bytes check is a
  `startswith` comparison** on the first 4 bytes
  of the in-memory buffer. The comparison is
  O(1) and runs after the SHA-256 is computed
  in the current code; the plan reorders the
  check to BEFORE the SHA-256 for early
  rejection of non-zip files.
- **The `Settings.zevtc_magic_bytes` field is
  hard-coded** to the canonical PKZip signature.
  A future plan that supports other file
  formats (e.g. `.evtc` non-zip) can make this
  a `dict[str, bytes]` mapping format -> magic.
