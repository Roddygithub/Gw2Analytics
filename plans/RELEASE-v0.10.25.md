# v0.10.25 Release Notes -- 2026-07-16

> **Cycle companion docs:**
> - [Cycle release plan -- Tour 7 v0.10.25 (F17 frontend rollout)](./RELEASE-v0.10.25-tour-7-frontend.md)
> - [F17 plan -- Combat Readout UI Rollout](./F17-frontend-rollout.md)
> - [WAVE-8 parser-side plan](./WAVE-8-parser-side.md)

## Headline

WAVE-8 A.4 CBTS_BUFFAPPLY=18 emit path lands + libs/gw2_skills SCAFFOLD landed + upload-size hardening (defense-in-depth at 3 layers + Caddy reverse-proxy) + ruff/canonicalization across all touched files + style-cleanup commit. The site is operationally ready for deployment.

## Included work

### 1. WAVE-8 A.4 parser extension (cycle operator-signed v0.11.0; landed early as pre-cycle land)

- `libs/gw2_core/src/gw2_core/models.py`: `EventType.BUFF_APPLY` + `BuffApplyEvent` Pydantic v2 model + `_EVENT_MAP` wiring (F821 forward-reference safe: class above `_EVENT_MAP`).
- `libs/gw2_core/src/gw2_core/__init__.py`: Public-surface export of `BuffApplyEvent`.
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`: `if is_statechange == 18: yield BuffApplyEvent(...)` BEFORE the generic statechange skip.
- 3 unit tests + 1 integration test + extended `test_real_fixture_dual_channel_emit_contract` per-kind summing.

### 2. libs/gw2_skills SCAFFOLD library (forward-foundation for v0.11.0 WAVE-8 B)

- 5 new files + workspace member registration. NDJSON file intentionally empty (population is WAVE-8 B cycle 2 work).

### 3. Upload-size hardening (defense-in-depth)

- `MAX_UPLOAD_SIZE_BYTES=100 * 1024 * 1024` hard cap at apps/api config layer.
- 3-layer enforcement in `routes/uploads.py` (Content-Length + Starlette file.size + post-read).
- Caddy reverse-proxy body cap mirrors at the edge.

### 4. ruff + mypy + pytest canonicalization

- `mypy.ini` + `pytest.ini` + `pyproject.toml` ruff `extend-exclude` extended for libs/gw2_skills SCAFFOLD integration.

### 5. Style cleanup

- ruff --fix + format + trailing-newline normalization across touched files.

## Acceptance

- ruff check: clean.
- mypy --no-incremental: 0 issues across 73 source files.
- pytest libs: 100% green (WAVE-8 A.4 added 4 tests, total in libs/gw2_evtc_parser = 23).
- Live API reports version `0.10.25`.
- Caddy caps uploads at 100 MiB before the bytes reach the API.

## Not-in-scope (carried over)

- **WAVE-8 B Skills DB catalog population** (the `gw2_skills.ndjson` is empty; the v0.11.0 WAVE-8 B cycle will populate it).
- **Browser-use live UI end-to-end verification** (prior attempt was blocked by a Chrome DevTools `filePath` API parameter issue; a followup commit will retry with an API-upload workaround).
- **schema.d.ts regeneration** (regenerated during WAVE-8 A.4; no further changes for v0.10.25).

## Operator handoff

- Tag: `v0.10.25` (lightweight tag, pushed to origin).
- Branch: `main` (release commits land BEFORE the tag).
- Deployment: `git checkout v0.10.25 && make deploy`.
