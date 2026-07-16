"""Locust load harness -- HTTP throughput smoke for /api/v1/fights.

Use plain HttpUser (geventhttpclient dep NOT required -- FastHttpUser
would force `pip install locust[geventhttpclient]` as a separate step
in the README which is more friction than warranted for a single
endpoint smoke test).
"""
from __future__ import annotations

from locust import HttpUser, between, task


class BrowseFightsUser(HttpUser):
    """1 user = 1 parallel browse session hitting ``/api/v1/fights``.

    ``wait_time`` between 1-2s emulates a human analyst scrolling
    through the fights grid without saturating the event loop.
    """

    wait_time = between(1, 2)

    @task
    def browse_fights(self) -> None:
        """GET /api/v1/fights -- the canonical read-heavy surface.

        Asserts the response is JSON-decodable (FastAPI returns
        422 for malformed querystrings + 500 for backend tracebacks,
        but a 200 always decodes as JSON via the FastAPI default
        encoder).
        """
        with self.client.get("/api/v1/fights", catch_response=True) as response:
            try:
                response.raise_for_status()
                _ = response.json()
            except Exception as exc:
                response.failure(f"browse_fights: {type(exc).__name__}: {exc}")
