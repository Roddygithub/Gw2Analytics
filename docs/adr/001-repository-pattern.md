# ADR 001 — Repository Pattern

- **Status:** Accepted
- **Date:** 2026-07-24
- **Phase:** 2.1

## Context

Routes and services accessed SQLAlchemy directly via raw ``select()`` /
``execute()`` calls, creating tight coupling between business logic
and the ORM. This made unit testing difficult (required a live DB)
and scattered query patterns across the codebase.

## Decision

Introduce a ``repositories/`` package between services and the ORM.
Each aggregate root gets its own repository class:

- ``FightRepository`` — fights, agents, skills
- ``UploadRepository`` — uploads
- ``WebhookRepository`` — subscriptions, deliveries, DLQ
- ``PlayerRepository`` — player summaries, profiles
- ``GuildRepository`` — guilds, members

Repositories expose only domain-meaningful methods (``get_by_*``,
``find_by_*``, ``save``, ``delete``) — never raw SQLAlchemy calls.

## Consequences

- **Positive:** Services can be tested with mocked repositories.
- **Positive:** Query patterns are consolidated, not scattered.
- **Positive:** Easier to add caching or switch ORMs later.
- **Negative:** More boilerplate (one class + ``__init__.py`` export
  per aggregate root).
- **Negative:** Slight indirection — developers must know both the
  repository and the model.

## Related

- ADR 002 — Service Layer
