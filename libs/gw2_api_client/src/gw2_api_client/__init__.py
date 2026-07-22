"""Typed async wrapper for the official Guild Wars 2 v2 REST API."""

from __future__ import annotations

from gw2_api_client.client import AsyncGuildWars2Client

__version__ = "0.1.0"

__all__ = [
    "AsyncGuildWars2Client",
    "__version__",
]
