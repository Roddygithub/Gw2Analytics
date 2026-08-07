"""Whether Elite Insights counts a damage record as a landed hit.

The rule is shared by every counter that says "how many times did this
connect": the damage tables, ``damageTakenCount``, and the against-downed
counters. Keeping one copy matters because the answer is *not* "the record
carries damage" -- a hit fully converted to barrier, or fully mitigated,
lands for zero and still counts.
"""

from __future__ import annotations

from gw2_core import DamageEvent

#: Direct-hit ``cbtresult`` values EI counts as landed. Only used as a
#: fallback for DamageEvents built by hand rather than by the parser
#: (tests, fixtures, synthetic streams), which leave ``connected`` unset.
#: The parser resolves the flag itself because the condition enum was
#: renumbered in 2026-05 and reading it needs the build version. Matches
#: ``parser._DIRECT_HIT_RESULTS``.
DIRECT_HIT_RESULTS = frozenset({0, 1, 2, 8, 10})
DIRECT_ABSORB_RESULT = 6


def landed_hit(event: DamageEvent) -> bool:
    """Whether EI would count this record as a landed hit.

    A condition tick that lands for zero health damage -- fully mitigated,
    or entirely converted to barrier -- still counts, so the magnitude is
    not a usable stand-in for the result byte.
    """
    if event.is_condition:
        return event.connected
    if event.connected:
        return True
    if event.buff_dmg > 0:
        return event.damage > 0
    return event.result in DIRECT_HIT_RESULTS


def absorbed_hit(event: DamageEvent) -> bool:
    """Whether EI books this record under ``invulned``."""
    if event.is_condition:
        return event.absorbed
    return event.absorbed or event.result == DIRECT_ABSORB_RESULT
