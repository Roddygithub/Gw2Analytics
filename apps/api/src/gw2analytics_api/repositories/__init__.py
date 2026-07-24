"""Repository layer: thin wrappers around SQLAlchemy session queries.

Each repository encapsulates all DB access for one aggregate root,
exposing only domain-meaningful methods (``get_by_id``, ``find_by_*``,
``save``, ``delete``) — never raw ``select()`` / ``execute()`` calls.
This lets services (and tests) depend on an abstracted persistence
interface instead of SQLAlchemy internals.

Naming convention
-----------------
- ``get_by_*`` — returns a single ORM instance or ``None``.
- ``find_by_*`` — returns a collection (``list`` or ``set``).
- ``save`` — ``add`` + ``flush`` (caller commits).
- ``delete`` — ``delete`` + ``flush`` (caller commits).
"""

from gw2analytics_api.repositories.fight_repository import FightRepository
from gw2analytics_api.repositories.guild_repository import GuildRepository
from gw2analytics_api.repositories.player_repository import PlayerRepository
from gw2analytics_api.repositories.upload_repository import UploadRepository
from gw2analytics_api.repositories.webhook_repository import WebhookRepository

__all__ = [
    "FightRepository",
    "GuildRepository",
    "PlayerRepository",
    "UploadRepository",
    "WebhookRepository",
]
