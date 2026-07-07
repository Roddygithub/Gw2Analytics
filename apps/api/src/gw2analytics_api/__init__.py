"""FastAPI gateway for GW2Analytics.

This package is a **thin** HTTP layer: it serializes :mod:`gw2_core`
models in and out. No business logic lives here.
"""

from __future__ import annotations

from gw2analytics_api.main import app

__version__ = "0.8.6"

__all__ = ["__version__", "app"]
