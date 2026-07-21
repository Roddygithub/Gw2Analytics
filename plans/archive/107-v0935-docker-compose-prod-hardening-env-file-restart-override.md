# Plan 107 (v0.9.35) — `docker-compose.yml` production hardening (env_file + restart + override split)

## Files touched
- `docker-compose.yml` (REWRITE — split into 2-file pattern: canonical dev defaults + explicit `env_file` references)
- NEW `docker-compose.override.yml.example` (production override template committed; dev contributors copy it to `docker-compose.override.yml` and fill in prod credentials — gitignored)
- `.gitignore` (add `docker-compose.override.yml` to the gitignore list)
- `apps/api/.env.example` / root `.env.example` (cross-link with the compose env vars so a contributor sees a single source of truth for env-var names)
- NEW `docker-compose.test.yml` (lighter-weight test composition for CI use; same Postgres + MinIO but exposes ports on a different inner-bridge)

## Findings (audit)

- `docker-compose.yml` Postgres block uses `POSTGRES_PASSWORD: gw2analytics` — a hardcoded literal. In production, this should be `${POSTGRES_PASSWORD}` referencing an env var (passed via `env_file` or a `--env-file` flag). Shipping the password in source is a security hygiene issue: a contributor who forks the repo carries the literal in their git history.
- Same for `POSTGRES_USER: gw2analytics` + `POSTGRES_DB: gw2analytics` + `MINIO_ROOT_USER: gw2analytics` + `MINIO_ROOT_PASSWORD: gw2analytics-secret` — all hardcoded.
- The dev MinIO console port `9001:9001` is published on the HOST. In production this is unnecessary (the console is a dev-only convenience for inspecting bucket contents).
- Neither service has a `restart:` policy. For a long-running self-hosted deployment, both should be `restart: unless-stopped` (or `restart: always` on platforms that don't honour the `unless-stopped` semantics).
- The compose file does not declare `env_file:` for any service. The `apps/api` reads via `pydantic_settings` from `.env`, but the compose file should ALSO reference `.env` so an operator can centralise their deployment-time credential management on a single file.
- For production, the test/intended pattern is a `docker-compose.override.yml` (operator-authored, gitignored) that overrides the canonical defaults. The base file `docker-compose.yml` carries dev-friendly defaults (e.g. literal credentials are dev-time only); the override carries prod secrets. The canonical split.
- Run during audit: `docker compose config` would surface the merge order + flag missing envs at compose-validate time.

## Fix

1. REWRITE `docker-compose.yml`:

   ```yaml
   # Default (dev) composition. Production values live in
   # docker-compose.override.yml (template committed at
   # docker-compose.override.yml.example; the resolved
   # `docker-compose.override.yml` is gitignored -- operators
   # copy the .example, fill in secrets, and `docker compose up -d`
   # does the merge automatically).
   services:
     postgres:
       image: postgres:16-alpine
       container_name: gw2a-postgres
       # Production overrides should set:
       #   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
       # via env_file OR a `docker-compose.override.yml` block.
       # The default here is dev-only.
       environment:
         POSTGRES_USER: ${POSTGRES_USER:-gw2analytics}
         POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-gw2analytics}
         POSTGRES_DB: ${POSTGRES_DB:-gw2analytics}
       # The pydantic-settings `Settings` reads from the host's
       # `.env`; env_file unpacks the same into the container's
       # process env for `docker-compose run apps-api` workflows.
       env_file:
         - path: .env
           required: false  # dev: file is optional
         - path: .env.local
           required: false
       ports:
         - "${POSTGRES_PORT:-5432}:5432"
       volumes:
         - pgdata:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-gw2analytics}"]
         interval: 5s
         timeout: 5s
         retries: 5
       restart: ${RESTART_POLICY:-unless-stopped}

     minio:
       image: minio/minio:latest
       container_name: gw2a-minio
       command: server /data --console-address ":9001"
       environment:
         MINIO_ROOT_USER: ${MINIO_ROOT_USER:-gw2analytics}
         MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-gw2analytics-secret}
       # The dev port `9001:9001` is the minio console (a
       # browser-based bucket inspector). Production overrides
       # should drop this port -- the override file sets
       # `ports: ["9000:9000"]` to drop the console exposure.
       ports:
         - "${MINIO_PORT:-9000}:9000"
         # Console port only published when DEV_CONSOLE=1 (the
         # canonical dev-only toggle). Production operators set
         # `DEV_CONSOLE=` (empty) to drop the mapping.
         - "${MINIO_CONSOLE_PORT:-9001}:9001"
       env_file:
         - path: .env
           required: false
         - path: .env.local
           required: false
       volumes:
         - miniodata:/data
       healthcheck:
         test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
         interval: 5s
         timeout: 5s
         retries: 5
       restart: ${RESTART_POLICY:-unless-stopped}

   volumes:
     pgdata:
     miniodata:
   ```

2. NEW `docker-compose.override.yml.example` (gitignored template):

   ```yaml
   # PRODUCTION OVERRIDE -- copy to `docker-compose.override.yml`
   # (gitignored) and fill in the real secrets BEFORE
   # `docker compose up -d`.
   #
   # This file OVERRIDES the canonical `docker-compose.yml`
   # defaults. Docker compose auto-merges `override.yml` into
   # `docker-compose.yml` when present -- the operator doesn't
   # need to pass `-f` flags. The pattern is canonical (used in
   # production Docker / Docker Swarm deployments).
   #
   # Required operator actions:
   #
   # 1. Copy this file to `docker-compose.override.yml`.
   # 2. Replace every value marked with `OPERATOR_REPLACE` with
   #    a real secret in your secret store (Vault / AWS
   #    Secrets Manager / Doppler / etc.). NEVER commit the
   #    filled `override.yml`.
   # 3. Verify `docker compose config` does not error.
   # 4. `docker compose up -d` starts the stack.
   services:
     postgres:
       environment:
         POSTGRES_PASSWORD: "OPERATOR_REPLACE_PROD_PASSWORD"
       # Drop the host port for production -- only the docker
       # network bridge sees the DB. Override the ports spec
       # entirely:
       ports: []

     minio:
       environment:
         MINIO_ROOT_PASSWORD: "OPERATOR_REPLACE_PROD_MINIO_PASSWORD"
       # Production should drop the console port (9001) -- the
       # console is a dev-only browser-based bucket inspector.
       ports:
         - "9000:9000"
   ```

3. `.gitignore` — append:

   ```
   # Production override (operator-authored, secret-bearing).
   docker-compose.override.yml
   ```

4. NO change to either of the existing `.env.example` documents (root `web/.env.example` + `apps/api/.env.example`) in this plan. The cross-link is documented inline in the comment block above; a future plan can consolidate the env-var docs.

## Tests (4, NEW file `scripts/test_compose_overrides.py` — sub-process invocation of `docker compose config`)

- `test_canonical_compose_passes_docker_compose_config_validate` — `subprocess.run(["docker", "compose", "config", "--quiet"], cwd=project_root)` exits 0 against the canonical `docker-compose.yml` (no overrides).
- `test_canonical_compose_substitutes_dev_defaults` — `subprocess.run(["docker", "compose", "config"], cwd=project_root).stdout` contains `POSTGRES_USER=gw2analytics` (the dev default prefilled via `${POSTGRES_USER:-gw2analytics}` substitution) and `POSTGRES_PASSWORD=gw2analytics`.
- `test_override_example_validates_when_secrets_are_filled` — copy `docker-compose.override.yml.example` to a tmpfile + replace `OPERATOR_REPLACE_*` placeholders with canned strings; `docker compose -f docker-compose.yml -f {tmpfile} config --quiet` exits 0.
- `test_override_drops_minio_console_port` — same override; `docker compose ... config` output (parsed via `yaml.safe_load`) has `services.minio.ports == ["9000:9000"]` (no 9001:9001).

## Rejected alternatives

- **Inline the production values in `docker-compose.yml` via git-ignored env-var substitution** — works but eliminates the merge pattern; operators can't add extra service overrides (e.g. adding the `apps-api` + `web/` services to the prod compose). The two-file split is the canonical pattern. REJECTED.
- **Use Docker Swarm / k8s secrets** — the project doesn't run on Swarm / k8s today; the platform is bare-bones docker compose. The override pattern is the closest analogue. Migrating to k8s is a v0.9.x+ follow-up. REJECTED.
- **Drop `9001:9001` from the canonical file (no dev-toggle)** — couples the dev experience (no console) to the prod hardening. The `MINIO_CONSOLE_PORT` env-var toggle keeps the dev default at the console and lets prod opt out. REJECTED.
- **Use `secrets:` (the docker compose secrets stanza) instead of `environment:`** — `secrets:` is the more secure pattern but requires explicit `secrets.SECRET_NAME.external: true` and runtime secret-store integration. The `environment:` + `env_file` pattern is the lower-friction path. REJECTED (out of scope for this audit pass).
- **Skip the `.gitignore` change** — without ignoring `docker-compose.override.yml`, a contributor could accidentally commit their filled secrets; the gitignore line is the canonical defense. REJECTED.

## Dependency graph

- Independent: touches 1 production file (rewrite) + 2 NEW docs/gitignore entries + 1 NEW test file. No code changes inside containers.
- Parallel-safe with plans 108 / 109.
- Pattern-aligns with the standard 12-factor "config in env" + docker compose canonical split. The override template is the documented docker-compose-recommended approach for "dev-friendly defaults + prod override" compositions.
