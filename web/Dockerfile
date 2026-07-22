# --- builder stage ---
FROM node:22-bookworm-slim AS builder

RUN corepack enable && corepack prepare pnpm@10 --activate

ARG API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV API_BASE_URL=${API_BASE_URL}
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /app/
# --mount=type=cache caches the pnpm store across rebuilds, avoiding
# re-downloading unchanged packages from the registry.
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY . /app
RUN pnpm build

# --- runtime stage ---
FROM node:22-bookworm-slim

# API_BASE_URL needed at runtime for SSR + rewrites.
# env.ts requires it in production (NODE_ENV=production).
ARG API_BASE_URL=http://api:8000
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV API_BASE_URL=${API_BASE_URL}
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
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
