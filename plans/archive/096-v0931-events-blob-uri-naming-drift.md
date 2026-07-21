# Plan 096 (v0.9.31) — `events_blob_uri` name-vs-content clarification (no migration)

## Files touched
- `apps/api/src/gw2analytics_api/storage.py` (docstring update on `put_events` + return-value semantics alignment)
- `apps/api/src/gw2analytics_api/models.py` (`OrmFight.events_blob_uri` docstring updated to clarify "URI" is shorthand for "bucket-relative key" — no schema change)
- NEW `apps/api/src/gw2analytics_api/storage.py::build_blob_key` helper (small — same module)
- NEW `apps/api/tests/test_storage_helpers.py` (4 hermetic tests covering the `build_blob_key` helper + the docstring-aligned return values)

## Findings (audit)

- `models.py::OrmFight::events_blob_uri` is named `events_blob_uri` and typed as a 255-char string. The docstring says it's "the location of the per-fight gzipped-JSONL event blob in MinIO".
- `storage.py::put_events(fight_id, gz_data) -> str` RETURNS `f"events/{fight_id}.jsonl.gz"` — a bucket-RELATIVE KEY, NOT a URI. No `s3://` scheme, no bucket prefix.
- `storage.py::get_events(key) -> bytes` reads with `bucket=get_settings().minio_bucket` + the `key` string the caller passes. This path is consistent with the way PUT stored the value: relative key + the bucket is reconstructed at read time from `get_settings().minio_bucket`.
- The consumer-facing function pair works correctly TODAY (PUT writes relative key, GET reads relative key + bucket from settings). But the column NAME "URI" is misleading: a future operator querying the row expects a URI (e.g. `s3://bucket/key`) and gets a relative key. The docstring also doesn't clarify this — it says "the location" which is ambiguous.
- The same naming is reflected in `WebhookDeliveryReplayOut.next_attempt_at` semantics elsewhere; row-level reader code (e.g. ad-hoc SQL queries) that assumes `events_blob_uri` field is directly fetchable against a URI scheme will silently construct wrong URLs.
- The `_ensure_bucket` helper in `storage.py` is paired with the PUT but doesn't validate the bucket is consistent with the column. The minor drift risk: if `S3_BUCKET` env var changes between PUT and GET, GET reads from the NEW bucket but the row's stored `events_blob_uri` is still relative to the OLD bucket → 404. This is a pre-existing migration concern, not a name-vs-content fix, but the name-vs-content fix prevents the operator from making the wrong assumption about what's stored.

## Fix (no migration, docstring + return-value semantics only)

1. `storage.py` — RENAME the function `put_events` to remain `put_events`, but update its return-value semantics and upstream-callers:

   ```python
   def build_blob_key(fight_id: str) -> str:
       """Build the canonical bucket-relative key for a fight's events blob.

       Today this is ``"events/{fight_id}.jsonl.gz"`` -- a
       bucket-RELATIVE key, NOT a URI. The corresponding
       :attr:`OrmFight.events_blob_uri` column is named ``uri`` for
       historical reasons (the design-doc level schema name) but
       STORES a relative key: pair it with
       :func:`gw2analytics_api.config.get_settings().minio_bucket`
       to construct the runtime bucket-projected path. A full
       URI rewrite (``s3://bucket/key``) is deferred to a v0.9.x+
       alembic migration per plan 096 Step 3.
       """
       return f"events/{fight_id}.jsonl.gz"


   def put_events(fight_id: str, gz_data: bytes) -> str:
       """Upload a per-fight gzipped JSONL event blob, returning a
       bucket-RELATIVE KEY (NOT a URI).

       Pair the return value with
       :func:`gw2analytics_api.config.get_settings().minio_bucket`
       to construct the runtime bucket-projected path. The
       :class:`gw2analytics_api.models.OrmFight.events_blob_uri`
       column STORES this relative key directly; the reader
       (:func:`get_events`) pairs it with the configured bucket at
       read time.

       Phase 7 v1 storage contract: ``gz_data`` is the gzip-compressed
       JSONL output of :func:`PythonEvtcParser.parse_events` ``->``
       ``damage_event.model_dump_json()`` per line. ``content_type`` is
       ``application/gzip`` so HTTP fetches can decompress transparently
       via ``Content-Encoding`` if a downstream proxy ever needs to.
       """
       settings = get_settings()
       client = get_minio()
       bucket = settings.minio_bucket
       _ensure_bucket(client, bucket)
       key = build_blob_key(fight_id)
       client.put_object(
           bucket,
           key,
           io.BytesIO(gz_data),
           len(gz_data),
           content_type="application/gzip",
       )
       return key
   ```

2. `models.py::OrmFight::events_blob_uri` — extend the field's docstring comment with the bucket-relative-semantics note:

   ```python
   # Phase 7 v1: location of the per-fight gzipped-JSONL event blob
   # in MinIO. Stored as a bucket-RELATIVE KEY (``"events/{fight_id}.jsonl.gz"``),
   # NOT a URI. Pair with `settings.minio_bucket` to construct the
   # runtime bucket-projected path (see `storage.py::get_events`).
   # The column is named ``events_blob_uri`` for historical alignment
   # with the design-doc schema; the storage layer's
   # `storage.py::build_blob_key` is the canonical builder. Alembic
   # rename to ``events_blob_key`` is deferred to a v0.9.x+ follow-up
   # per plan 096 Step 3.
   events_blob_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
   ```

3. `storage.py::get_events` — extend the docstring with the matching clarification:

   ```python
   def get_events(blob_key: str) -> bytes:
       """Fetch a previously-uploaded events blob by its bucket-relative KEY.

       The ``blob_key`` argument is the bucket-RELATIVE KEY returned by
       :func:`put_events` (NOT a URI). The function pairs ``blob_key``
       with :func:`gw2analytics_api.config.get_settings().minio_bucket``
       to construct the runtime fetch path. This is consistent with
       how :attr:`OrmFight.events_blob_uri` STORES values in the rows
       returned by the parser route.
       """
       client = get_minio()
       bucket = get_settings().minio_bucket
       response = client.get_object(bucket, blob_key)
       try:
           return response.read()
       finally:
           response.close()
           response.release_conn()
   ```

   Note: the parameter RENAME `key -> blob_key` is intentional. It signals intent at the call site — `get_events(events_blob_uri)` is now self-documenting (vs the older `get_events(key)` which read identically to a dict-key access).

4. NO alembic migration. A full rename of the column to `events_blob_key` is REJECTED in this plan (see rejected alternatives) and deferred to a v0.9.x+ follow-up that bundles the entire `events_blob_*` cleanup.

## Tests (4 hermetic, NEW file `apps/api/tests/test_storage_helpers.py`)

- `test_build_blob_key_returns_relative_key_shape` — `build_blob_key("abc-123") == "events/abc-123.jsonl.gz"`. Defensive: catches accidental prefix drift if someone reorders the `f"{fight_id}.jsonl.gz"` interpolation.
- `test_put_events_returns_relative_key_and_uploads_under_bucket` — `monkeypatch` the Minio client, call `put_events("xyz", b"data")`, assert `client.put_object.call_args.kwargs["bucket_name"] == settings.minio_bucket AND client.put_object.call_args.args[1] == "events/xyz.jsonl.gz"` AND the function return value matches the same relative key (`"events/xyz.jsonl.gz"`).
- `test_get_events_paired_with_minio_bucket_for_read` — `monkeypatch` Minio to capture `client.get_object(bucket, key)` args, call `get_events("events/abc.jsonl.gz")`, assert `client.get_object.call_args.args[0] == settings.minio_bucket` AND `client.get_object.call_args.args[1] == "events/abc.jsonl.gz"`. Confirms the read path is bucket-pair + relative-key.
- `test_orm_fight_events_blob_uri_docstring_clarifies_relative_key_semantics` — `inspect.getsource(OrmFight).events_blob_uri` regex finds the literal phrase "bucket-RELATIVE KEY" in the docstring. Defensive grep: catches a future regression where the docstring drift back to ambiguous wording.

## Rejected alternatives

- **Alembic-migration rename `events_blob_uri` -> `events_blob_key`** — invasive (one-shot migration script + backward-compat shim + ORM attribute rename + every route / service / model reference). The minimal fix is the docstring clarification; the migration is a separate v0.9.x+ pass. REJECTED (for this plan; flagged as next-pass follow-up).
- **Rewrite the column to store full s3://bucket/key URIs** — even bigger migration (write path + read path both changed; existing rows need a backfill UPDATE to prepend `s3://{bucket}/`). Operator benefit is high (truly-URI column) but the payload is too big for an audit pass. REJECTED (for this plan; flagged as the preferred v0.9.x+ follow-up).
- **Don't rename the `get_events(key)` parameter** — keeps the parameter name `key` so existing callers (any current consumer that does `get_events(row.events_blob_uri)`) compile unchanged. But the parameter rename is the single biggest signal that "the value is a relative key, not a URI" — leaving it as `key` propagates the docstring burden. REJECTED.
- **Add a `BlobUri` Pydantic v2 type (`s3://bucket/key` validated format) around `events_blob_uri`** — adds a pydantic validation layer on the SQL column; doesn't address the underlying content; complicates the read path. REJECTED.
- **Wrap `events_blob_uri` in a `BlobKey` SQLAlchemy type with `__init__` / `__str__` overrides** — adds a tiny custom type just for naming clarification; equivalent clarity to the docstring at higher code cost. REJECTED.
- **Skip the fix entirely (the docstring is "close enough")** — leaves the source of the footgun in place; a future reader of an `events_blob_uri` value will continue to treat it as a URI. The 3-line docstring + parameter rename is the minimum fix. REJECTED.

## Dependency graph

- Independent: touches `storage.py` + `models.py` only (different field + different function).
- No interaction with plans 095 (`reset_infrastructure_caches`) or 097 (`make_settings`).
- Forward-compat: the docstring + parameter-rename fixes do not block a future alembic column-rename → operators reading `events_blob_uri` today see the new docstring and don't make the bogus "it's a URI" assumption; the future rename to `events_blob_key` becomes a 1-step rename without a content-vs-name bridge period.
