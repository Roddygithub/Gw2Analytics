# Gw2Analytics — development notes for automated agents and contributors

Gw2Analytics is a Guild Wars 2 WvW combat-analytics platform: a PostgreSQL-backed
FastAPI backend, an Arq worker, and a Next.js frontend. The detailed contracts and
conventions live in `README.md`, `CONTRIBUTING.md`, `DECISIONS.md` and `docs/`;
this file only records the rules that are easy to get wrong.

## Data and privacy

- `WvW/` links to the maintainer's private combat-log corpus. Never commit,
  upload, publish or otherwise exfiltrate its contents or player identifiers.
  Local analysis for development and tests is allowed; nothing derived from it
  may be checked in.
- Never commit raw `.zevtc` logs or private Elite Insights JSON exports. Only
  anonymized manifests and checksums are versioned (see `scripts/ei-parity/`).

## Running things

- Run all Python tooling through `uv run` (a bare `python` bypasses the workspace
  environment). The workspace pins CPython via `.python-version`.
- Iterate with targeted tests. The full Python suite (`uv run pytest`) enforces
  coverage and needs Docker for the integration/database tests.
- Python lint/type gates: `uv run ruff check`, `uv run ruff format --check`,
  `uv run mypy libs`, `uv run mypy apps/api/src`.
- Web gates (from `web/`): `pnpm exec tsc --noEmit`,
  `pnpm exec vitest run`.

## Architecture rules

- `libs/gw2_core` is the single shared contract and stays I/O-free. The frontend
  consumes the OpenAPI schema, never EVTC structures or ORM models.
- In the API, respect the `routes -> services -> repositories -> ORM` layering:
  repositories never commit, services own transactions.
- Parser/analytics code must not leak implementation-specific raw keys into the
  database, API models or frontend.

## WvW semantics that are easy to get wrong

- Compare each Elite Insights player entry against its own `firstAware`/
  `lastAware` window, not whole-fight totals; one account can have several
  contiguous slices.
- Resolve owners, character swaps and agent IDs over time; a global
  `instance_id -> owner` table produces false attributions.
- Distinguish the arcdps damage channel from the Elite Insights classification
  for condition damage; life-steal effects are not EI conditions.

## Git policy

- Never push directly to `main`; open a PR with a linear history.
- Sign every commit with the DCO trailer `Signed-off-by:`.
- Do not create commits unless the maintainer asked for them.
