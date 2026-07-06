"""Allow `uv run python -m gw2analytics_api` to boot the app.

This module is the standard-library way to expose a CLI entry point
without packaging CLI scripts. Useful in Docker / smoke tests.
"""

from __future__ import annotations

import uvicorn

from gw2analytics_api.main import app


def main() -> None:
    """Run the FastAPI app via uvicorn on 127.0.0.1:8000."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
