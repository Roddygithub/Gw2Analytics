# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `CHANGELOG.md`: this file. Captures the V1.4 stability cycle and the
  P1 parser closure that landed in the same push window.
- `.github/workflows/ci.yml`: a single `lint-and-test` GitHub Actions
  job (Python 3.12 on `ubuntu-latest`) running `uv run ruff check`
  + `uv run ruff format --check` + `uv run mypy libs apps
  --no-incremental` + `uv run pytest --tb=line -q` on every push and
  pull request to `main`. Uses `astral-sh/setup-uv@v3` with
  `enable-cache: true` keyed on `uv.lock`. No GitHub repository
  secrets are required because `pytest-env` (see Changed) injects
  the docker-compose dev credentials at pytest session startup,
  and the Postgres-dependent `test_uploads_e2e.py` self-skips via
  the `db_reachable` fixture when no docker-compose Postgres is
  reachable on the runner.
- `README.md`: a CI status badge under the H1 title pointing at the
  new workflow.
- `libs/gw2_evtc_parser/tests/test_parser.py`: new synthetic unit
  test `test_player_with_empty_char_name_but_valid_account_and_subgroup`
  locking down the WvW arcdps edge case where a player record has an
  empty ``char_name`` but a valid ``account_name`` + ``subgroup``
  (previously only covered by the real-fixture integration test).

### Changed

- `pyproject.toml`: added `pytest-env>=1.6.0` to the dev dependency
  group. `pytest-env` reads the new `[tool.pytest_env]` table and
  injects `DATABASE_URL` + `S3_*` docker-compose dev credentials
  into `os.environ` at pytest session startup, so the test suite
  no longer depends on a hand-rolled `.env` file.
- `apps/api/src/gw2analytics_api/config.py`: credentials are now
  **fully environment-driven** (no hardcoded sentinel defaults).
  Each `minio_*` Python field is mapped to the matching `S3_*` env
  var via `Field(validation_alias="...")`; `database_url` maps to
  `DATABASE_URL`. **Operators must `cp .env.example .env`** before
  running `uv run uvicorn` (or `uv run fastapi dev`); tests are
  insulated by `pytest-env`.
- `pyproject.toml`: removed the now-unnecessary
  `apps/**/config.py = ["S105"]` per-file ruff ignore plus its
  belt-and-suspenders cross-reference comments. `config.py` is
  sentinel-free, so bandit will catch any future regression at PR
  time.
- `pyproject.toml`: bug fix in `[tool.ruff.lint] select`: the
  `"S"` (flake8-bandit) entry was previously collapsed onto the
  `"UP"` comment line and silently dropped from the array. Now
  restored on its own line; `select` is `["E","F","I","B","UP",
  "S","RUF"]` (verified via `tomllib`).
- `apps/api/src/gw2analytics_api/main.py`: added an inline `# type:
  ignore[import-untyped]` on the `fastapi_mcp` import (the
  `[[tool.mypy.overrides]]` block was not always honoured).
- `.pre-commit-config.yaml`: bumped the `ruff-pre-commit` hook from
  `v0.7.0` to `v0.15.2` to match the workspace `ruff>=0.7` resolved
  by `uv` to `ruff 0.15.20`. The eight-minor version gap previously
  caused the `ruff-format` hook to repeatedly re-format files that
  newer ruff had already formatted correctly ("1 file reformatted"
  on every pre-commit run).
- `libs/gw2_evtc_parser/tests/test_parser.py`: previously hoisted a
  parser import from inside a function body to module top
  (`ruff PLC0415`).
- `README.md`: Quickstart step 5 is now `cp .env.example .env`
  (required for the env-driven credentials); subsequent steps
  renumbered.

### Fixed

- See "Changed" above: the `select` array regression, the
  `ruff-pre-commit` version mismatch, the `fastapi_mcp` import
  ignoring the mypy override, and the `config.py` S105 sentinel
  workaround (replaced with an honest env-only contract).

### Security

- No hardcoded credentials remain anywhere in the source tree.

## [0.4.0] - Phase 1 parser landed

### Added

- `libs/gw2_evtc_parser`: a Python `EvtcParser` PartialImpl that
  reads the V1.3 EVTC binary layout: 25-byte header + 96-byte
  agent records + variable-size skill records. The parser is
  strict on agent record boundaries (`EvtcParseError` on
  truncation) and lenient on the skill table (stops early + logs
  a warning when `header.skill_count` exceeds the actual record
  count -- a known arcdps quirk).
- `libs/gw2_evtc_parser/tests/test_parser.py`: 545-line test
  suite covering synthetic minimal fights, header + agent +
  skill edge cases, real-fixture integration, and `.zevtc` zip
  wrapping/unwrapping.
- `libs/gw2_evtc_parser/tests/test_parser.py::test_real_evtc_binary_parses_with_realistic_agent_count`:
  end-to-end real-fixture integration test against
  `/tmp/inner_20251002-213519` (skipped if the fixture is absent).

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/a67e672...HEAD
[0.4.0]: https://github.com/Roddygithub/Gw2Analytics/releases/tag/0.4.0
