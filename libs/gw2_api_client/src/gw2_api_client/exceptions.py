"""Typed exceptions for :mod:`gw2_api_client`."""

from __future__ import annotations


class GuildWars2ClientError(Exception):
    """Base class for all client-side GW2 v2 API failures."""


class GuildWars2ApiError(GuildWars2ClientError):
    """A non-2xx response from the v2 API was received.

    Rate-limit (429) and transport errors are included here.
    Check the error message for "rate-limited" to distinguish
    429 exhaustion from other HTTP failures.
    """
