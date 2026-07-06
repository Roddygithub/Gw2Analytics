"""Typed async wrapper for the official Guild Wars 2 v2 REST API.

Exposes:

- :class:`~gw2_api_client.client.GuildWars2Client` -- the Protocol
  both async and (future) sync implementations conform to.
- :class:`~gw2_api_client.client.AsyncGuildWars2Client` -- the
  shipped httpx-backed async implementation with rate-limit retry.
- :class:`~gw2_api_client.exceptions.GuildWars2ClientError` and its
  subclasses -- the typed error surface.

The :mod:`gw2_core` data shapes (:class:`AccountInfo`,
:class:`WorldInfo`, :class:`Population`) live in :mod:`gw2_core`
and are imported by consumers unconditionally.
"""

from __future__ import annotations

from gw2_api_client.client import AsyncGuildWars2Client, GuildWars2Client
from gw2_api_client.exceptions import (
    GuildWars2ClientError,
    GuildWars2HttpError,
    GuildWars2RateLimitError,
    MissingApiKeyError,
)

__version__ = "0.1.0"

__all__ = [
    "AsyncGuildWars2Client",
    "GuildWars2Client",
    "GuildWars2ClientError",
    "GuildWars2HttpError",
    "GuildWars2RateLimitError",
    "MissingApiKeyError",
    "__version__",
]
