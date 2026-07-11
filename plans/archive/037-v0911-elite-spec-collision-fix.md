# Plan 037 — v0.9.11 EliteSpec value-collision fix

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — `libs/gw2_core` + `libs/gw2_api_client` deep pass
**Status:** pending
**Effort:** S
**Category:** correctness (data classification)
**Files touched:** `libs/gw2_core/src/gw2_core/models.py` (1 file, additive changes only) + `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` (1 file, 1-line change at the EliteSpec lookup call site) + `libs/gw2_core/tests/test_models.py` (NEW test file)

## Problem

`libs/gw2_core/src/gw2_core/models.py::EliteSpec` has 2
IntEnum value collisions, both acknowledged in the
docstring but unresolved:

```python
class EliteSpec(IntEnum):
    UNKNOWN = 0
    BASE = 0  # No elite spec active
    # ...
    DAREDEVIL = 55       # Thief elite
    SOULBEAST = 55       # Ranger elite; collides with Daredevil pre-2018
    # ...
    RENEGADE = 63        # Revenant elite
    WEAVER = 63          # Elementalist elite; collides with Renegade historically
    # ...
```

Python's `IntEnum` allows duplicate values (each name is a
separate member with its own identity), but the canonical
"construct from int" behaviour is to return the FIRST
defined member with that value. So:

- `EliteSpec(55)` returns `EliteSpec.DAREDEVIL`, even when
  the arcdps byte came from a Ranger playing Soulbeast.
- `EliteSpec(63)` returns `EliteSpec.RENEGADE`, even when
  the arcdps byte came from an Elementalist playing
  Weaver.

The downstream parser currently does:

```python
elite = EliteSpec(agent.elite_raw)
```

…which silently misclassifies Soulbeast players as
Daredevils and Weaver players as Renegades. The
`elite_raw` field is preserved on the `Agent` model for
forensics, but the canonical `EliteSpec` value is wrong.

### Severity

- **Correctness**: MED — misclassification silently
  propagates through the per-account roll-up
  (PlayerProfileAggregator) and the per-fight roll-up
  (TargetDpsRow, SquadRollupRow). An analyst looking at
  the per-fight squad table sees Soulbeast players
  labelled as "Daredevil" (or vice-versa).
- **User trust**: MED — the canonical "what spec did
  this player run?" question returns the wrong answer
  for the 2 collision cases.

### Affected surfaces

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` —
  the parser is the canonical read site of `elite_raw`
  + the canonical write site of `EliteSpec`. The fix
  is at the parser-level lookup call.
- `libs/gw2_analytics` aggregators (transitively
  affected — the `EliteSpec` is exposed via the
  per-account roll-up + the per-fight roll-up).

## Goals

- Add a `disambiguate_elite_spec(raw_value: int, profession: Profession) -> EliteSpec`
  function in `gw2_core.models` that uses the agent's
  profession to pick the right member for the 2
  collision cases.
- Update the parser to use `disambiguate_elite_spec(...)`
  instead of `EliteSpec(...)` at the EliteSpec lookup
  call site.
- Add a module-level
  `_ELITE_SPEC_DISAMBIGUATION: Final[dict[int, dict[Profession, EliteSpec]]]`
  table as the single source of truth for the
  disambiguation rules.
- Add hermetic tests that assert the disambiguation
  for both collision cases + a fallback to the
  first-defined member for non-collision values.

## Non-goals

- Deduplicating the EliteSpec IntEnum values (assigning
  unique integers to Soulbeast + Weaver). The arcdps
  byte values are the source of truth; the Python
  enum values are a Python-language mirror. Changing
  the Python values would break the canonical
  `EliteSpec(int_value)` round-trip for non-collision
  cases.
- Adding a date-based disambiguation (e.g. "pre-2018
  Daredevil, post-2018 Soulbeast"). The arcdps byte
  alone does not carry a timestamp; the build_version
  field is a release date (e.g. `20250925`) but the
  release-date-to-elite-id mapping is undocumented and
  is a future enhancement.
- Adding a new `EliteSpecRaw` enum with unique values
  for the disambiguated cases. The 2-element
  disambiguation table is sufficient for the 2 known
  collision cases; a new enum would be over-engineered.
- Changing the `Agent.elite_raw` field to a
  disambiguated type. The `elite_raw` is the canonical
  raw byte (forensics); the `EliteSpec` is the
  disambiguated enum. Both are useful.

## Implementation

### File: `libs/gw2_core/src/gw2_core/models.py`

Add the disambiguation table + the disambiguation
function. The diff is a new module-level constant + a
new module-level function + an updated docstring.

```python
# ---------------------------------------------------------------------------
# EliteSpec disambiguation table
# ---------------------------------------------------------------------------
# Two EliteSpec IntEnum values collide (same arcdps byte
# shared by 2 different specs at different points in GW2's
# history). The Python ``IntEnum`` constructor returns the
# FIRST defined member with the given value, so without
# disambiguation ``EliteSpec(55)`` returns ``DAREDEVIL``
# even when the agent is a Ranger playing Soulbeast.
#
# The disambiguation table is keyed on the raw byte value
# + the agent's profession. The parser reads both
# (``agent.elite_raw`` + ``agent.profession``) so the
# lookup is well-defined at parse time.
#
# The table is the canonical single source of truth for
# the disambiguation rules. A future collision (e.g. a
# 2027 elite that reuses a retired spec's byte) is added
# here in 2 lines: 1 for the byte key + 1 for the
# profession-to-spec mapping.

_ELITE_SPEC_DISAMBIGUATION: Final[dict[int, dict[Profession, EliteSpec]]] = {
    # byte 55: Thief Daredevil (2015-2018) vs Ranger Soulbeast (2017+)
    55: {
        Profession.RANGER: EliteSpec.SOULBEAST,
        Profession.THIEF: EliteSpec.DAREDEVIL,
    },
    # byte 63: Revenant Renegade (2017+) vs Elementalist Weaver (2018+)
    63: {
        Profession.ELEMENTALIST: EliteSpec.WEAVER,
        Profession.REVENANT: EliteSpec.RENEGADE,
    },
}


def disambiguate_elite_spec(
    raw_value: int, profession: Profession
) -> EliteSpec:
    """Disambiguate a raw arcdps elite byte to the canonical
    :class:`EliteSpec` member.

    Most bytes map unambiguously to one spec; for those,
    the function returns ``EliteSpec(raw_value)`` (the
    Python IntEnum's canonical constructor behaviour).
    For the 2 known collision bytes (55 + 63), the
    function uses the agent's profession to pick the
    right member.

    Parameters
    ----------
    raw_value:
        The raw arcdps byte (4-byte little-endian int from
        the agent table bytes 12-15).
    profession:
        The agent's profession (read from the agent table
        bytes 8-11). Required for the disambiguation
        lookup; falls back to the first-defined member
        when ``profession`` is not in the disambiguation
        table (preserves Python's IntEnum canonical
        behaviour).

    Returns
    -------
    The canonical :class:`EliteSpec` member for the
    given byte + profession. Falls back to
    ``EliteSpec(raw_value)`` (first-defined member) when
    the byte is not in the disambiguation table OR the
    profession is not in the per-byte table.
    """
    table = _ELITE_SPEC_DISAMBIGUATION.get(raw_value)
    if table is not None:
        spec = table.get(profession)
        if spec is not None:
            return spec
    # Fallback: Python IntEnum's canonical behaviour
    # (return the first defined member with the value).
    return EliteSpec(raw_value)
```

Update the `EliteSpec` class docstring to remove the
"NOTE: Some older arcdps revisions write legacy IDs
that no longer match the current catalogue" caveat and
to point to `disambiguate_elite_spec`:

```python
class EliteSpec(IntEnum):
    """Elite specializations.

    Integer values mirror ``arcdps`` bytes 12-15. Values
    are taken from the Elite Insights / GW2 wiki mapping.
    The catalogue is intentionally incomplete -- unknown
    values fall back to :attr:`UNKNOWN` at parse time.

    Disambiguation
    ==============
    Two values collide (see the
    :data:`_ELITE_SPEC_DISAMBIGUATION` table): byte 55 is
    shared by Thief's Daredevil (2015-2018) and Ranger's
    Soulbeast (2017+); byte 63 is shared by Revenant's
    Renegade (2017+) and Elementalist's Weaver (2018+).
    The Python IntEnum constructor returns the first
    defined member with the given value, so a naive
    ``EliteSpec(55)`` returns ``DAREDEVIL`` regardless of
    the agent's profession. The canonical fix is to use
    :func:`disambiguate_elite_spec` at the parser
    read site, which uses the agent's profession to pick
    the right member.

    The ``Agent.elite_raw`` field preserves the raw byte
    for forensics (the operator can see the original
    arcdps byte even after the disambiguation).
    """
```

### File: `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`

Update the parser's EliteSpec lookup call site. The
diff is a 1-line change: replace
`elite = EliteSpec(agent.elite_raw)` with
`elite = disambiguate_elite_spec(agent.elite_raw, agent.profession)`.

```python
# BEFORE:
from gw2_core import Agent, EliteSpec, Profession

# ... in the agent-table parse loop:
elite = EliteSpec(agent.elite_raw)

# AFTER:
from gw2_core import Agent, Profession, disambiguate_elite_spec

# ... in the agent-table parse loop:
elite = disambiguate_elite_spec(agent.elite_raw, agent.profession)
```

### File: `libs/gw2_core/tests/test_models.py` (NEW)

```python
import pytest

from gw2_core import (
    EliteSpec,
    Profession,
    disambiguate_elite_spec,
)


class TestDisambiguateEliteSpec:
    """The disambiguation table + function pin the
    Soulbeast-vs-Daredevil + Weaver-vs-Renegade
    disambiguation contract."""

    def test_daredevil_for_thief_at_byte_55(self) -> None:
        """Byte 55 + Thief profession = Daredevil."""
        assert (
            disambiguate_elite_spec(55, Profession.THIEF)
            == EliteSpec.DAREDEVIL
        )

    def test_soulbeast_for_ranger_at_byte_55(self) -> None:
        """Byte 55 + Ranger profession = Soulbeast."""
        assert (
            disambiguate_elite_spec(55, Profession.RANGER)
            == EliteSpec.SOULBEAST
        )

    def test_renegade_for_revenant_at_byte_63(self) -> None:
        """Byte 63 + Revenant profession = Renegade."""
        assert (
            disambiguate_elite_spec(63, Profession.REVENANT)
            == EliteSpec.RENEGADE
        )

    def test_weaver_for_elementalist_at_byte_63(self) -> None:
        """Byte 63 + Elementalist profession = Weaver."""
        assert (
            disambiguate_elite_spec(63, Profession.ELEMENTALIST)
            == EliteSpec.WEAVER
        )

    def test_non_collision_byte_falls_through(self) -> None:
        """A byte not in the disambiguation table returns
        the first-defined member (Python IntEnum
        canonical behaviour)."""
        # Byte 18 (Berserker) is unambiguous.
        assert (
            disambiguate_elite_spec(18, Profession.WARRIOR)
            == EliteSpec.BERSERKER
        )

    def test_collision_byte_with_unknown_profession_falls_back(
        self,
    ) -> None:
        """A collision byte + UNKNOWN profession falls
        back to the first-defined member (preserves the
        Python IntEnum canonical behaviour for the
        missing-data case)."""
        # Byte 55 + UNKNOWN profession = Daredevil (the
        # first-defined member at byte 55).
        assert (
            disambiguate_elite_spec(55, Profession.UNKNOWN)
            == EliteSpec.DAREDEVIL
        )
```

## Test plan

1. **6 new hermetic tests** in
   `libs/gw2_core/tests/test_models.py` cover the 4
   disambiguated cases + the non-collision fallback +
   the UNKNOWN-profession fallback.
2. **All existing tests pass** — the change is
   backwards-compatible for any non-collision byte
   (the function falls through to the canonical
   IntEnum behaviour).
3. **`uv run pytest libs/gw2_core/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.
5. **`uv run ruff check`** is clean.

## Acceptance criteria

- [ ] `_ELITE_SPEC_DISAMBIGUATION` table is added to
      `libs/gw2_core/src/gw2_core/models.py` with the
      2 known collision cases (55 + 63).
- [ ] `disambiguate_elite_spec(raw_value, profession) -> EliteSpec`
      function is added.
- [ ] The parser's EliteSpec lookup call site is
      updated to use `disambiguate_elite_spec`.
- [ ] 6 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the
      disambiguation is a strict refinement of the
      existing lookup; non-collision bytes are
      unaffected).

## Out-of-scope / deferred

- **Deduplicating the EliteSpec IntEnum values**:
  out of scope (the arcdps byte values are the source
  of truth; the Python enum values are a
  Python-language mirror).
- **Adding a date-based disambiguation** (e.g.
  pre-2018 vs post-2018): out of scope (the arcdps
  byte alone does not carry a timestamp).
- **Adding a new `EliteSpecRaw` enum with unique
  values for the disambiguated cases**: out of scope
  (the 2-element disambiguation table is sufficient
  for the 2 known collision cases).
- **Migrating historical Soulbeast-as-Daredevil rows
  in production**: out of scope (the per-account
  roll-up is regenerated on the next re-parse; a
  future plan can add a one-shot migration to fix
  the existing rows without a re-parse).

## Maintenance notes

- **The `_ELITE_SPEC_DISAMBIGUATION` table is the
  single source of truth for the disambiguation
  rules**. A future collision (e.g. a 2027 elite
  that reuses a retired spec's byte) is added here
  in 2 lines: 1 for the byte key + 1 for the
  profession-to-spec mapping.
- **The `EliteSpec` class retains its duplicate
  values** (e.g. `SOULBEAST = 55` and
  `DAREDEVIL = 55`). The duplicates are intentional
  -- they preserve the arcdps byte values as the
  Python enum values. A naive `EliteSpec(55)` call
  returns the first-defined member, which is the
  intended fallback behaviour for callers that
  don't have the profession available (e.g. raw
  byte logging).
- **The function name is `disambiguate_elite_spec`**
  (verb-led, matching the parser's `parse_events`
  convention). A future helper
  (`lookup_elite_spec` for the raw-byte-only case)
  can be added if needed.
- **The 2-element disambiguation table covers the 2
  known collision cases**. GW2's elite catalogue
  has been stable since 2018; a future collision is
  unlikely but possible (e.g. if a new elite
  reuses a retired spec's byte). The table is
  extensible in 2 lines per new collision.
