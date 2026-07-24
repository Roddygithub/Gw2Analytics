"""Guild service: list guilds for an account.

Phase 5.2: removed the ``sync_guilds`` stub (dead code — the
gw2_api_client library does not yet expose guild endpoints).

Uses :class:`GuildRepository` for all DB queries.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from gw2analytics_api.models import Guild
from gw2analytics_api.repositories import GuildRepository

logger = logging.getLogger(__name__)


def list_guilds_for_account(db: Session, account_name: str) -> list[Guild]:
    """Return all guilds that the given account is a member of.

    Delegates to :meth:`GuildRepository.find_guilds_for_account`.
    """
    repo = GuildRepository(db)
    return repo.find_guilds_for_account(account_name)
