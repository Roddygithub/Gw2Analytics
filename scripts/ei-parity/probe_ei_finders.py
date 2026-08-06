#!/usr/bin/env python3
"""Score a transcribed Elite Insights ``InstantCastFinder`` against EI's own output.

The three earlier attempts at the ``rotation`` bucket all failed the same
way: a trigger that *covers* every cast is not a trigger that fires *only*
on casts, and correlating our event stream against EI's cast list cannot
tell the two apart. The finders are declarative in EI's sources, so the
rule is read from there and only *verified* here.

For each rule this reports, over the whole corpus, how many of EI's casts
the rule reproduces, how many it misses, and how many it invents. A rule
worth wiring covers everything and invents nothing.

Usage: probe_ei_finders.py [rule ...]   (default: every rule)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from gw2_core import (  # noqa: E402
    ActivationType,
    BoonApplyEvent,
    EffectEvent,
    Profession,
    SkillActivationEvent,
)
from gw2_evtc_parser import PythonEvtcParser, read_zevtc_archive  # noqa: E402

#: EI's ``ParserHelper.ServerDelayConstant``.
SERVER_DELAY = 10
#: EI's ``InstantCastFinder.DefaultICD``.
DEFAULT_ICD = 50

GUARDIAN_SHOUT = "122BA55CCDF2B643929F6C4A97226DC9"
CLEANSING_FIRE_1 = "BFFE3477ECFA26458D69E93EE76EFF6B"
CLEANSING_FIRE_2 = "61F5669F9FAC1F48B47635C9F3833CEF"
CLEANSING_FIRE_3 = "ABF2332D28C7D6449A5B822E5714ADA4"

AEGIS = 743
STABILITY = 1122

#: ``MinionCastCastFinder(playerSkill, petSkill)`` from ``EvokerHelper``.
EVOKER_FAMILIARS = {
    76882: 76643,  # Ignite
    76709: 77225,  # Splash
    76803: 77370,  # Zap
    76925: 77226,  # Calcify
}


def _apply_icd(hits: list[tuple[int, int]], icd: int = DEFAULT_ICD) -> list[tuple[int, int]]:
    """Gate ``(agent, time)`` hits per agent the way ``EffectCastFinder`` does.

    EI reassigns ``lastTime`` on the *suppressed* event too, so a burst of
    sub-ICD effects slides the window forward instead of anchoring it on
    the first one. Reproducing that matters: anchoring instead lets the
    tail of a burst through.
    """
    last: dict[int, int] = {}
    kept: list[tuple[int, int]] = []
    for agent, time in sorted(hits, key=lambda hit: (hit[0], hit[1])):
        previous = last.get(agent)
        last[agent] = time
        if previous is not None and time - previous < icd:
            continue
        kept.append((agent, time))
    return kept


class Log:
    """One corpus log, parsed once and indexed for every rule."""

    def __init__(self, stem: str) -> None:
        raw = read_zevtc_archive(ROOT / "zevtc files" / f"{stem}.zevtc")
        parser = PythonEvtcParser()
        self.stem = stem
        self.fight = next(parser.parse(raw))
        self.events = list(parser.parse_events(raw))
        self.ei = json.loads(
            (ROOT / ".tooling" / "ei-out" / f"{stem}_detailed_wvw_kill.json").read_text()
        )
        # The fight origin is the log's declared start, not the first event
        # we emit: on three corpus logs the first raw record is a statechange
        # ``parse_events`` drops, and taking the first emitted event instead
        # shifts every cast 1 ms late.
        header = self.fight.header
        self.origin = (
            header.start_time_ms
            if header is not None and header.start_time_ms is not None
            else min(event.time_ms for event in self.events)
        )
        self.player_instances = {player["instanceID"] for player in self.ei["players"]}

        self.profession = {agent.id: agent.profession for agent in self.fight.agents}
        self.agents_by_inst: dict[int, set[int]] = defaultdict(set)
        for agent in self.fight.agents:
            if agent.instance_id:
                self.agents_by_inst[agent.instance_id].add(agent.id)

        self.effects_by_guid: dict[str, list[EffectEvent]] = defaultdict(list)
        self.aegis_applies: list[BoonApplyEvent] = []
        self.stability_applies: list[BoonApplyEvent] = []
        self.casts_by_skill: dict[int, list[SkillActivationEvent]] = defaultdict(list)
        for event in self.events:
            if isinstance(event, EffectEvent):
                self.effects_by_guid[event.guid].append(event)
            elif isinstance(event, BoonApplyEvent) and event.kind == "apply":
                if event.skill_id == AEGIS:
                    self.aegis_applies.append(event)
                elif event.skill_id == STABILITY:
                    self.stability_applies.append(event)
            elif isinstance(event, SkillActivationEvent) and event.skill_id in EVOKER_FAMILIARS:
                self.casts_by_skill[event.skill_id].append(event)

    def expected(self, skill_id: int) -> set[tuple[int, int]]:
        """EI's own casts of ``skill_id`` as ``(instance_id, fight-relative ms)``."""
        out: set[tuple[int, int]] = set()
        for player in self.ei["players"]:
            for group in player.get("rotation") or []:
                if group.get("id") != skill_id:
                    continue
                for cast in group.get("skills") or []:
                    out.add((player["instanceID"], cast["castTime"]))
        return out

    def to_instance(self, hits: list[tuple[int, int]]) -> set[tuple[int, int]]:
        """Map ``(agent, absolute ms)`` onto EI's ``(instance, relative ms)`` space."""
        inst_of = {
            agent_id: inst
            for inst, agent_ids in self.agents_by_inst.items()
            for agent_id in agent_ids
        }
        return {
            (inst_of[agent], time - self.origin)
            for agent, time in hits
            if agent in inst_of and inst_of[agent] in self.player_instances
        }


def rule_advance(log: Log) -> list[tuple[int, int]]:
    """``EffectCastFinderByDst(Advance, GuardianShout)``.

    Keyed on the effect's *destination*, gated on the destination being a
    guardian, and told apart from the other guardian shouts by a
    self-applied aegis of 20 to 40 seconds.
    """
    hits = []
    for effect in log.effects_by_guid.get(GUARDIAN_SHOUT, ()):
        dst = effect.target_agent_id
        if not effect.is_around_dst or log.profession.get(dst) != Profession.GUARDIAN:
            continue
        if any(
            apply.source_agent_id == dst
            and apply.target_agent_id == dst
            and abs(apply.time_ms - effect.time_ms) < SERVER_DELAY
            and apply.duration_ms + SERVER_DELAY >= 20_000
            and apply.duration_ms - SERVER_DELAY <= 40_000
            for apply in log.aegis_applies
        ):
            hits.append((dst, effect.time_ms))
    return _apply_icd(hits)


def rule_stand_your_ground(log: Log) -> list[tuple[int, int]]:
    """``EffectCastFinderByDst(StandYourGround, GuardianShout)``, five-plus self-stabs."""
    hits = []
    for effect in log.effects_by_guid.get(GUARDIAN_SHOUT, ()):
        dst = effect.target_agent_id
        if not effect.is_around_dst or log.profession.get(dst) != Profession.GUARDIAN:
            continue
        stacks = sum(
            apply.source_agent_id == dst
            and apply.target_agent_id == dst
            and abs(apply.time_ms - effect.time_ms) < SERVER_DELAY
            for apply in log.stability_applies
        )
        if stacks >= 5:
            hits.append((dst, effect.time_ms))
    return _apply_icd(hits)


def rule_cleansing_fire(log: Log) -> list[tuple[int, int]]:
    """``EffectCastFinderByDst(CleansingFire, ...1)`` + two same-agent secondaries.

    The secondary check compares EI's *key* agent, which for a by-dst
    finder is the effect's destination -- not its source.
    """
    hits = []
    for effect in log.effects_by_guid.get(CLEANSING_FIRE_1, ()):
        dst = effect.target_agent_id
        if not effect.is_around_dst or log.profession.get(dst) != Profession.ELEMENTALIST:
            continue
        if all(
            any(
                other is not effect
                and other.target_agent_id == dst
                and abs(other.time_ms - effect.time_ms) < SERVER_DELAY
                for other in log.effects_by_guid.get(guid, ())
            )
            for guid in (CLEANSING_FIRE_2, CLEANSING_FIRE_3)
        ):
            hits.append((dst, effect.time_ms))
    return _apply_icd(hits)


def rule_evoker_familiars(log: Log) -> list[tuple[int, int]]:
    """``MinionCastCastFinder(playerSkill, petSkill)`` for the four familiar skills.

    EI never reassigns ``lastTime`` after an accepted cast here, so its ICD
    only ever suppresses a cast that follows a *suppressed* one -- which is
    never. The gate is reproduced as written rather than as intended.
    """
    inst_to_agent = {agent.instance_id: agent.id for agent in log.fight.agents if agent.instance_id}
    hits = []
    for pet_skill in EVOKER_FAMILIARS:
        for cast in log.casts_by_skill.get(pet_skill, ()):
            if cast.activation not in (ActivationType.NORMAL, ActivationType.QUICKNESS):
                continue
            owner = inst_to_agent.get(cast.src_master_instid)
            if owner:
                hits.append((owner, cast.time_ms))
    return hits


RULES = {
    "advance": (9084, rule_advance),
    "stand-your-ground": (9153, rule_stand_your_ground),
    "cleansing-fire": (5535, rule_cleansing_fire),
    "evoker-familiars": (0, rule_evoker_familiars),
}


def main() -> int:
    wanted = sys.argv[1:] or list(RULES)
    stems = sorted(
        path.name.split("_detailed")[0]
        for path in (ROOT / ".tooling" / "ei-out").glob("*_detailed_wvw_kill.json")
    )

    totals: dict[str, list[int]] = {name: [0, 0, 0] for name in wanted}
    for stem in stems:
        log = Log(stem)
        for name in wanted:
            skill_id, rule = RULES[name]
            predicted = log.to_instance(rule(log))
            if name == "evoker-familiars":
                # One rule covers four skills; score them together by
                # comparing the union, since the familiar skill fixes the
                # player skill and a mis-paired one would show on both sides.
                expected = set()
                for player_skill in EVOKER_FAMILIARS.values():
                    expected |= log.expected(player_skill)
            else:
                expected = log.expected(skill_id)
            covered = len(predicted & expected)
            missing = len(expected - predicted)
            extra = len(predicted - expected)
            totals[name][0] += covered
            totals[name][1] += missing
            totals[name][2] += extra
            if missing or extra:
                print(f"  {stem:<16} {name:<18} +{covered} -{missing} !{extra}")

    print()
    for name in wanted:
        covered, missing, extra = totals[name]
        verdict = "EXACT" if not missing and not extra else "mismatch"
        print(f"{name:<18} covered={covered:<5} missing={missing:<5} extra={extra:<5} {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
