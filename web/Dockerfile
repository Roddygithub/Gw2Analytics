# --- builder stage ---
FROM node:22-bookworm-slim AS builder

RUN corepack enable && corepack prepare pnpm@10 --activate

ARG API_BASE_URL=http://api:8000
ENV API_BASE_URL=${API_BASE_URL}

WORKDIR /app

COPY package.json pnpm-lock.yaml /app/
RUN pnpm install --frozen-lockfile

COPY . /app
RUN pnpm build

# --- runtime stage ---
FROM node:22-bookworm-slim

WORKDIR /app

COPY --from=builder /app/.next/standalone /app
COPY --from=builder /app/.next/static /app/.next/static
COPY --from=builder /app/public /app/public

EXPOSE 3000

CMD ["node", "server.js"]
