"""Guild sync service: fetch guild info + members from the GW2 API.

Uses the ``gw2_api_client`` library to fetch guild data from the official
GW2 v2 REST API.  The current gw2_api_client ships ``account_get`` but
does **not** yet expose guild-specific endpoints; ``sync_guilds`` is
therefore a stub that will be completed once the upstream library adds
``get_guild`` / ``get_guild_members`` support.

Ported from WvW_Analytics ``guild_service.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from gw2analytics_api.models import Guild, GuildMember

logger = logging.getLogger(__name__)


async def sync_guilds(db: Session, api_key: str) -> list[dict[str, Any]]:  # noqa: ARG001
    """Sync guild info + members from the GW2 API for the given API key.

    Returns a list of synced guild dicts with id, name, tag.
    """
    logger.warning(
        "sync_guilds: gw2_api_client does not yet expose guild endpoints - "
        "returning empty list. Implement once get_guild/get_guild_members "
        "are added to gw2_api_client.",
    )
    return []


def list_guilds_for_account(db: Session, account_name: str) -> list[Guild]:
    """Return all guilds that the given account is a member of."""
    return (
        db.query(Guild)
        .join(GuildMember)
        .filter(GuildMember.account_name == account_name)
        .distinct()
        .all()
    )
