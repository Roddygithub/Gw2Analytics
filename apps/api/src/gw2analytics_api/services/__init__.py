"""Domain ⇄ ORM translation via repository layer.

Phase 2.2: every module in this package uses repository classes for
all DB access instead of raw SQLAlchemy calls. See the
:mod:`gw2analytics_api.repositories` package for the data-access layer.
"""

from gw2analytics_api.services.event_blob import _persist_event_blob
from gw2analytics_api.services.fight_persistence import MAX_NAME_LEN, _sanitize_name
from gw2analytics_api.services.guild_service import list_guilds_for_account
from gw2analytics_api.services.parse import process_parse
from gw2analytics_api.services.player_profiles import (
    aggregate_player_profiles_cursor,
    aggregate_player_profiles_from_sql,
    find_account_fights_without_summary,
    find_fights_without_summary,
    get_account_contributions_from_sql,
)
from gw2analytics_api.services.player_summaries import (
    _compute_account_roles,
    _persist_player_summaries,
)

__all__ = [
    "MAX_NAME_LEN",
    "_compute_account_roles",
    "_persist_event_blob",
    "_persist_player_summaries",
    "_sanitize_name",
    "aggregate_player_profiles_cursor",
    "aggregate_player_profiles_from_sql",
    "find_account_fights_without_summary",
    "find_fights_without_summary",
    "get_account_contributions_from_sql",
    "list_guilds_for_account",
    "process_parse",
]
