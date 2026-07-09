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

import inspect

import pytest

from gw2analytics_api.services import MAX_NAME_LEN, _sanitize_name


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
        # ---- v0.10.2 hotfix followup #5: String(128) truncation ----
        # The arcdps parser can yield ``name_len`` up to
        # ``MAX_SKILL_NAME_BYTES = 4096`` for skill names (custom
        # add-on skill names); a 200-char skill name would
        # otherwise fail the INSERT with
        # ``value too long for type character varying(128)`` and
        # roll back the whole ``_save_fight`` transaction.
        # The truncation is silent (no warning) and applied AFTER
        # the NUL-strip pass so a name with NULs followed by > 128
        # chars of content is clipped on the surviving (post-strip)
        # string, not on the original (pre-strip) string.
        # Exactly at the limit: round-trips
        ("A" * 128, "A" * 128),
        # 1 over the limit: truncated
        ("A" * 129, "A" * 128),
        # Well over the limit: truncated
        ("A" * 200, "A" * 128),
        # Way over the limit: truncated
        ("A" * 1_000, "A" * 128),
        # NUL + overlong: NUL stripped first, then truncated
        ("A" * 200 + "\x00" + "B" * 200, "A" * 128),
        # All-NUL + overlong: collapses to empty, NOT truncated to "A"*128
        ("\x00" * 200, ""),
        # At-the-limit with embedded NUL: NUL stripped first (length
        # drops to 127), no truncation needed
        ("A" * 100 + "\x00" + "A" * 27, "A" * 127),
        # NUL at the START + overlong: NUL stripped (the leading
        # NUL collapses), the 200 surviving chars are truncated to
        # 128. Pins that ``\x00`` is stripped BEFORE the
        # truncation cap, not after, so a name like
        # ``"\x00" + "A" * 200`` becomes ``"A" * 128`` (NOT
        # ``"" + "A" * 127`` which would be the result of
        # truncating the original 201-char string to 128 BEFORE
        # the NUL strip). This is the "NUL at start + overlong"
        # counterpart to the "NUL in middle + overlong" case
        # above; both pin the post-strip truncation contract.
        ("\x00" + "A" * 200, "A" * 128),
        # NUL at the END + overlong: same as the start-NUL case
        # (symmetric). The 200 surviving chars are truncated.
        ("A" * 200 + "\x00", "A" * 128),
        # Multiple NULs at the start + overlong: all leading NULs
        # collapse, the 200 surviving chars are truncated.
        ("\x00" * 5 + "A" * 200, "A" * 128),
    ],
)
def test_sanitize_name_strips_nul_bytes(raw: str | None, expected: str) -> None:
    """The sanitizer contract: strip 0x00, preserve other chars, coerce None, truncate to 128."""
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


def test_sanitize_name_truncation_is_idempotent() -> None:
    """v0.10.2 hotfix followup #5: a sanitized-then-truncated name is stable under a 2nd pass.

    Mirrors :func:`test_sanitize_name_idempotent` for the new
    128-char truncation: once a name is sanitized + truncated,
    re-applying the helper must yield the same string (the
    truncation is a fixed point, not a one-shot operation). This
    pins the re-parse safety contract: a re-upload of the same
    SHA (which lands on the same ``OrmFight`` row) must produce
    the same ORM rows bit-for-bit. Pre-hotfix, a 200-char skill
    name would have been truncated to 128 chars on the first
    write, then re-truncated on the second write to the same
    128 chars (the helper is stable), so this test pins the
    round-trip contract.
    """
    long_name = "A" * 200
    once = _sanitize_name(long_name)
    twice = _sanitize_name(once)
    assert once == twice == "A" * 128


def test_sanitize_name_default_max_length_is_128() -> None:
    """v0.10.2 hotfix followup #5: the default ``max_length`` matches the String(128) column constraint.

    Pins the contract that the helper's default truncation cap is
    in lockstep with the ORM column constraint. A future schema
    bump that lifts the cap to e.g. ``String(256)`` MUST bump
    ``MAX_NAME_LEN`` in :mod:`gw2analytics_api.services`
    accordingly; this test fires if the cap + the column diverge.
    The two assertions are split (not chained) so a failure
    surfaces a clear message: either the helper default drifted
    OR the constant drifted.
    """
    sig = inspect.signature(_sanitize_name)
    default_value = sig.parameters["max_length"].default
    assert default_value == MAX_NAME_LEN, (
        f"helper default {default_value!r} != MAX_NAME_LEN {MAX_NAME_LEN!r}"
    )
    assert MAX_NAME_LEN == 128, (
        f"MAX_NAME_LEN drifted to {MAX_NAME_LEN}; expected 128 to match the String(128) column"
    )


def test_sanitize_name_custom_max_length() -> None:
    """v0.10.2 hotfix followup #5: callers can override the truncation cap (defense for future schema bumps).

    The ``max_length`` parameter is exposed so a future
    ``String(256)`` migration (or a per-column override for
    e.g. an ``OrmFightEvent.payload`` TEXT column) can use the
    same helper with a different cap. The test pins the
    parameter is wired correctly: 50-char cap yields a 50-char
    output for a 200-char input, AND a 50-char input
    round-trips unchanged.
    """
    assert _sanitize_name("A" * 200, max_length=50) == "A" * 50
    assert _sanitize_name("A" * 50, max_length=50) == "A" * 50
    assert _sanitize_name("A" * 49, max_length=50) == "A" * 49
    # NUL strip happens BEFORE the truncation cap, so a
    # "A"*100 + NUL + "A"*100 input at max_length=50 yields
    # "A"*50 (the post-strip string is "A"*200, truncated to 50).
    assert _sanitize_name("A" * 100 + "\x00" + "A" * 100, max_length=50) == "A" * 50
