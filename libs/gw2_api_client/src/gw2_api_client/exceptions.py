"""Typed exceptions for :mod:`gw2_api_client`.

All client-side failures inherit from :class:`GuildWars2ClientError`
so callers can use a single ``except GuildWars2ClientError`` clause
to catch the entire failure surface. Specific subclasses are
provided for the well-known failure modes (missing config, HTTP
non-success, rate limiting) so callers that want to react differently
to different failure modes can do so.

The exception hierarchy does NOT inherit from httpx's exceptions --
the gw2_api_client surface is supposed to be agnostic of its
underlying transport, so a future swap to aiohttp / urllib3 should
not bleed into the public exception surface.
"""

from __future__ import annotations


class GuildWars2ClientError(Exception):
    """Base class for all client-side GW2 v2 API failures."""


class MissingApiKeyError(GuildWars2ClientError):
    """``GW2_API_KEY`` (or the configured override env var) was not set.

    Raised by :meth:`AsyncGuildWars2Client.from_env` when the env
    var is missing or empty.
    """


class GuildWars2HttpError(GuildWars2ClientError):
    """A non-2xx response from the v2 API was received.

    Separate from :class:`GuildWars2RateLimitError` so callers can
    choose to retry on rate-limit while surfacing other HTTP errors
    (401, 403, 404, 5xx) directly to the user.
    """


class GuildWars2RateLimitError(GuildWars2ClientError):
    """429 was hit and the client's local retry policy was exhausted.

    The client retries up to :data:`AsyncGuildWars2Client._MAX_RATE_LIMIT_RETRIES`
    times before giving up. On exhaustion this exception is raised so
    callers can back off at their own policy layer (e.g. circuit
    breaker, queue depth limit).
    """
