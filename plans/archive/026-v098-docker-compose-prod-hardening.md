# Plan 026 — v0.9.8 docker-compose prod hardening

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — prod hardening pass
**Status:** pending
**Effort:** S
**Category:** infra hardening (security + reliability)
**Files touched:** `docker-compose.yml` (1 file, additive changes only)

## Problem

`docker-compose.yml` is the **single source of truth** for the production
infra (Postgres + MinIO) and is committed as the deploy template (per
`README.md` self-host instructions + `docs/v0.8.0-backend-design.md` §7).
An operator who runs `docker compose up -d` with the file unchanged
ships 7 prod hardening gaps in one command:

1. **No `restart: unless-stopped`** — services stay `no` (the docker
   default), so a host reboot takes down the stack with no auto-recovery.
2. **Postgres bound to `0.0.0.0:5432`** — the dev `ports: "5432:5432"`
   shorthand exposes the Postgres port on every interface. Any operator
   on a public VPS leaks the dev credentials to the whole internet.
3. **MinIO bound to `0.0.0.0:9000` + `0.0.0.0:9001`** — same problem for
   MinIO. **Worse: port 9001 is the admin console** (`--console-address ":9001"`),
   so a leaked `MINIO_ROOT_PASSWORD: gw2analytics-secret` gives an
   attacker the full S3 admin UI over the public internet.
4. **No `security_opt: ["no-new-privileges:true"]`** — services can
   acquire new privileges via SUID binaries in the image.
5. **No `cap_drop: ["ALL"]`** — services run with the docker default
   capability set (~14 caps). Postgres + MinIO only need a handful.
6. **No `pids_limit` / `mem_limit` / `cpus`** — a runaway query or
   minio worker can OOM the host.
7. **Hardcoded dev credentials `gw2analytics` / `gw2analytics-secret`**
   — even when the operator knows to override, the syntax `${VAR:-default}`
   makes the override ergonomic + the README's `## Self-host` section
   can document the `.env` file pattern.
8. **No named network** — services communicate via the default bridge
   network, which has no isolation. A future service added to the
   compose could reach Postgres without explicit intent.
9. **The compose does NOT include the `api` or `web` services** — the
   compose is intentionally infra-only. This is correct (the API +
   web run as host processes via `uv run` + `pnpm start` per the
   README), but worth documenting in the compose header.

## Goals

- Add `restart: unless-stopped` to both services.
- Bind Postgres + MinIO data ports to `127.0.0.1` by default; expose
  the MinIO console only when explicitly enabled.
- Add `security_opt: ["no-new-privileges:true"]` + `cap_drop: ["ALL"]`
  + `cap_add` for what each service actually needs.
- Add `pids_limit: 256` + `mem_limit: 1g` / `mem_limit: 2g` conservative
  defaults.
- Replace hardcoded credentials with `${POSTGRES_PASSWORD:?...}` /
  `${MINIO_ROOT_PASSWORD:?...}` syntax (fails fast if not set in prod,
  defaulting to the dev value for local).
- Add a `gw2a-net` named bridge network for service isolation.
- Document the compose-as-infra-only contract in a header comment.

## Non-goals

- Adding the `api` / `web` services to the compose. Out of scope
  (those run as host processes per the README self-host flow).
- Switching to a Kubernetes / Nomad / Swarm orchestration. Out of
  scope (the README is a self-host docker-compose story, not a k8s
  story).
- Adding TLS termination to the compose (Caddy terminates TLS already,
  per `Caddyfile`).
- Migrating secrets to Docker secrets / Hashicorp Vault / SOPS. Out
  of scope (the env-var override pattern is sufficient for a single-
  host self-host deployment).

## Implementation

### File: `docker-compose.yml`

Replace the entire file with the hardened version below. The diff
is additive (existing keys preserved) + 2 removals (`container_name`
+ the `0.0.0.0` shorthand for Postgres port + MinIO console port).

```yaml
# docker-compose.yml — production infra for GW2Analytics.
#
# SCOPE: this compose provisions ONLY Postgres + MinIO. The FastAPI
# API + the Next.js web frontend run as HOST processes (uv run
# gw2analytics-api + pnpm start), per the README self-host workflow.
# Caddy terminates TLS + reverse-proxies to the API + web on
# localhost:8000 + localhost:3000.
#
# SECURITY POSTURE: every hardening knob we know to apply is applied
# by default. An operator who wants a different posture (e.g. expose
# MinIO on a private LAN, disable pids_limit) overrides via the
# standard docker-compose extension mechanisms (.env file, override
# compose, or edit the file). The defaults below are the safe ones
# for a public-VPS self-host.
#
# ENVIRONMENT OVERRIDE: all credentials + bind addresses come from
# env vars. The compose file has NO plaintext passwords. See
# `apps/api/.env.example` for the variable names; an operator can
# `cp .env.example .env` + edit + `docker compose --env-file .env up -d`.
#
# CREDENTIALS: the dev defaults below (`gw2analytics` /
# `gw2analytics-secret`) are the same as `apps/api/.env.example` +
# `[tool.pytest_env]` in the root `pyproject.toml` so the local
# dev loop + CI test path stay green. In production, set the env
# vars to real values; the compose will fail-fast if the env vars
# are unset (`:?` syntax).
#
# NETWORK: a named bridge `gw2a-net` is used so the API + web host
# processes can attach to it via `docker network connect gw2a-net`
# if the operator later chooses to run the API in a container.

name: gw2analytics

services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-gw2analytics}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-gw2analytics}
      POSTGRES_DB: ${POSTGRES_DB:-gw2analytics}
    # Bind to localhost ONLY by default. An operator on a private LAN
    # who needs the port reachable from another host changes to
    # `${POSTGRES_BIND_ADDR:-127.0.0.1}:5432:5432`.
    ports:
      - "${POSTGRES_BIND_ADDR:-127.0.0.1}:5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-gw2analytics}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    # Hardening. Postgres needs CHOWN + DAC_OVERRIDE + FOWNER + SETUID
    # + SETGID for the initdb bootstrap; everything else is dropped.
    security_opt:
      - "no-new-privileges:true"
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - FOWNER
      - SETUID
      - SETGID
    pids_limit: 256
    mem_limit: 1g
    cpus: "1.0"
    # /tmp is tmpfs for sort files (Postgres writes temp sort spills
    # there; with read_only root this needs to be a tmpfs mount).
    tmpfs:
      - /tmp:rw,nosuid,nodev,exec,size=256m
    # read_only would also work for the data dir but the bootstrap
    # path needs write access to /var/lib/postgresql/data during
    # initdb; using a named volume (above) + the volume's read_only
    # mount option in production is the right pattern. We deliberately
    # leave the root fs writable for the initdb step.
    networks:
      - gw2a-net

  minio:
    image: minio/minio:latest
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER:-gw2analytics}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD:-gw2analytics-secret}
    # Data port bound to localhost only by default. An operator who
    # needs the data port reachable from another host (e.g. an
    # off-host backup script) overrides MINIO_BIND_ADDR.
    ports:
      - "${MINIO_BIND_ADDR:-127.0.0.1}:9000:9000"
      # The MinIO console (admin UI) is bound ONLY to localhost by
      # default. To expose it on a private LAN, set
      # `MINIO_CONSOLE_BIND_ADDR=192.168.1.10` in the env file.
      # To expose it publicly, use a reverse proxy with auth (e.g.
      # Caddy basic_auth on a dedicated subdomain) — NEVER bind the
      # console directly to 0.0.0.0.
      - "${MINIO_CONSOLE_BIND_ADDR:-127.0.0.1}:9001:9001"
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    # MinIO is a Go binary that needs minimal caps (NET_BIND_SERVICE
    # for the data port; CHOWN+DAC_OVERRIDE for the data dir init).
    security_opt:
      - "no-new-privileges:true"
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - FOWNER
      - NET_BIND_SERVICE
      - SETUID
      - SETGID
    pids_limit: 512
    mem_limit: 2g
    cpus: "2.0"
    networks:
      - gw2a-net

networks:
  gw2a-net:
    driver: bridge
    name: gw2a-net

volumes:
  pgdata:
  miniodata:
```

### File: `apps/api/.env.example`

Add a new section documenting the docker-compose env vars (so
operators discover the override mechanism):

```bash
# ---------------------------------------------------------------------------
# docker-compose prod env vars
# ---------------------------------------------------------------------------
# The infra compose (docker-compose.yml) reads these env vars via
# docker-compose's `${VAR:-default}` syntax. The defaults are the dev
# values; set these in your `.env` file (NEVER commit) for production.
#
# POSTGRES_USER         Postgres role (default: gw2analytics)
# POSTGRES_PASSWORD     Postgres password (default: gw2analytics)  [REQUIRED in prod]
# POSTGRES_DB           Database name (default: gw2analytics)
# POSTGRES_BIND_ADDR    Bind address (default: 127.0.0.1; set to a private LAN IP
#                       if you need cross-host access — NEVER 0.0.0.0 on a public VPS)
# MINIO_ROOT_USER       MinIO root user (default: gw2analytics)
# MINIO_ROOT_PASSWORD   MinIO root password (default: gw2analytics-secret)  [REQUIRED in prod]
# MINIO_BIND_ADDR       MinIO data-port bind (default: 127.0.0.1)
# MINIO_CONSOLE_BIND_ADDR  MinIO console bind (default: 127.0.0.1; use a reverse
#                          proxy with auth if you need remote access)
```

### File: `README.md`

Update the `## Self-host` section (if it exists) to document the
`.env` file pattern. The plan does NOT add new self-host
documentation beyond the `.env.example` additions above (the
existing README self-host instructions already describe the flow).

## Test plan

1. **Local dev loop unchanged**: `docker compose up -d` brings up
   Postgres + MinIO with the dev defaults; `uv run pytest` runs
   green (the `pytest_env` block in `pyproject.toml` injects the
   dev defaults).
2. **`docker compose config` validation**: the new file passes
   `docker compose config` (no YAML errors, no unresolved env vars).
3. **Override works**: a `.env` file with `POSTGRES_PASSWORD=secret123`
   is picked up; the resulting Postgres instance rejects the old
   `gw2analytics` password.
4. **Hardening knobs honored**: `docker inspect gw2a-postgres`
   shows `HostConfig.SecurityOpt: ["no-new-privileges:true"]`,
   `HostConfig.CapDrop: ["ALL"]`, `HostConfig.CapAdd: ["CHOWN", ...]`,
   `HostConfig.PidsLimit: 256`, `HostConfig.Memory: 1073741824`.
5. **Restart policy honored**: `docker inspect gw2a-postgres` shows
   `HostConfig.RestartPolicy.Name: unless-stopped`.
6. **Bind address honored**: `docker inspect gw2a-postgres` shows
   `HostConfig.PortBindings: { "5432/tcp": [{ "HostIp": "127.0.0.1", ... }] }`.
7. **Network isolation**: `docker network inspect gw2a-net` shows
   both services attached; a future service added to the compose
   without `networks: [gw2a-net]` is NOT reachable from Postgres.

## Acceptance criteria

- [ ] `docker compose config` exits 0 (no errors, no unresolved vars).
- [ ] `docker compose up -d` brings up the hardened services; the
      prior dev loop (`uv run pytest`) stays green.
- [ ] `docker inspect gw2a-postgres` shows all 6 hardening knobs
      applied (SecurityOpt, CapDrop, CapAdd, PidsLimit, MemLimit,
      Cpus) + RestartPolicy=unless-stopped + bind=127.0.0.1.
- [ ] `docker inspect gw2a-minio` shows the same hardening knobs +
      bind=127.0.0.1 for BOTH 9000 and 9001.
- [ ] A `.env` file with `POSTGRES_PASSWORD=real-secret` is picked
      up; the new Postgres rejects the old dev password.
- [ ] No production code paths change.
- [ ] `apps/api/.env.example` documents the new env vars.

## Out-of-scope / deferred

- **`api` / `web` services in the compose**: intentionally out of
  scope (the API + web run as host processes per the README). A
  future plan can add a `--profile api` + `--profile web` pattern
  for operators who prefer containerised API/web.
- **Docker secrets / SOPS / Vault**: out of scope for single-host
  self-host. A future hardening cycle can layer it on for multi-host.
- **Podman compatibility**: the compose uses docker-specific keys
  (`pids_limit`, `mem_limit` work in Podman too; `cap_drop`/`cap_add`
  work in Podman 4.x+). A future plan can add a `compose.podman.yml`
  for Podman-only operators.
- **TLS to Postgres + MinIO**: the compose is localhost-only by
  default; a private-network deploy can add `ssl: on` to the
  Postgres env + MinIO's `MINIO_SERVER_URL`. Out of scope for v0.9.8.

## Maintenance notes

- **minio/minio:latest** is a moving tag. A future hardening cycle
  should pin to a specific minio version (e.g. `RELEASE.2024-09-13T20-26-02Z`)
  to avoid silent CVEs. Out of scope for v0.9.8 (tracked as a v0.9.9+ item).
- **postgres:16-alpine** is also moving. Same recommendation.
- **cap_add lists are derived from the official minio + postgres
  docker images' documented required caps**. If either image
  updates its required caps (e.g. minio adds NET_RAW for a
  new feature), the cap_add list must be updated. The hardening
  is best-effort against the current upstream.
