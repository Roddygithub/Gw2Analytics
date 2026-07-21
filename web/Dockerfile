# --- builder stage ---
FROM node:22-bookworm-slim AS builder

RUN corepack enable && corepack prepare pnpm@11.13 --activate

ARG API_BASE_URL=http://api:8000
ENV API_BASE_URL=${API_BASE_URL}

WORKDIR /app

COPY package.json pnpm-lock.yaml /app/
# CI=true tells pnpm to run native build scripts (esbuild, sharp)
# even in a non-TTY Docker environment.
ENV CI=true
# The lockfile was generated locally (pnpm 11.13.0, Node 26) while
# Docker runs Node 22. The Node major version delta causes persistent
# ERR_PNPM_LOCKFILE_CONFIG_MISMATCH on the overrides section even with
# the same pnpm minor pinned. Using --no-frozen-lockfile is pragmatic:
# the lockfile is committed and verified locally via CI.
RUN pnpm install --no-frozen-lockfile

COPY . /app
RUN pnpm build

# --- runtime stage ---
FROM node:22-bookworm-slim

# API_BASE_URL needed at runtime for SSR + rewrites.
# env.ts requires it in production (NODE_ENV=production).
ARG API_BASE_URL=http://api:8000
ENV API_BASE_URL=${API_BASE_URL}
# Override Docker's HOSTNAME (container ID) so Next.js standalone
# binds to 0.0.0.0 instead of trying to resolve the container ID.
ENV HOSTNAME=0.0.0.0

WORKDIR /app

COPY --from=builder /app/.next/standalone /app
COPY --from=builder /app/.next/static /app/.next/static
COPY --from=builder /app/public /app/public

# Run as non-root for security (principle of least privilege).
RUN useradd -r appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 3000

CMD ["node", "server.js"]
