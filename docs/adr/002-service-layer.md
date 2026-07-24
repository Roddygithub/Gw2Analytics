# ADR 002 — Service Layer

- **Status:** Accepted
- **Date:** 2026-07-24
- **Phase:** 2.2

## Context

Route handlers in FastAPI contained business logic alongside HTTP
concerns (parameter parsing, response formatting). This made routes
hard to test and forced duplication of logic across endpoints.

## Decision

Extract business logic into a ``services/`` layer that sits between
routes and repositories. Each service module is responsible for one
domain concept:

- ``player_profiles.py`` — cross-fight player aggregation
- ``player_service.py`` — per-account contribution computation
- ``player_summaries.py`` — per-fight summary materialization
- ``fight_persistence.py`` — domain fight → ORM translation
- ``event_blob.py`` — event blob persistence
- ``parse.py`` — EVTC parse orchestration
- ``guild_service.py`` — guild queries

Routes become thin HTTP wrappers: parse params → call service →
format response.

## Consequences

- **Positive:** Routes are ~200 lines instead of ~800.
- **Positive:** Business logic is testable without HTTP.
- **Positive:** Services can be composed for new endpoints.
- **Negative:** Another layer of indirection.

## Related

- ADR 001 — Repository Pattern
- ADR 003 — Boon Normalization
