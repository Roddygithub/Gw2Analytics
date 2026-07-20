# Script tests

This directory contains standalone tests for the helper scripts in `scripts/`.

## `upload-batch.sh`

`test_upload_batch.py` exercises the batch uploader without needing a real API:

- **Dry-run**: verifies file discovery and the `--dry-run` (or `-n`) output without network calls.
- **Successful upload**: runs the script against a local mock API and checks the summary.
- **Progress resume**: confirms that a `UPLOAD_PROGRESS_FILE` causes already-uploaded files to be skipped on a second run.

### Run

```bash
uv run pytest tests/scripts/test_upload_batch.py -q
```

The tests start a small Python mock API on an ephemeral port, so no external services are required.
