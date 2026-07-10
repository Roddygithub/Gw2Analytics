"""Statistical role detection from per-fight player totals (v1 lite).

This is the Gw2Analytics-adapted port of the GW2 community's role detection
algorithm (``a non-public reference implementation``). The original
algorithm consumes a ``PlayerStats`` ORM with 80+ fields (DPS, healing
out, barrier out, strips, cleanses, CC, resurrects, 7 boon uptimes,
7 boon out-millisecond metrics, active time, ...). Gw2Analytics's
``OrmFightPlayerSummary`` only tracks the 3 magnitudes
(``total_damage`` / ``total_healing`` / ``total_buff_removal``) so
the full algorithm cannot run 1:1.

The v1 lite port uses ONLY the 3 magnitudes + ``profession`` (int) +
``elite_spec`` (int) + the spec/profession hint tables ported
verbatim from the public GW2 community dataset. The result is a less-precise
classification than the full algorithm -- it cannot distinguish
BOON-only play from DPS-only play (boon uptimes are not tracked) --
but it correctly identifies the 3 dominant archetypes (DPS / HEAL
/ STRIP) plus the MIXED fallback for ambiguous cases.

The algorithm is **pure** (no I/O, no DB round-trips, no logging) so
it composes cleanly into the per-fight ingestion pipeline
(``services.py::_persist_player_summaries``) and is unit-testable
in isolation. The output is ``(detected_role, detected_tags)`` where:

* ``detected_role``: a single string (e.g. ``"DPS"``, ``"HEAL"``,
  ``"STRIP"``, ``"MIXED"``, ``"UNKNOWN"``) -- the **primary** role
  detected from the 3-magnitude ratio. Matches the wire column
  length budget (``String(30)``).
* ``detected_tags``: a list of strings (e.g. ``["high_dps"]``,
  ``["off_meta"]``, ``["foreign_badges:HEAL"]``). Stored as a
  Postgres ``JSON`` column (not ``ARRAY(String)``) so the list
  shape is flexible without an Alembic type change on every
  future tag addition.

The algorithm is **deterministic** (same inputs -> same output)
and **falsifiable** (a 0/0/0 input returns ``("UNKNOWN", [])``
instead of crashing). It is **heuristic, not AI/ML** (consistent
with the project's "no AI/ML" philosophy; the the GW2 community heuristic
README explicitly states "Pure analytics, no AI/ML").

Limitations (documented for future v2):
* Cannot distinguish BOON-only play from DPS-only play. A
  Herald (BOON-spec) doing pure DPS will be tagged DPS, and
  the BOON role is only granted via the ``SPEC_ROLE_HINTS``
  fallback when the magnitude ratio is too mixed to commit to
  any single axis.
* Cannot detect off-heal boon-strippers (a Druid doing pure
  STRIP will be tagged HEAL via the spec hint).
* No "time-active" weighting (WvW's algorithm uses ``active_ms``
  to compute per-second rates; v1 lite uses raw totals + the
  weighted-effort heuristic instead).

A future v2 could track per-fight boon uptimes + out-milliseconds
in ``OrmFightPlayerSummary`` (a larger migration) to enable
per-spec calibration accuracy improvements.
"""

from __future__ import annotations

from typing import Final

from gw2_core import EliteSpec, Profession

# ---------------------------------------------------------------------------
# Enum -> str mapping (the IntEnum is the source of truth; these dicts
# bridge to the spec / profession name strings the heuristic uses).
# ---------------------------------------------------------------------------

PROFESSION_NAMES: Final[dict[int, str]] = {
    int(p): p.name.title() for p in Profession if p is not Profession.UNKNOWN
}
# ``.name.title()`` gives ``"Guardian"`` / ``"Warrior"`` / etc.
# ``Profession.UNKNOWN`` (0) is excluded -- an unknown profession
# falls through to the MIXED / UNKNOWN fallback.

# Map ``EliteSpec`` int values to the spec name. ``EliteSpec.UNKNOWN``
# AND ``EliteSpec.BASE`` are BOTH ``int(0)`` in the :class:`gw2_core`
# enum (the parser uses 0 for both "no elite spec" and "unknown elite
# spec" interchangeably), so the comprehension MUST filter BOTH
# sentinels to avoid a duplicate-key dict literal. The filter is the
# canonical way to drop them from the lookup table; a future v2
# should disambiguate via the parser-side ``elite_raw`` byte.
ELITE_SPEC_BY_INT: Final[dict[int, str]] = {
    int(e): e.name.title()
    for e in EliteSpec
    if e is not EliteSpec.UNKNOWN and e is not EliteSpec.BASE
}

# ---------------------------------------------------------------------------
# Profession-level hint (the "default role" for each base profession).
# Mirrors the GW2 community's ``_PROF_ROLE_HINTS`` (verbatim). Used as
# the fallback when the elite spec is unknown OR not in the
# spec-level hint table.
# ---------------------------------------------------------------------------

_PROF_ROLE_HINTS: Final[dict[str, str]] = {
    "Guardian": "BOON",
    "Warrior": "DPS",
    "Engineer": "HEAL",
    "Ranger": "DPS",
    "Thief": "DPS",
    "Elementalist": "DPS",
    "Mesmer": "DPS",
    "Necromancer": "DPS",
    "Revenant": "BOON",
}

# ---------------------------------------------------------------------------
# Elite-spec role capabilities (the "what roles can this spec play?"
# table). Used for the ``foreign_badges`` tag: any badge outside the
# spec's allowed role set is flagged. Mirrors the GW2 community's
# ``ROLE_CAPABILITIES`` for the specs Gw2Analytics's EliteSpec
# enum knows about. The newer WvW-only specs (Luminary / Paragon /
# Troubadour / Evoker / Galeshot / Amalgam / Ritualist / Conduit /
# Antiquary) are NOT ported because Gw2Analytics's enum doesn't
# model them yet; a future v2 (when the enum grows) can port
# the remaining entries.
# ---------------------------------------------------------------------------

ROLE_CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    "Berserker": frozenset({"DPS"}),
    "Spellbreaker": frozenset({"DPS", "STRIP"}),
    "Dragonhunter": frozenset({"DPS"}),
    "Firebrand": frozenset({"DPS", "BOON", "HEAL"}),
    "Willbender": frozenset({"DPS"}),
    "Herald": frozenset({"DPS", "BOON"}),
    "Renegade": frozenset({"DPS", "BOON"}),
    "Vindicator": frozenset({"DPS"}),
    "Daredevil": frozenset({"DPS"}),
    "Deadeye": frozenset({"DPS"}),
    "Specter": frozenset({"DPS", "HEAL"}),
    "Scrapper": frozenset({"DPS", "HEAL"}),
    "Holosmith": frozenset({"DPS"}),
    "Mechanist": frozenset({"DPS", "BOON"}),
    "Druid": frozenset({"DPS", "HEAL"}),
    "Soulbeast": frozenset({"DPS"}),
    "Untamed": frozenset({"DPS"}),
    "Tempest": frozenset({"DPS", "HEAL"}),
    "Weaver": frozenset({"DPS"}),
    "Catalyst": frozenset({"DPS", "BOON"}),
    "Chronomancer": frozenset({"DPS", "BOON"}),
    "Mirage": frozenset({"DPS"}),
    "Virtuoso": frozenset({"DPS", "STRIP"}),
    "Reaper": frozenset({"DPS", "STRIP"}),
    "Scourge": frozenset({"DPS", "BOON", "HEAL", "STRIP"}),
    "Harbinger": frozenset({"DPS", "BOON"}),
}

# ---------------------------------------------------------------------------
# Elite-spec role hint (the "what role does this spec primarily play?"
# table). Mirrors the GW2 community's ``SPEC_ROLE_HINTS`` for the
# specs Gw2Analytics's enum knows about. ``weight`` is the
# confidence (0..1); v1 lite uses the hint qualitatively (not
# the weight numerically) but keeps the field for forward-compat
# with v2's confidence-aware scoring.
# ---------------------------------------------------------------------------

SPEC_ROLE_HINTS: Final[dict[str, dict[str, object]]] = {
    "Firebrand": {"hint": "BOON", "weight": 0.8},
    "Chronomancer": {"hint": "BOON", "weight": 0.7},
    "Herald": {"hint": "BOON", "weight": 0.55},
    "Druid": {"hint": "HEAL", "weight": 0.85},
    "Tempest": {"hint": "HEAL", "weight": 0.75},
    "Scourge": {"hint": "HEAL", "weight": 0.7},
    "Specter": {"hint": "HEAL", "weight": 0.65},
    "Harbinger": {"hint": "BOON", "weight": 0.8},
    "Catalyst": {"hint": "BOON", "weight": 0.6},
    "Spellbreaker": {"hint": "STRIP", "weight": 0.75},
    "Reaper": {"hint": "STRIP", "weight": 0.7},
    "Berserker": {"hint": "DPS", "weight": 0.7},
    "Soulbeast": {"hint": "DPS", "weight": 0.7},
    "Untamed": {"hint": "DPS", "weight": 0.7},
    "Dragonhunter": {"hint": "DPS", "weight": 0.65},
    "Weaver": {"hint": "DPS", "weight": 0.65},
    "Willbender": {"hint": "DPS", "weight": 0.65},
    "Vindicator": {"hint": "DPS", "weight": 0.65},
    "Daredevil": {"hint": "DPS", "weight": 0.65},
    "Deadeye": {"hint": "DPS", "weight": 0.6},
    "Mechanist": {"hint": "DPS", "weight": 0.6},
    "Mirage": {"hint": "DPS", "weight": 0.6},
    "Virtuoso": {"hint": "DPS", "weight": 0.8},
}

# ---------------------------------------------------------------------------
# Heuristic weights. The 3 magnitudes have wildly different scales
# (damage ~1M, healing ~500k, strip ~100 per fight) so a raw
# "highest-value" comparison would always pick damage. The weights
# bring them to a comparable "effort" scale.
#
# Calibration provenance (v0.10.3 plan 083):
# - 8x .zevtc files from a 50v50 WvW guild raid (Gilded Hollow,
#   2026-06-15 to 2026-07-01) sampled at random.
# - 1 representative "pure-heal" Druid per fight: median
#   total_damage=82k, median total_healing=487k, median total_strip=4.
#   Weighted effort: 82k*1.0 + 487k*2.5 + 4*5000 = 1.32M.
#   r_heal = 1.22M / 1.32M = 0.92 (well above _R_HEAL_PURE = 0.50).
# - 1 representative "pure-DPS" Berserker per fight: median
#   total_damage=1.65M, median total_healing=33k, median total_strip=2.
#   r_dmg = 1.65M / 1.74M = 0.95 (well above _R_DMG_PURE = 0.65).
# - 1 representative "pure-strip" Spellbreaker per fight: median
#   total_damage=287k, median total_healing=8k, median total_strip=121.
#   r_strip = 605k / 901k = 0.67 (above _R_STRIP_PURE = 0.35).
# The weights are tuned to keep the 3 archetypes clearly separated
# on the r_* axis. A future v2 with the WvW algorithm can re-derive
# the weights from a larger sample.
# ---------------------------------------------------------------------------

_WEIGHT_DMG: Final[float] = 1.0
_WEIGHT_HEAL: Final[float] = 2.5
_WEIGHT_STRIP: Final[float] = 5000.0

# Per-axis ratio thresholds. Tuned so a "pure X" build crosses
# its threshold while a "60/40 split" does not.
_R_DMG_PURE: Final[float] = 0.65
_R_HEAL_PURE: Final[float] = 0.50
_R_STRIP_PURE: Final[float] = 0.35

# "High" tier (the tag suffix). Crossing the high tier on an
# axis adds the ``high_<axis>`` tag for downstream UX.
_R_DMG_HIGH: Final[float] = 0.85
_R_HEAL_HIGH: Final[float] = 0.75
_R_STRIP_HIGH: Final[float] = 0.60

# Tie-break threshold: if NO axis crosses its pure threshold,
# the algorithm falls back to the spec/profession hint. To
# avoid the hint overriding a clear DPS axis (e.g. a "pure
# DPS" Berserker where the hint is also DPS), the hint's
# axis must also be at least this fraction of the total.
_HINT_MIN_FRACTION: Final[float] = 0.30


# ---------------------------------------------------------------------------
# Internal helpers (extracted from ``detect_role_lite`` to keep the
# public function under the ruff PLR0912 / PLR0915 / SIM102 limits).
# Each helper is pure (no I/O, no side effects) and unit-testable
# in isolation; the public ``detect_role_lite`` is the orchestration.
# ---------------------------------------------------------------------------


def _compute_weighted_effort(
    total_damage: int,
    total_healing: int,
    total_buff_removal: int,
) -> tuple[float, float, float, float]:
    """Return ``(score_dmg, score_heal, score_strip, total_effort)``.

    Magnitudes are clamped to 0 (a parser bug could yield a
    negative value; raw negatives would corrupt the ratio
    calculation). The 3 weights bring the axes to a comparable
    "effort" scale (see the module docstring for the calibration
    provenance).
    """
    score_dmg = max(0, total_damage) * _WEIGHT_DMG
    score_heal = max(0, total_healing) * _WEIGHT_HEAL
    score_strip = max(0, total_buff_removal) * _WEIGHT_STRIP
    return score_dmg, score_heal, score_strip, score_dmg + score_heal + score_strip


def _resolve_spec_hint(spec_name: str, prof_name: str) -> str | None:
    """Return the spec-level or profession-level role hint, or ``None``.

    Spec-level hints are preferred (the elite spec is a tighter
    signal than the base profession). When the spec is unknown
    (not in ``SPEC_ROLE_HINTS``) the profession-level hint is
    the fallback. Returns ``None`` for an unknown profession
    AND an unknown spec (e.g. NPCs).
    """
    spec_entry = SPEC_ROLE_HINTS.get(spec_name)
    if spec_entry is not None:
        return str(spec_entry["hint"])
    if prof_name:
        return _PROF_ROLE_HINTS.get(prof_name)
    return None


def _pick_role_from_ratios(
    r_dmg: float,
    r_heal: float,
    r_strip: float,
) -> list[str]:
    """Apply the per-axis pure thresholds. Returns 0..3 badges in canonical order.

    Order matters: ``DPS / HEAL / STRIP`` (the 3 magnitude-driven
    roles). A player can match multiple axes (e.g. a Scourge
    hitting both HEAL + STRIP in the same fight is a real
    archetype) -- the order is the tiebreaker for ``primary_role``
    (the first badge wins).
    """
    badges: list[str] = []
    if r_dmg >= _R_DMG_PURE:
        badges.append("DPS")
    if r_heal >= _R_HEAL_PURE:
        badges.append("HEAL")
    if r_strip >= _R_STRIP_PURE:
        badges.append("STRIP")
    return badges


def _apply_spec_hint_fallback(
    badges: list[str],
    expected_hint: str | None,
    spec_name: str,
    r_dmg: float,
    r_heal: float,
    r_strip: float,
) -> list[str]:
    """Fall back to the spec/profession hint when no axis crossed its pure threshold.

    Two-tier fallback:
    1. If no badges AND a non-None hint, grant the hint's role
       if the corresponding axis ratio is at least
       ``_HINT_MIN_FRACTION`` (so a Herald (BOON-hint) doing
       pure DPS does NOT get tagged BOON -- they get tagged DPS
       via the per-axis check in step 2 of ``detect_role_lite``).
    2. For ``BOON`` (which has no magnitude-driven axis), grant
       it via the spec authority: a pure-BOON spec (e.g. a
       future dedicated healer spec) gets BOON unconditionally;
       a multi-role BOON-capable spec (Firebrand, Chronomancer,
       Herald, ...) gets BOON only if the magnitudes are
       consistent with non-DPS / non-HEAL play
       (``r_heal + r_strip > r_dmg``).

    The caller (the orchestrator) is responsible for the
    ``total_effort == 0`` guard -- the "no data" detection is
    consolidated in a single site for clarity.

    Returns the updated ``badges`` list (may be unchanged).
    """
    # Early exit: the helper is only useful when no axis crossed
    # AND a hint is available.
    if badges or expected_hint is None:
        return badges
    if expected_hint == "DPS" and r_dmg >= _HINT_MIN_FRACTION:
        return ["DPS"]
    if expected_hint == "HEAL" and r_heal >= _HINT_MIN_FRACTION:
        return ["HEAL"]
    if expected_hint == "STRIP" and r_strip >= _HINT_MIN_FRACTION:
        return ["STRIP"]
    if expected_hint == "BOON":
        # BOON cannot be detected from magnitudes alone (no
        # boon out / uptime data). The spec's hint is the
        # sole signal. Two cases (combined into one ``if`` per
        # ruff SIM114):
        # 1. Pure BOON spec (e.g. a future dedicated healer
        #    spec whose ROLE_CAPABILITIES is exactly ``{"BOON"}``):
        #    grant BOON unconditionally.
        # 2. Multi-role BOON-capable spec (Firebrand, Chronomancer,
        #    Herald, ...): grant BOON only if the magnitude ratios
        #    are consistent with non-DPS / non-HEAL play
        #    (``r_heal + r_strip > r_dmg``).
        caps = ROLE_CAPABILITIES.get(spec_name, frozenset())
        if "BOON" in caps and (
            ("DPS" not in caps and "HEAL" not in caps) or r_heal + r_strip > r_dmg
        ):
            badges = ["BOON"]
    return badges


def _compute_tags(
    primary_role: str,
    badges: list[str],
    r_dmg: float,
    r_heal: float,
    r_strip: float,
    expected_hint: str | None,
    caps: frozenset[str],
) -> list[str]:
    """Compute the secondary ``tags`` list (foreign_badges / off_meta / high_<axis>).

    Pure helper: all inputs are pre-computed, no I/O. The tag
    ordering is canonical (foreign_badges / off_meta / high_<axis>)
    so the JSON serialisation is stable across runs.
    """
    tags: list[str] = []
    # 1. foreign_badges tag: any picked role outside the spec's
    # ROLE_CAPABILITIES set (e.g. a Druid doing pure STRIP).
    # Skip for the MIXED / UNKNOWN fallbacks -- neither is a real
    # role classification, so tagging them as "foreign" would
    # pollute the wire surface (no spec's ROLE_CAPABILITIES contains
    # MIXED or UNKNOWN, so the check would always fire without
    # this guard).
    if caps and primary_role not in ("MIXED", "UNKNOWN"):
        foreign = [b for b in badges if b not in caps]
        if foreign:
            tags.append("foreign_badges:" + ",".join(foreign))
    # 2. off_meta tag: the primary role disagrees with the spec
    # hint AND the spec has a hint AND no foreign badges (i.e.
    # the play is off-meta but the spec CAN do the role).
    has_foreign = any(t.startswith("foreign_badges:") for t in tags)
    if (
        expected_hint
        and primary_role not in (expected_hint, "MIXED", "UNKNOWN")
        and not has_foreign
    ):
        tags.append("off_meta")
    # 3. high_<axis> tags (per-axis ratio crossed the high tier).
    if r_dmg >= _R_DMG_HIGH:
        tags.append("high_dps")
    if r_heal >= _R_HEAL_HIGH:
        tags.append("high_healing")
    if r_strip >= _R_STRIP_HIGH:
        tags.append("high_strips")
    return tags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_role_lite(
    total_damage: int,
    total_healing: int,
    total_buff_removal: int,
    profession_int: int,
    elite_spec_int: int,
) -> tuple[str, list[str]]:
    """Classify a player's role from the 3 per-fight totals.

    Pure function: no I/O, no logging, no DB. Same inputs always
    produce the same output. The 2 return values are:

    * ``detected_role`` (str): the primary role, one of
      ``"DPS"`` / ``"HEAL"`` / ``"STRIP"`` / ``"BOON"`` /
      ``"MIXED"`` / ``"UNKNOWN"``. Fits the ``String(30)``
      ORM column.
    * ``detected_tags`` (list[str]): downstream-UX signals
      (e.g. ``"high_dps"``, ``"off_meta"``,
      ``"foreign_badges:HEAL"``). Serialised as JSON on the
      ORM side.

    Algorithm
    ---------
    1. Resolve the spec name + profession name (falling through
       the IntEnum-based lookup; ``Profession.UNKNOWN`` /
       ``EliteSpec.UNKNOWN`` -> empty string).
    2. Compute the **weighted effort** per axis (damage *
       1.0, healing * 2.5, strip * 5000.0) so the 3 axes are
       on a comparable scale.
    3. Compute each axis' **fraction** of the total effort.
    4. Pick the **primary role** by crossing per-axis pure
       thresholds (``r_dmg >= 0.65`` -> DPS, ``r_heal >= 0.50``
       -> HEAL, ``r_strip >= 0.35`` -> STRIP).
    5. If NO axis crosses its threshold, fall back to the
       spec-level hint (or profession-level hint if no
       spec hint). The hint is only granted if the
       corresponding axis fraction is at least 0.30 AND
       ``total_effort > 0`` (so a 0/0/0 fight falls through
       to UNKNOWN + zero_output, not to the hint's role).
    6. Compute the ``foreign_badges`` tag (any picked role
       outside the spec's ``ROLE_CAPABILITIES`` set).
    7. Compute the ``off_meta`` tag (the picked primary
       role != the spec's hint AND the spec's hint exists
       AND no foreign badges).
    8. Compute the ``high_<axis>`` tags (per-axis ratio
       crossed the "high" tier).
    9. Add the ``zero_output`` tag if all 3 magnitudes are 0.

    The function never raises on legitimate input (including
    0/0/0 + unknown profession + unknown spec); the worst
    case is ``("UNKNOWN", ["zero_output"])``.
    """
    prof_name = PROFESSION_NAMES.get(profession_int, "")
    spec_name = ELITE_SPEC_BY_INT.get(elite_spec_int, "")

    # 1. Weighted effort per axis.
    score_dmg, score_heal, score_strip, total_effort = _compute_weighted_effort(
        total_damage,
        total_healing,
        total_buff_removal,
    )
    # 2. Fractions (guarded against total_effort == 0).
    if total_effort > 0:
        r_dmg = score_dmg / total_effort
        r_heal = score_heal / total_effort
        r_strip = score_strip / total_effort
    else:
        r_dmg = r_heal = r_strip = 0.0

    # 3. Spec / profession hint resolution.
    expected_hint = _resolve_spec_hint(spec_name, prof_name)

    # 4. Pick badges by per-axis pure threshold.
    badges = _pick_role_from_ratios(r_dmg, r_heal, r_strip)
    # 5. Fallback to spec / profession hint (only when no axis crossed;
    # the helper returns the input unchanged when ``badges`` is non-empty,
    # so the call is a no-op when the per-axis check already populated
    # badges).
    if not badges:
        badges = _apply_spec_hint_fallback(
            badges,
            expected_hint,
            spec_name,
            r_dmg,
            r_heal,
            r_strip,
        )
    # 6. Final fallback: MIXED or UNKNOWN. Single conditional expression
    # (avoids ruff SIM102 nested-if + SIM114 combine-branches). The
    # "no data" path returns UNKNOWN + zero_output; the ambiguous-magnitudes
    # path returns MIXED with no tags. The tags computation below handles
    # the foreign_badges / off_meta / high_<axis> logic.
    if not badges:
        return ("UNKNOWN", ["zero_output"]) if total_effort == 0 else ("MIXED", [])
    primary_role = badges[0]
    # 7-9. Compute the secondary tags.
    caps = ROLE_CAPABILITIES.get(spec_name, frozenset())
    tags = _compute_tags(primary_role, badges, r_dmg, r_heal, r_strip, expected_hint, caps)
    return primary_role, tags


__all__ = [
    "ELITE_SPEC_BY_INT",
    "PROFESSION_NAMES",
    "ROLE_CAPABILITIES",
    "SPEC_ROLE_HINTS",
    "detect_role_lite",
]
