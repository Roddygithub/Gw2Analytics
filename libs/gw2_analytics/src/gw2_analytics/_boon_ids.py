"""Shared boon skill-ID set for v0.11.0 damage-aggregator filtering.

The parser emits a ``DamageEvent`` for every EVTC cbtevent record whose
byte-flag pattern does not match any buff-interaction branch, even when
the ``value`` field carries buff metadata (duration in ms) instead of
actual damage.  Boon applies (Might, Aegis, Stability, etc.) go through
the damage path when ``_ev_buff != 0 AND value > 0`` because the
EVTC2025+ guard in the parser prevents the APPLY branch from firing
(it requires ``value == 0`` for EVTC2025+).

Condition skill IDs (Burning=733, Bleeding=735, Torment=42, etc.) are
INTENTIONALLY excluded from this set: their ``value`` field carries
legitimate condition-damage ticks, not buff metadata.

WvW map buffs (e.g. "Gliding Enabled"=40806, "Active Kill Streak!"=22889,
"Siege Deployment Blocked"=14712) are ALSO excluded because their values
overlap with real damage ranges and cannot be distinguished without a
skill-name database. The parser-level ``_DAMAGE_SANITY_CAP`` catches
only the INT32_MAX sentinel cases; values below that threshold leak
through both the parser cap AND this boon filter.

See ``libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py``
``_DAMAGE_SANITY_CAP`` for the related sentinel-value fix.
"""

from typing import Final

BOON_SKILL_IDS: Final[frozenset[int]] = frozenset(
    {
        717,  # Protection
        718,  # Regeneration
        719,  # Swiftness
        725,  # Fury
        726,  # Vigor
        738,  # Vulnerability (condition that doesn't deal direct damage)
        740,  # Might
        743,  # Aegis
        762,  # Determined
        873,  # Resolution
        1122,  # Stability
        1187,  # Quickness
        26980,  # Resistance (arcdps uses 26980, not 868)
        30328,  # Alacrity
        5974,  # Superspeed (arcdps uses 5974, not 875)
        62653,  # Blight (condition without direct damage)
    }
)

__all__ = ["BOON_SKILL_IDS"]
