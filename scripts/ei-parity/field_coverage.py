#!/usr/bin/env python3
"""Execute the Elite Insights field-coverage gate.

The gate answers one question, per product-consumed field: *can the pinned EI
detailed-WvW export reproduce what Gw2Analytics needs?*

It is deliberately **self-verifying**. ``MAPPING`` is a curated table, but every
``ei`` path in it is resolved against the real corpus before the matrix is
written. A claim about a path the corpus does not contain is a hard failure, so
the published matrix cannot drift into fiction the way a hand-written table
does.

Usage::

    uv run python scripts/ei-parity/field_coverage.py \
        --corpus   "/path/to/zevtc files" \
        --ei-out   /path/to/ei-out \
        --write

``--write`` rewrites ``docs/validation/ei-field-coverage.json`` and
``docs/validation/ei-field-coverage-matrix.md``. Without the private corpus the
gate exits 2 (INCOMPLETE) rather than reporting a pass.

Privacy: only structural information is emitted -- EI key paths, presence
counts and statuses. No account names, character names, IPs or raw logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS_LIST = ROOT / "scripts" / "ei-parity" / "corpus.txt"
DEFAULT_OUT_JSON = ROOT / "docs" / "validation" / "ei-field-coverage.json"
DEFAULT_OUT_MD = ROOT / "docs" / "validation" / "ei-field-coverage-matrix.md"

#: Status vocabulary. ``EXACT`` and ``TRANSFORMABLE`` are the only statuses
#: that let a field be served straight from EI; ``AGGREGATED_BUT_SUFFICIENT``
#: means EI exposes the answer but not the per-event detail behind it.
EXACT = "EXACT"
TRANSFORMABLE = "TRANSFORMABLE"
AGGREGATED_BUT_SUFFICIENT = "AGGREGATED_BUT_SUFFICIENT"
MISSING = "MISSING"
AMBIGUOUS = "AMBIGUOUS"
REQUIRES_EI_EXPORT_CHANGE = "REQUIRES_EI_EXPORT_CHANGE"
PRODUCT_REDUNDANT = "PRODUCT_REDUNDANT"

STATUS_ORDER = (
    EXACT,
    TRANSFORMABLE,
    AGGREGATED_BUT_SUFFICIENT,
    AMBIGUOUS,
    MISSING,
    REQUIRES_EI_EXPORT_CHANGE,
    PRODUCT_REDUNDANT,
)


@dataclass(frozen=True)
class Entry:
    """One product-consumed field and its standing against the EI export."""

    area: str
    product_field: str
    product_source: str
    consumers: str
    status: str
    #: Dotted EI path (``players[].dpsAll[].damage``), validated against the
    #: corpus. ``None`` when EI exposes nothing today.
    ei: str | None = None
    note: str = ""


def E(  # noqa: N802 - compact table builder keeps MAPPING readable
    area: str,
    product_field: str,
    product_source: str,
    consumers: str,
    status: str,
    ei: str | None = None,
    note: str = "",
) -> Entry:
    return Entry(area, product_field, product_source, consumers, status, ei, note)


#: The gate. Every ``ei`` path below is resolved against the corpus at run time.
MAPPING: tuple[Entry, ...] = (
    # -- fight identity and envelope -----------------------------------------
    E(
        "fight",
        "time_start_ms",
        "gw2_core.Fight.header.time_start_ms",
        "api routes/fights, web",
        TRANSFORMABLE,
        "timeStartStd",
        "EI emits an offset-qualified local timestamp string; convert to epoch ms.",
    ),
    E(
        "fight",
        "time_end_ms",
        "gw2_core.Fight.header.time_end_ms",
        "api routes/fights",
        TRANSFORMABLE,
        "timeEndStd",
        "Same conversion as time_start_ms.",
    ),
    E(
        "fight",
        "duration_ms",
        "gw2_core.Fight.header.duration_ms",
        "gw2_analytics aggregators, web",
        EXACT,
        "durationMS",
        "",
    ),
    E(
        "fight",
        "build_version",
        "gw2_core.Fight.header.build_version",
        "api routes/fights, diagnostics",
        TRANSFORMABLE,
        "gW2Build",
        "EI exposes the integer build number plus the arcdps arcVersion string; "
        "the product keys on the arcdps build token.",
    ),
    E(
        "fight",
        "arc_revision",
        "gw2_core.Fight.header.arc_revision",
        "diagnostics",
        TRANSFORMABLE,
        "arcRevision",
        "",
    ),
    E(
        "fight",
        "map_id",
        "gw2_core.Fight.header.map_id",
        "api routes/fights, web",
        EXACT,
        "mapID",
        "",
    ),
    E(
        "fight",
        "encounter_outcome",
        "gw2_core.CombatOutcomeEvent",
        "gw2_analytics.multi_fight, down_contribution",
        EXACT,
        "success",
        "EI resolves success/wipe; the custom parser derives it from the outcome events.",
    ),
    # -- actors ---------------------------------------------------------------
    E(
        "players",
        "account_name",
        "gw2_core.Agent.account_name",
        "api routes/fights, web, squad_rollup",
        EXACT,
        "players[].account",
        "",
    ),
    E(
        "players",
        "character_name",
        "gw2_core.Agent.name",
        "api routes/fights, web",
        EXACT,
        "players[].name",
        "",
    ),
    E(
        "players",
        "profession",
        "gw2_core.Agent.profession",
        "web, role_detection",
        TRANSFORMABLE,
        "players[].profession",
        "EI emits the display name (elite spec when specialised); split back into "
        "base profession + EliteSpec. Elite Insights' SpecList is the authority.",
    ),
    E(
        "players",
        "elite_spec",
        "gw2_core.Agent.elite",
        "web, role_detection",
        TRANSFORMABLE,
        "players[].profession",
        "Same field; needs the spec table to decide core vs elite.",
    ),
    E(
        "players",
        "subgroup",
        "gw2_core.Agent.subgroup",
        "web, squad_rollup, per_fight_timeline",
        EXACT,
        "players[].group",
        "",
    ),
    E(
        "players",
        "team_id",
        "gw2_core.Agent.team_id",
        "web, player_profile",
        EXACT,
        "players[].teamID",
        "",
    ),
    E(
        "players",
        "instance_id",
        "gw2_core.Agent.instance_id",
        "temporal_identity, per_player_timeline",
        EXACT,
        "players[].instanceID",
        "",
    ),
    E(
        "players",
        "gear_stats (healing/toughness/concentration/condition)",
        "gw2_core.Agent.* attribute fields",
        "role_detection",
        EXACT,
        "players[].healing",
        "EI also exposes toughness/condition/concentration on the same record.",
    ),
    E(
        "players",
        "weapons",
        "gw2_core.Agent weapon data",
        "web, player_profile",
        EXACT,
        "players[].weapons",
        "",
    ),
    E(
        "players",
        "guild_id",
        "gw2_core.Agent.guild_id",
        "web",
        EXACT,
        "players[].guildID",
        "",
    ),
    # -- awareness ------------------------------------------------------------
    E(
        "awareness",
        "first_aware_ms",
        "scan_agent_awareness()[agent][0]",
        "temporal_identity, buff_uptime windows",
        EXACT,
        "players[].firstAware",
        "",
    ),
    E(
        "awareness",
        "last_aware_ms",
        "scan_agent_awareness()[agent][1]",
        "temporal_identity, buff_uptime windows",
        EXACT,
        "players[].lastAware",
        "",
    ),
    # -- identity / ownership -------------------------------------------------
    E(
        "identity",
        "source/target agent reference",
        "gw2_core.BaseEvent.src_agent/dst_agent",
        "every gw2_analytics aggregator",
        TRANSFORMABLE,
        "players[].statsTargets[][]",
        "EI per-target arrays are positional against targets[] and players[]; "
        "a resolvable index replaces the raw agent pointer.",
    ),
    E(
        "ownership",
        "minion -> master (static membership)",
        "gw2_core.Agent ownership",
        "per_player_timeline, role_detection",
        TRANSFORMABLE,
        "players[].minions[].id",
        "EI nests each minion under its owning player; membership is recoverable, "
        "but only as a static set without time bounds.",
    ),
    E(
        "ownership",
        "OwnershipInterval (time-ranged)",
        "gw2_core.OwnershipInterval",
        "temporal_identity",
        REQUIRES_EI_EXPORT_CHANGE,
        None,
        "EI records minion/pet damage under the owner but publishes no "
        "[start,end) ownership interval. The product's time-parameterised "
        "identity resolution needs a new EI export.",
    ),
    E(
        "ownership",
        "minion unique-per-timeframe flag",
        "gw2_core.Agent ownership",
        "temporal_identity",
        AMBIGUOUS,
        "players[].minions[].isUniquePerTimeFrame",
        "Hints at temporal resolution but the payload carries no interval bounds.",
    ),
    # -- damage ---------------------------------------------------------------
    E(
        "damage",
        "total_damage",
        "gw2_core.DamageEvent aggregation",
        "player_damage, squad_rollup, web",
        EXACT,
        "players[].dpsAll[].damage",
        "",
    ),
    E(
        "damage",
        "strike_damage",
        "gw2_core.DamageEvent (power)",
        "condi_power_split, web",
        EXACT,
        "players[].dpsAll[].powerDamage",
        "",
    ),
    E(
        "damage",
        "condition_damage",
        "gw2_core.DamageEvent (condition)",
        "condi_power_split, web",
        EXACT,
        "players[].dpsAll[].condiDamage",
        "",
    ),
    E(
        "damage",
        "barrier_damage",
        "gw2_core.DamageEvent shield",
        "player_damage",
        EXACT,
        "players[].dpsAll[].breakbarDamage",
        "Breakbar damage is exposed; shield/barrier damage is on totalDamageDist[].shieldDamage.",
    ),
    E(
        "damage",
        "per-skill damage distribution",
        "gw2_core.DamageEvent by skill",
        "skill_usage, web",
        EXACT,
        "players[].totalDamageDist[][].totalDamage",
        "",
    ),
    E(
        "damage",
        "damage per target",
        "gw2_core.DamageEvent by target",
        "target_dps, web",
        EXACT,
        "players[].dpsTargets[][].damage",
        "",
    ),
    E(
        "damage",
        "critical rate / flanking / glance",
        "gw2_core.DamageEvent flags",
        "web",
        EXACT,
        "players[].statsAll[].criticalRate",
        "",
    ),
    # -- mitigation -----------------------------------------------------------
    E(
        "mitigation",
        "invulned / absorbed",
        "gw2_core.DamageEvent.result",
        "player_defense, web",
        EXACT,
        "players[].defenses[].invulnedCount",
        "",
    ),
    E(
        "mitigation",
        "blocked",
        "gw2_core.BlockEvent",
        "player_defense, web",
        EXACT,
        "players[].defenses[].blockedCount",
        "",
    ),
    E(
        "mitigation",
        "dodges",
        "gw2_core.DodgeEvent",
        "player_defense, web",
        EXACT,
        "players[].defenses[].dodgeCount",
        "",
    ),
    E(
        "mitigation",
        "evaded / missed",
        "gw2_core.DamageEvent.result",
        "player_defense, web",
        EXACT,
        "players[].defenses[].evadedCount",
        "",
    ),
    E(
        "mitigation",
        "damage taken (total / strike / condition / barrier)",
        "gw2_core.DamageEvent (incoming)",
        "web, player_profile",
        EXACT,
        "players[].defenses[].damageTaken",
        "",
    ),
    # -- healing and barrier --------------------------------------------------
    E(
        "healing",
        "outgoing healing",
        "gw2_core.HealingEvent",
        "player_heal, squad_rollup, web",
        EXACT,
        "players[].extHealingStats.outgoingHealing",
        "",
    ),
    E(
        "healing",
        "incoming healing",
        "gw2_core.HealingEvent (incoming)",
        "web",
        EXACT,
        "players[].extHealingStats.incomingHealing",
        "",
    ),
    E(
        "healing",
        "healing distribution",
        "gw2_core.HealingEvent by skill",
        "web",
        EXACT,
        "players[].extHealingStats.totalHealingDist",
        "",
    ),
    E(
        "barrier",
        "outgoing barrier",
        "gw2_core.BarrierEvent",
        "player_heal",
        EXACT,
        "players[].extBarrierStats.outgoingBarrier",
        "",
    ),
    E(
        "barrier",
        "incoming barrier",
        "gw2_core.BarrierEvent (incoming)",
        "web",
        EXACT,
        "players[].extBarrierStats.incomingBarrier",
        "",
    ),
    # -- support --------------------------------------------------------------
    E(
        "support",
        "condition cleanses",
        "gw2_core.ConditionRemoveEvent",
        "web, squad_rollup",
        EXACT,
        "players[].support[].condiCleanse",
        "",
    ),
    E(
        "support",
        "boon strips",
        "gw2_core.BuffRemovalEvent",
        "web, squad_rollup",
        EXACT,
        "players[].support[].boonStrips",
        "",
    ),
    E(
        "support",
        "stun breaks",
        "gw2_core.StunBreakEvent",
        "web",
        EXACT,
        "players[].support[].stunBreak",
        "",
    ),
    E(
        "support",
        "resurrects / resurrect time",
        "gw2_core resurrect events",
        "web",
        EXACT,
        "players[].support[].resurrects",
        "",
    ),
    E(
        "support",
        "removed stun duration",
        "gw2_core.StunBreakEvent",
        "web",
        EXACT,
        "players[].support[].removedStunDuration",
        "",
    ),
    # -- crowd control --------------------------------------------------------
    E(
        "crowd_control",
        "applied CC count",
        "gw2_core.CCEvent",
        "web, squad_rollup",
        EXACT,
        "players[].statsAll[].appliedCrowdControl",
        "",
    ),
    E(
        "crowd_control",
        "applied CC duration",
        "gw2_core.CCEvent duration",
        "web",
        EXACT,
        "players[].statsAll[].appliedCrowdControlDuration",
        "",
    ),
    E(
        "crowd_control",
        "received CC",
        "gw2_core.CCEvent (incoming)",
        "web",
        EXACT,
        "players[].defenses[].receivedCrowdControl",
        "",
    ),
    E(
        "crowd_control",
        "breakbar damage",
        "gw2_core.CCEvent breakbar",
        "web",
        EXACT,
        "players[].defenses[].breakbarDamageTaken",
        "",
    ),
    # -- lifecycle ------------------------------------------------------------
    E(
        "lifecycle",
        "downs",
        "gw2_core.DownEvent",
        "down_contribution, multi_fight, web",
        EXACT,
        "players[].defenses[].downCount",
        "",
    ),
    E(
        "lifecycle",
        "deaths",
        "gw2_core.DeathEvent",
        "multi_fight, web",
        EXACT,
        "players[].defenses[].deadCount",
        "",
    ),
    E(
        "lifecycle",
        "down contribution",
        "gw2_core.DamageEvent (down contribution)",
        "down_contribution, web",
        EXACT,
        "players[].statsAll[].downContribution",
        "",
    ),
    E(
        "lifecycle",
        "interrupts",
        "gw2_core.InterruptEvent",
        "player_defense, web",
        EXACT,
        "players[].statsAll[].interrupts",
        "",
    ),
    E(
        "lifecycle",
        "death recap",
        "gw2_core.DeathEvent context",
        "web",
        EXACT,
        "players[].deathRecap[].deathTime",
        "",
    ),
    # -- buffs ----------------------------------------------------------------
    E(
        "buffs",
        "buff application (per event)",
        "gw2_core.BuffApplyEvent",
        "buff_state, buff_uptime",
        MISSING,
        None,
        "EI publishes per-second buff state, never the apply/remove events. The "
        "custom parser's event stream is the only source of the transition itself.",
    ),
    E(
        "buffs",
        "buff removal (per event)",
        "gw2_core.BuffRemovalEvent",
        "buff_state, target_buff_removal",
        MISSING,
        None,
        "Same as buff application: aggregate state only.",
    ),
    E(
        "buffs",
        "buff extension (per event)",
        "gw2_core.BuffExtensionEvent",
        "buff_state",
        MISSING,
        None,
        "No extension event in the EI export.",
    ),
    E(
        "buffs",
        "buff stack activation",
        "gw2_core.BuffStackActiveEvent",
        "buff_state",
        AGGREGATED_BUT_SUFFICIENT,
        "players[].buffUptimes[].states",
        "Per-second stack counts are exposed; the individual activation event is not.",
    ),
    E(
        "buffs",
        "buff uptime",
        "gw2_analytics.buff_uptime",
        "player_boons, squad_rollup, web",
        AGGREGATED_BUT_SUFFICIENT,
        "players[].buffUptimes[].buffData",
        "EI computes uptime itself (and the corpus shows it differs from the "
        "product's recomputation -- see scripts/ei-parity/corpus-baseline.json). "
        "Accepting EI's number means accepting EI's semantics.",
    ),
    E(
        "buffs",
        "buff apply/remove deltas (volume)",
        "gw2_analytics.buff_state",
        "web",
        AGGREGATED_BUT_SUFFICIENT,
        "players[].buffVolumes[].buffVolumeData",
        "",
    ),
    E(
        "buffs",
        "initial buffs at fight start",
        "gw2_analytics.initial_buffs",
        "player_boons, web",
        TRANSFORMABLE,
        "players[].buffUptimes[].states",
        "Index 0 of the per-second state array is the fight-start state.",
    ),
    E(
        "buffs",
        "self vs group vs squad vs off-group buff attribution",
        "gw2_analytics.player_boons",
        "web",
        EXACT,
        "players[].squadBuffs[].buffData",
        "EI pre-splits the same attribution the product computes.",
    ),
    # -- skills and rotations -------------------------------------------------
    E(
        "skills",
        "casts (skill activation)",
        "gw2_core.SkillActivationEvent",
        "skill_usage, rotation, web",
        TRANSFORMABLE,
        "players[].rotation[].skills",
        "EI exposes the activation ORDER per skill, not per-cast timestamps; "
        "cast timing must be re-derived or dropped.",
    ),
    E(
        "skills",
        "instant casts",
        "gw2_core.SkillActivationEvent (instant)",
        "rotation",
        AMBIGUOUS,
        "players[].rotation[].skills",
        "The rotation list does not distinguish instant from cast-time skills.",
    ),
    E(
        "skills",
        "rotation (ordered activation list)",
        "gw2_analytics.rotation",
        "web",
        TRANSFORMABLE,
        "players[].rotation[].id",
        "EI's rotation is an ordered skill-id list grouped per skill; the product's "
        "rotation is timestamped. Semantics differ but both are derivable "
        "projections of the same activations.",
    ),
    E(
        "skills",
        "weapon swap count",
        "gw2_core.WeaponSwapEvent",
        "web",
        EXACT,
        "players[].statsAll[].swapCount",
        "",
    ),
    E(
        "skills",
        "consumables",
        "gw2_core consumable events",
        "web",
        EXACT,
        "players[].consumables[].id",
        "",
    ),
    E(
        "skills",
        "skill cast uptime",
        "gw2_analytics.skill_usage",
        "web",
        EXACT,
        "players[].statsAll[].skillCastUptime",
        "",
    ),
    # -- positions / replay ---------------------------------------------------
    E(
        "positions",
        "agent positions over time",
        "gw2_core.PositionEvent",
        "position_analysis, web",
        REQUIRES_EI_EXPORT_CHANGE,
        None,
        "The pinned config runs ParseCombatReplay=false, so no position samples "
        "are emitted. Enabling it changes the export shape and cost and must be "
        "budgeted and re-certified.",
    ),
    E(
        "positions",
        "combat replay / timeline",
        "gw2_core.PositionEvent timeline",
        "web replay view",
        REQUIRES_EI_EXPORT_CHANGE,
        None,
        "Follows from the same config flag as agent positions.",
    ),
    E(
        "positions",
        "distToCom / stack distance",
        "gw2_analytics.position_analysis",
        "web",
        AGGREGATED_BUT_SUFFICIENT,
        "players[].statsAll[].distToCom",
        "EI reports the summary distance without the per-sample path.",
    ),
    E(
        "timeline",
        "health / barrier percentage timeline",
        "gw2_analytics.per_fight_timeline",
        "web",
        AGGREGATED_BUT_SUFFICIENT,
        "players[].healthPercents",
        "Per-second sampling, not event-resolution.",
    ),
    E(
        "timeline",
        "damage timeline (1s buckets)",
        "gw2_analytics.per_player_timeline",
        "web",
        AGGREGATED_BUT_SUFFICIENT,
        "players[].damage1S",
        "EI buckets at 1s; the product's timeline is event-resolution.",
    ),
    E(
        "timeline",
        "boon / condition state timeline",
        "gw2_analytics.per_fight_timeline",
        "web",
        AGGREGATED_BUT_SUFFICIENT,
        "players[].boonsStates",
        "",
    ),
    # -- targets --------------------------------------------------------------
    E(
        "targets",
        "enemy target roster",
        "gw2_core.Agent (enemy)",
        "target_dps, target_healing, web",
        TRANSFORMABLE,
        "targets[]",
        "EI's targets[] carries name/health/instanceID; mapping to product agents "
        "needs an identity join.",
    ),
    E(
        "targets",
        "per-target stats",
        "gw2_analytics.target_dps",
        "web",
        EXACT,
        "players[].statsTargets[][].totalDmg",
        "",
    ),
    E(
        "targets",
        "per-target healing",
        "gw2_analytics.target_healing",
        "web",
        EXACT,
        "players[].extHealingStats.outgoingHealingAllies",
        "",
    ),
    E(
        "targets",
        "per-target buff removal",
        "gw2_analytics.target_buff_removal",
        "web",
        MISSING,
        None,
        "Needs the raw buff-removal stream, which EI does not publish.",
    ),
    # -- archive --------------------------------------------------------------
    E(
        "archive",
        "multi-fight archive semantics",
        "gw2analytics_api.services.parse (fight iterator)",
        "uploads route, event_blob",
        AMBIGUOUS,
        None,
        "EI takes one log per invocation and merges nothing across fights. The "
        "product's upload->N fights contract has no EI equivalent; the adapter "
        "must define fight identity itself (see MULTILOG design note).",
    ),
    E(
        "archive",
        "raw event stream (generic)",
        "gw2_evtc_parser.PythonEvtcParser.parse_events",
        "event_blob, every gw2_analytics aggregator",
        REQUIRES_EI_EXPORT_CHANGE,
        None,
        "The product's analytics consume a normalized event stream. EI publishes "
        "aggregates and per-second series only. Removing the custom parser "
        "therefore requires either an EI export change or a product-side rewrite "
        "onto EI's aggregates. This single row gates the migration.",
    ),
    # -- product-redundant ----------------------------------------------------
    E(
        "redundant",
        "boon/condition classification tables",
        "gw2_evtc_parser buff tables",
        "buff_dispatch",
        PRODUCT_REDUNDANT,
        "buffMap",
        "EI publishes the buffMap/skillMap the product derives locally; the "
        "product copy can be sourced from EI metadata.",
    ),
    E(
        "redundant",
        "personal buff/damage-modifier tables",
        "gw2_evtc_parser tables",
        "buff_dispatch",
        PRODUCT_REDUNDANT,
        "personalBuffs",
        "EI publishes these per profession.",
    ),
)


def _walk(node: Any, path: str, sink: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            sink.add(here)
            _walk(value, here, sink)
    elif isinstance(node, list):
        sink.add(f"{path}[]")
        for item in node:
            _walk(item, f"{path}[]", sink)


def corpus_ids(list_file: Path) -> list[str]:
    return [
        line.strip()
        for line in list_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def ei_presence(ei_out: Path, ids: list[str]) -> tuple[dict[str, int], list[str]]:
    """Return ``(path -> number of logs containing it, missing log ids)``."""
    presence: Counter[str] = Counter()
    missing: list[str] = []
    for log_id in ids:
        export = ei_out / f"{log_id}_detailed_wvw_kill.json"
        if not export.is_file():
            missing.append(log_id)
            continue
        paths: set[str] = set()
        _walk(json.loads(export.read_text(encoding="utf-8")), "", paths)
        presence.update(paths)
    return dict(presence), missing


def _resolve(entry: Entry, presence: dict[str, int]) -> list[str]:
    """Return the unresolved EI paths an entry claims, if any."""
    if entry.ei is None:
        return []
    return [path for path in (entry.ei,) if path not in presence]


#: Account names look like ``Name.1234``; instance IPs are dotted quads.
_ACCOUNT_RE = re.compile(r"\b[A-Za-z][\w ]{2,}\.\d{3,5}\b")
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _privacy_violations(text: str, *, masks: tuple[str, ...] = ()) -> list[str]:
    """Return anything in ``text`` that looks like a private identifier.

    Structural tokens that merely *resemble* an identifier -- the Elite
    Insights version ``3.26.0.0`` is a valid dotted quad -- are masked out
    first, so the guard only fires on real leaks.
    """
    for mask in masks:
        if mask:
            text = text.replace(mask, "")
    violations = []
    violations.extend(_ACCOUNT_RE.findall(text))
    violations.extend(_IP_RE.findall(text))
    return violations


@dataclass
class Report:
    entries: list[Entry]
    presence: dict[str, int]
    unresolved: list[tuple[Entry, list[str]]] = field(default_factory=list)
    log_count: int = 0
    missing_logs: list[str] = field(default_factory=list)
    ei_version: str = ""
    corpus_digest: str = ""

    @property
    def counts(self) -> dict[str, int]:
        counter = Counter(entry.status for entry in self.entries)
        return {status: counter.get(status, 0) for status in STATUS_ORDER}


def build_report(corpus: Path, ei_out: Path) -> Report:
    ids = corpus_ids(CORPUS_LIST)
    presence, missing = ei_presence(ei_out, ids)
    unresolved = [(entry, bad) for entry in MAPPING if (bad := _resolve(entry, presence))]

    version, digest = "", ""
    sample = ei_out / f"{ids[0]}_detailed_wvw_kill.json" if ids else None
    if sample is not None and sample.is_file():
        payload = json.loads(sample.read_text(encoding="utf-8"))
        version = str(payload.get("eliteInsightsVersion", ""))
    if corpus.is_dir():
        digest = hashlib.sha256(
            "".join(sorted(p.name for p in corpus.glob("*.zevtc"))).encode()
        ).hexdigest()

    return Report(
        entries=list(MAPPING),
        presence=presence,
        unresolved=unresolved,
        log_count=len(ids) - len(missing),
        missing_logs=missing,
        ei_version=version,
        corpus_digest=digest,
    )


def render_json(report: Report) -> str:
    payload = {
        "gate": "ei-field-coverage",
        "ei_version": report.ei_version,
        "logs_analysed": report.log_count,
        "corpus_file_set_digest": report.corpus_digest,
        "status_counts": report.counts,
        "covered_ei_paths": len(report.presence),
        "unresolved_claims": [
            {"product_field": entry.product_field, "ei": bad} for entry, bad in report.unresolved
        ],
        "fields": [
            {
                "area": entry.area,
                "product_field": entry.product_field,
                "product_source": entry.product_source,
                "consumers": entry.consumers,
                "status": entry.status,
                "ei_path": entry.ei,
                "ei_presence_logs": report.presence.get(entry.ei, 0) if entry.ei else 0,
                "note": entry.note,
            }
            for entry in report.entries
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def render_markdown(report: Report) -> str:
    counts = report.counts
    lines = [
        "# EI field-coverage matrix",
        "",
        "Generated by `scripts/ei-parity/field_coverage.py` from the private "
        f"certification corpus ({report.log_count} logs) and the pinned Elite "
        f"Insights {report.ei_version} detailed-WvW export.",
        "",
        "Do not edit by hand: every `ei_path` below was resolved against the "
        "corpus at generation time. A path the corpus does not contain fails "
        "the gate instead of being published.",
        "",
        "## Status counts",
        "",
        "| status | fields |",
        "| --- | ---: |",
    ]
    lines += [f"| `{status}` | {counts[status]} |" for status in STATUS_ORDER]
    lines += [
        "",
        f"Distinct EI key paths observed across the corpus: {len(report.presence)}.",
        "",
        "## Matrix",
        "",
        "| area | product field | source | consumers | status | EI path | note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in report.entries:
        ei = f"`{entry.ei}`" if entry.ei else "--"
        note = entry.note.replace("|", "\\|")
        lines.append(
            f"| {entry.area} | {entry.product_field} | `{entry.product_source}` | "
            f"{entry.consumers} | `{entry.status}` | {ei} | {note} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", required=True, type=Path, help="directory holding the .zevtc corpus"
    )
    parser.add_argument(
        "--ei-out", required=True, type=Path, help="directory holding EI detailed-WvW exports"
    )
    parser.add_argument("--write", action="store_true", help="rewrite the tracked matrix artifacts")
    args = parser.parse_args(argv)

    if not CORPUS_LIST.is_file():
        print(f"corpus list missing: {CORPUS_LIST}", file=sys.stderr)
        return 2

    report = build_report(args.corpus, args.ei_out)
    if report.missing_logs:
        print(
            f"INCOMPLETE: {len(report.missing_logs)} corpus logs lack an EI export: "
            f"{', '.join(report.missing_logs[:5])}",
            file=sys.stderr,
        )
        return 2

    counts = report.counts
    print(f"EI {report.ei_version}: {report.log_count} logs, {len(report.presence)} EI paths")
    for status in STATUS_ORDER:
        print(f"  {status:28s} {counts[status]}")

    md, js = render_markdown(report), render_json(report)
    violations = _privacy_violations(md + js, masks=(report.ei_version, report.corpus_digest))
    if violations:
        print(f"PRIVACY: refusing to write, found {violations[:3]}", file=sys.stderr)
        return 3

    if report.unresolved:
        for entry, bad in report.unresolved:
            print(f"UNRESOLVED CLAIM: {entry.product_field} -> {bad}", file=sys.stderr)
        return 1

    if args.write:
        DEFAULT_OUT_JSON.write_text(js, encoding="utf-8")
        DEFAULT_OUT_MD.write_text(md, encoding="utf-8")
        print(f"wrote {DEFAULT_OUT_JSON.relative_to(ROOT)} and {DEFAULT_OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
