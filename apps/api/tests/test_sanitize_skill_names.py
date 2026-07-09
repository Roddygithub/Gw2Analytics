"""v0.10.2 hotfix followup #2: ``_sanitize_name`` strips NUL bytes from names.

Background
==========

PostgreSQL ``TEXT`` / ``VARCHAR`` columns cannot contain the byte
``0x00`` (it's reserved as the C-string terminator in the wire
protocol; the backend rejects the bind with ``psycopg.DataError``).
The arcdps EVTC parser can yield ``Skill.name`` strings with embedded
NUL bytes from malformed skill tables -- the parser's
``MAX_SKILL_NAME_BYTES`` check surfaces the boundary case as a
WARNING and stops reading, but the YIELDED skills before the cut-off
may still contain NULs.

Pre-v0.10.2, an unguarded ``INSERT INTO fight_skills (... name)``
raised ``psycopg.DataError`` and rolled back the entire
``_save_fight`` transaction (CASCADE dropped the fight + agents + skills).
v0.10.2 ships :func:`_sanitize_name` in ``services.py`` and routes
every name-like field (``agent.name``, ``skill.name``,
``account_name``, ``subgroup``) through it before the INSERT.

What this test pins
===================

The pure-function contract of :func:`_sanitize_name`:

1. ``None`` -> ``""`` (coerced, so the ORM can treat it as a NOT NULL field).
2. ``""`` -> ``""`` (empty string round-trips).
3. A normal name -> unchanged.
4. A name with NUL bytes -> NUL bytes stripped.
5. An all-NUL name -> ``""`` (collapses cleanly).
6. Other control characters (tab, newline) -> preserved (the
   sanitizer is intentionally narrow: only NUL is stripped because
   other control chars are sometimes part of legitimate add-on skill
   names).
"""

from __future__ import annotations

import pytest

from gw2analytics_api.services import _sanitize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # None / empty round-trips
        (None, ""),
        ("", ""),
        # Normal name unchanged
        ("Protection", "Protection"),
        ("Bleeding", "Bleeding"),
        # NUL bytes stripped (the hotfix's whole reason for being)
        ("Prot\x00ection", "Protection"),
        ("\x00Bleeding", "Bleeding"),
        ("Bleeding\x00", "Bleeding"),
        ("a\x00b\x00c", "abc"),
        # All-NUL collapses to empty (NOT NULL field accepts empty string)
        ("\x00\x00\x00", ""),
        ("\x00", ""),
        # Other control characters are PRESERVED (intentional policy)
        ("tab\there", "tab\there"),
        ("line\nbreak", "line\nbreak"),
        ("carriage\rreturn", "carriage\rreturn"),
        # Mixed: NUL stripped, other control preserved
        ("a\x00b\tc\x00d", "ab\tcd"),
    ],
)
def test_sanitize_name_strips_nul_bytes(raw: str | None, expected: str) -> None:
    """The sanitizer contract: strip 0x00, preserve other chars, coerce None to empty."""
    assert _sanitize_name(raw) == expected


def test_sanitize_name_returns_str_type() -> None:
    """Static type contract: always returns ``str`` (never ``None``)."""
    assert isinstance(_sanitize_name(None), str)
    assert isinstance(_sanitize_name(""), str)
    assert isinstance(_sanitize_name("hello"), str)
    assert isinstance(_sanitize_name("a\x00b"), str)


def test_sanitize_name_idempotent() -> None:
    """Sanitizing twice == sanitizing once (idempotence for re-parse safety)."""
    once = _sanitize_name("a\x00b\x00c")
    twice = _sanitize_name(once)
    assert once == twice == "abc"
