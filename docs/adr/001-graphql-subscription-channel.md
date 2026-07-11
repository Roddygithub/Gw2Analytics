# ADR 001: GraphQL subscription channel — not planned

**Date:** 2026-07-11

## Context

Multiple documents mention a "GraphQL subscription channel" as a planned feature:
- `docs/v0.8.0-backend-design.md`: "GraphQL subscription channel — out of scope for v0.8.0, target v0.9.0+"
- `docs/ROADMAP.md` §3: Listed as v1.0+ strategic item

## Decision

**GraphQL subscription channel is not planned.**

The webhook system (v0.9.1+) covers push notifications via HMAC-signed HTTP callbacks with retry + DLQ + replay. Any future GraphQL proposal must demonstrate a concrete user requirement that webhooks cannot satisfy.

## Rationale

- Webhooks already cover the push-notification use case with existing infrastructure (DB-backed delivery queue, HMAC integrity, exponential-backoff retry, dead-letter queue, replay endpoint).
- GraphQL subscriptions would require a separate WebSocket infrastructure, persistent connection management, and authentication scoping — all for the same push-notification surface.
- No user or integrator has requested GraphQL subscriptions since the webhook system shipped.
- Adding a GraphQL subscription layer would increase the deployment complexity (WebSocket-aware reverse-proxy, connection state management) without a demonstrated benefit over the existing webhook contract.

## Consequences

- New contributors should not evaluate GraphQL subscriptions until a concrete user requirement emerges that webhooks cannot satisfy.
- The existing docs mentions have been updated to cross-reference this decision.
