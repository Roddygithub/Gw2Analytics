"""Stable internal data model for GW2 WvW analytics.

This package is the SINGLE SOURCE OF TRUTH for battle data shapes.
All other packages (parser, analytics, api, frontend) consume or
produce these models. It MUST NOT import anyone else.
"""

from __future__ import annotations

from gw2_core.models import Fight, GameType, Profession

__version__ = "0.0.1"

__all__ = ["Fight", "GameType", "Profession", "__version__"]
