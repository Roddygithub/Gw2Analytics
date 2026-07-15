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
