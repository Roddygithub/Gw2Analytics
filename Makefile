# Gw2Analytics — root Makefile
#
# The background dev targets (dev-web-bg, dev-api-bg) run their respective
# servers in detached tmux sessions so they survive across:
#   - AI-agent basher timeouts
#   - terminal closure
#   - system sleep / wake
#
# This is the difference between "the dev server is up, I can just refresh"
# and "I have to ask the agent to restart it every time I switch contexts".

.PHONY: help
help: ## Show this help (default)
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------------------
# Background dev servers (survive across basher timeouts)
# ----------------------------------------------------------------------------

.PHONY: dev-web-bg
dev-web-bg: ## Start Next.js dev server in tmux (idempotent)
	@./scripts/dev-web-bg.sh

.PHONY: dev-web-status
dev-web-status: ## Check pnpm dev + :3000 health
	@./scripts/dev-web-bg.sh --status

.PHONY: dev-web-stop
dev-web-stop: ## Kill the pnpm dev tmux session
	@./scripts/dev-web-bg.sh --stop

.PHONY: dev-web-tail
dev-web-tail: ## Tail the pnpm dev log
	@./scripts/dev-web-bg.sh --tail

.PHONY: dev-web-restart
dev-web-restart: ## Recycle pnpm dev (e.g. after .env change)
	@./scripts/dev-web-bg.sh --restart

.PHONY: dev-web-attach
dev-web-attach: ## Attach to the pnpm dev tmux session (Ctrl-b d to detach)
	@./scripts/dev-web-bg.sh --attach

# ----------------------------------------------------------------------------
# API background dev server (uvicorn in tmux)
# ----------------------------------------------------------------------------

.PHONY: dev-api-bg
dev-api-bg: ## Start FastAPI uvicorn + Arq worker dev servers in tmux
	@./scripts/dev-api-bg.sh

.PHONY: dev-api-status
dev-api-status: ## Check uvicorn (API), Arq (worker) + :8000 health
	@./scripts/dev-api-bg.sh --status

.PHONY: dev-api-stop
dev-api-stop: ## Kill the uvicorn and worker tmux sessions
	@./scripts/dev-api-bg.sh --stop

.PHONY: dev-api-tail
dev-api-tail: ## Tail the logs
	@./scripts/dev-api-bg.sh --tail

.PHONY: dev-api-restart
dev-api-restart: ## Recycle uvicorn (e.g. after .env change)
	@./scripts/dev-api-bg.sh --restart

.PHONY: dev-api-attach
dev-api-attach: ## Attach to the uvicorn tmux session (Ctrl-b d to detach)
	@./scripts/dev-api-bg.sh --attach

.PHONY: dev-api-attach-worker
dev-api-attach-worker: ## Attach to the arq worker tmux session (Ctrl-b d to detach)
	@./scripts/dev-api-bg.sh --attach-worker

# ----------------------------------------------------------------------------
# Stack-level operations
# ----------------------------------------------------------------------------

.PHONY: dev-stack-up
dev-stack-up: dev-api-bg dev-web-bg ## Start full dev stack (API + worker + web in tmux)
	@echo
	@echo "=== stack status ==="
	@./scripts/dev-api-bg.sh --status
	@echo
	@./scripts/dev-web-bg.sh --status

.PHONY: dev-stack-down
dev-stack-down: dev-api-stop dev-web-stop ## Stop the full dev stack
	@echo
	@echo "stack down (docker compose services — postgres/minio/redis — still running)."

.PHONY: dev-stack-status
dev-stack-status: ## Show API + web status
	@echo "=== api (FastAPI :8000 + Arq) ==="
	@./scripts/dev-api-bg.sh --status
	@echo
	@echo "=== web (Next.js :3000) ==="
	@./scripts/dev-web-bg.sh --status

# ----------------------------------------------------------------------------
# First-time onboarding (idempotent: re-runnable on partial failures)
# ----------------------------------------------------------------------------

.PHONY: dev-onboard
dev-onboard: ## One-shot first-time setup: tools, .env, docker services + health, deps, migrations, OpenAPI client, git hooks
	@echo "==> [1/7] Pre-flight: required dev tools (uv, pnpm, docker compose)"
	@command -v uv    >/dev/null 2>&1 || { echo >&2 "ERROR: uv not installed. See https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@command -v pnpm  >/dev/null 2>&1 || { echo >&2 "ERROR: pnpm not installed. Run: corepack enable && corepack prepare pnpm@latest --activate"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo >&2 "ERROR: docker not installed."; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo >&2 "ERROR: docker compose plugin missing."; exit 1; }
	@echo "      ok — uv $$(uv --version | awk '{print $$2}'), pnpm $$(pnpm --version), docker $$(docker --version | awk '{print $$3}' | tr -d ,)"
	@echo
	@echo "==> [2/7] Operator .env (idempotent: created only if missing)"
	@if [ ! -f .env ]; then \
	  cp .env.example .env && \
	  echo "      created .env from .env.example (edit SECRET_KEY before any deployment)"; \
	else \
	  echo "      .env already present — leaving untouched"; \
	fi
	@echo
	@echo "==> [3/7] Docker services (postgres + minio + redis) with portable 60s health-wait per service (Pure POSIX date/sleep loop — no GNU timeout dependency, works on macOS without `brew install coreutils`)"
	@docker compose up -d postgres minio redis
	@start=$$(date +%s); \
	  until docker compose exec -T postgres pg_isready -U gw2analytics >/dev/null 2>&1; do \
	    [ $$(($$(date +%s) - start)) -ge 60 ] && { echo >&2 "ERROR: postgres did not become ready in 60s (docker compose logs postgres)"; exit 1; }; \
	    sleep 2; \
	  done
	@start=$$(date +%s); \
	  until curl -fsS http://localhost:9000/minio/health/live >/dev/null 2>&1; do \
	    [ $$(($$(date +%s) - start)) -ge 60 ] && { echo >&2 "ERROR: minio did not become ready in 60s (docker compose logs minio)"; exit 1; }; \
	    sleep 2; \
	  done
	@start=$$(date +%s); \
	  until docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; do \
	    [ $$(($$(date +%s) - start)) -ge 60 ] && { echo >&2 "ERROR: redis did not become ready in 60s"; exit 1; }; \
	    sleep 2; \
	  done
	@echo "      postgres, minio, redis — all healthy"
	@echo
	@echo "==> [4/7] Python deps (uv sync --frozen --all-packages)"
	@uv sync --frozen --all-packages
	@echo
	@echo "==> [5/7] DB migrations (alembic upgrade head)"
	@cd apps/api && uv run alembic upgrade head
	@echo
	@echo "==> [6/7] Web deps + OpenAPI client regeneration"
	@cd web && pnpm install --frozen-lockfile && pnpm generate:api
	@echo
	@echo "==> [7/7] Git hooks (pre-commit + pre-push)"
	@uv run pre-commit install --hook-type pre-commit --hook-type pre-push
	@echo
	@echo "☑ dev-onboard complete."
	@echo "      Next step: \`make dev-stack-up\` to start API + Arq worker + Next.js (in tmux)."

# ----------------------------------------------------------------------------
# CI helpers
# ----------------------------------------------------------------------------

.PHONY: ci-status
ci-status: ## Show the latest GitHub Actions CI run status
	@gh run list --limit 5 2>/dev/null || echo "Install and authenticate the GitHub CLI (gh) to view CI status: https://cli.github.com/"

.PHONY: ci-open
ci-open: ## Open the GitHub Actions CI page in the browser
	@remote=$$(git remote get-url origin 2>/dev/null | sed -E 's/.*github\.com[:\/]([^/]+\/[^/]+)(\.git)?$$/\1/'); \
	if [ -z "$$remote" ]; then \
	  echo "Could not derive GitHub repo from git remote 'origin'."; \
	  exit 1; \
	fi; \
	url="https://github.com/$$remote/actions/workflows/ci.yml"; \
	echo "Opening $$url"; \
	xdg-open "$$url" 2>/dev/null || open "$$url" 2>/dev/null || echo "Open the URL manually in your browser: $$url"
