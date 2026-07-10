"""Pytest rootdir-discovery file for libs/gw2_core/tests/.

The test data builders (``make_damage_event`` / ``make_healing_event`` /
``make_buff_removal_event`` / ``make_account_info``) live in
:mod:`test_models` and are imported by name from there. This
:mod:`conftest` exists ONLY so pytest's rootdir discovery picks up
``libs/gw2_core/tests`` as a top-level test root (the canonical
fixture-injection surface for any future shared fixtures).
"""

from __future__ import annotations
