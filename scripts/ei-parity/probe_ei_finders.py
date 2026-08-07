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
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from gw2_core import (  # noqa: E402
    ActivationType,
    BoonApplyEvent,
    DamageEvent,
    EffectEvent,
    MissileEvent,
    Profession,
    SkillActivationEvent,
    WeaponSwapEvent,
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
REAPERS_SHROUD = 29446
DESERT_SHROUD = 40052
UNHOLY_BURST = 38767
SPITEFUL_SPIRIT_EFFECT = "C4E8DD3234E0C647993857940ED79AC1"
SYMBOL_OF_PROTECTION = 9161
SYMBOL_OF_PROTECTION_EFFECTS = (
    "8321373FA14B2B4B8761CDC6EEADB161",
    "E10D2D0DF7803146A69BBB5BD47944FC",
)

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
        self.buff_losses: dict[int, list[BoonApplyEvent]] = defaultdict(list)
        self.buff_gains: dict[int, list[BoonApplyEvent]] = defaultdict(list)
        self.desert_shroud_losses: list[int] = []
        self.unholy_burst_hits: list[DamageEvent] = []
        self.damage_by_skill: dict[int, list[DamageEvent]] = defaultdict(list)
        self.missile_by_skill: dict[int, list[MissileEvent]] = defaultdict(list)
        self.swaps_by_agent: dict[int, list[int]] = defaultdict(list)
        self.symbol_activations: list[SkillActivationEvent] = []
        for event in self.events:
            self._index(event)

    def _index(self, event: object) -> None:
        """File one event under every bucket a rule reads from."""
        if isinstance(event, EffectEvent):
            self.effects_by_guid[event.guid].append(event)
        elif isinstance(event, BoonApplyEvent):
            self._index_buff(event)
        elif isinstance(event, DamageEvent) and event.skill_id == UNHOLY_BURST:
            self.unholy_burst_hits.append(event)
        elif isinstance(event, DamageEvent):
            self.damage_by_skill[event.skill_id].append(event)
        elif isinstance(event, MissileEvent):
            self.missile_by_skill[event.skill_id].append(event)
        elif isinstance(event, SkillActivationEvent):
            if event.skill_id in EVOKER_FAMILIARS:
                self.casts_by_skill[event.skill_id].append(event)
            elif event.skill_id == SYMBOL_OF_PROTECTION:
                self.symbol_activations.append(event)
        elif isinstance(event, WeaponSwapEvent):
            self.swaps_by_agent[event.source_agent_id].append(event.time_ms)

    def _index_buff(self, event: BoonApplyEvent) -> None:
        if event.kind == "apply":
            self.buff_gains[event.skill_id].append(event)
            if event.skill_id == AEGIS:
                self.aegis_applies.append(event)
            elif event.skill_id == STABILITY:
                self.stability_applies.append(event)
        elif event.kind == "remove_all":
            self.buff_losses[event.skill_id].append(event)
            if event.skill_id == DESERT_SHROUD:
                self.desert_shroud_losses.append(event.time_ms)

    def before_weapon_swap(self, agent: int, time: int) -> int:
        """EI's ``UsingBeforeWeaponSwap``: pull the cast just ahead of a swap.

        The swap has to be within half a server delay, and the result is the
        *earlier* of the two -- a cast already before the swap is left alone
        rather than pushed forward onto it.
        """
        for swap_time in self.swaps_by_agent.get(agent, ()):
            if abs(swap_time - time) < SERVER_DELAY / 2:
                return min(swap_time - 1, time)
        return time

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


def _damage_rule(skill_id: int, icd: int = DEFAULT_ICD) -> Callable[[Log], list[tuple[int, int]]]:
    """``DamageCastFinder(Skill)``: damage from Skill implies the skill was cast."""

    def rule(log: Log) -> list[tuple[int, int]]:
        return _apply_icd(
            [(e.source_agent_id, e.time_ms) for e in log.damage_by_skill.get(skill_id, ())],
            icd,
        )

    return rule


def _effect_rule(guid: str, key_on: str = "src") -> Callable[[Log], list[tuple[int, int]]]:
    """``EffectCastFinder(Skill, EffectGUID)``: one effect created books one cast.

    ``key_on`` mirrors EI's choice of which agent the finder is indexed on:
    ``"dst"`` for the ByDst variants, ``"src"`` otherwise. ``IsAroundDst``
    finders only fire when the effect is around a destination.
    """

    def rule(log: Log) -> list[tuple[int, int]]:
        hits = []
        for effect in log.effects_by_guid.get(guid, ()):
            if key_on == "dst" and not effect.is_around_dst:
                continue
            agent = effect.target_agent_id if key_on == "dst" else effect.source_agent_id
            hits.append((agent, effect.time_ms))
        return _apply_icd(hits)

    return rule


def _missile_rule(skill_id: int) -> Callable[[Log], list[tuple[int, int]]]:
    """``MissileCastFinder(Skill)``: a missile of Skill implies the skill was cast."""

    def rule(log: Log) -> list[tuple[int, int]]:
        return _apply_icd(
            [(e.source_agent_id, e.time_ms) for e in log.missile_by_skill.get(skill_id, ())]
        )

    return rule


def _buff_give_rule(buff_id: int) -> Callable[[Log], list[tuple[int, int]]]:
    """``BuffGiveCastFinder(Skill, Buff)``: the source gave the buff to another."""

    def rule(log: Log) -> list[tuple[int, int]]:
        hits = [
            (e.source_agent_id, e.time_ms)
            for e in log.buff_gains[buff_id]
            if e.source_agent_id != e.target_agent_id
        ]
        return _apply_icd(hits)

    return rule


def _buff_gain_rule(buff_id: int) -> Callable[[Log], list[tuple[int, int]]]:
    """``BuffGainCastFinder(Skill, BuffID)``: the buff is self-applied at cast."""

    def rule(log: Log) -> list[tuple[int, int]]:
        return [
            (e.target_agent_id, e.time_ms)
            for e in log.buff_gains[buff_id]
            if e.source_agent_id == e.target_agent_id
        ]

    return rule


def _exit_shroud_rule(buff_ids: int | set[int]) -> Callable[[Log], list[tuple[int, int]]]:
    """``BuffLossCastFinder(_, BuffID).UsingBeforeWeaponSwap()``.

    Only a *full* removal counts -- the finder is typed on
    ``BuffRemoveAllEvent`` -- and the cast is pulled just ahead of the
    weapon swap the exit triggers (reaper shroud, celestial avatar, beast
    mode, photon forge, the tomes...). ``buff_ids`` is one buff or several,
    e.g. the three Firebrand tomes all route through ``StowTome``. The ICD
    is gated on the raw removal time, before that adjustment.
    """
    buffs = {buff_ids} if isinstance(buff_ids, int) else buff_ids

    def rule(log: Log) -> list[tuple[int, int]]:
        hits = []
        for buff_id in buffs:
            hits += _apply_icd(
                [(e.target_agent_id, e.time_ms) for e in log.buff_losses[buff_id]]
            )
        return [(agent, log.before_weapon_swap(agent, time)) for agent, time in hits]

    return rule


def rule_exit_reaper_shroud(log: Log) -> list[tuple[int, int]]:
    """``BuffLossCastFinder(ExitReaperShroud, ReapersShroud).UsingBeforeWeaponSwap()``.

    Kept under its own name because one corpus log books two exits while
    EI books one; the shroud has a re-enter within the server-delay
    ``UsingBeforeWeaponSwap`` half-window and EI's ICD drops the second.
    The generic rule does the same only for the atomic case.
    """
    hits = _apply_icd(
        [(loss.target_agent_id, loss.time_ms) for loss in log.buff_losses[REAPERS_SHROUD]]
    )
    return [(agent, log.before_weapon_swap(agent, time)) for agent, time in hits]


def rule_spiteful_spirit(log: Log) -> list[tuple[int, int]]:
    """``EffectCastFinder(SpitefulSpirit, NecromancerUnholyBurst)``.

    One effect serves both Unholy Burst and Spiteful Spirit. Unholy Burst
    only ever fires when it hits something, so a nearby hit of it rules the
    effect out; the desert-shroud check disambiguates the scourge collision
    and is deliberately global, not per-agent, in Elite Insights.
    """
    hits = []
    for effect in log.effects_by_guid.get(SPITEFUL_SPIRIT_EFFECT, ()):
        src = effect.source_agent_id
        if log.profession.get(src) != Profession.NECROMANCER:
            continue
        if any(abs(time - effect.time_ms) < 50 for time in log.desert_shroud_losses):
            continue
        if any(
            hit.source_agent_id == src and abs(hit.time_ms - effect.time_ms) < SERVER_DELAY
            for hit in log.unholy_burst_hits
        ):
            continue
        hits.append((src, effect.time_ms))
    return _apply_icd(hits)


def _cast_windows(activations: list[SkillActivationEvent]) -> dict[int, list[tuple[int, int]]]:
    """Rebuild ``(start, end)`` animated-cast windows per caster."""
    open_cast: dict[int, int] = {}
    windows: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for event in activations:
        agent = event.source_agent_id
        if event.activation in (ActivationType.NORMAL, ActivationType.QUICKNESS):
            open_cast[agent] = event.time_ms
        else:
            start = open_cast.pop(agent, event.time_ms - event.duration_ms)
            windows[agent].append((start, event.time_ms))
    for agent, start in open_cast.items():
        windows[agent].append((start, start))
    return windows


def rule_lesser_symbol_of_protection(log: Log) -> list[tuple[int, int]]:
    """``EffectCastFinder(LesserSymbolOfProtection, ...).UsingNoAnimatedCastChecker``.

    The trait version places the same symbol as the real skill, so an
    effect that falls inside a 9161 cast window belongs to the skill and
    must not be booked as the trait proc. EI's window test is inclusive of
    a server delay on both ends.
    """
    windows = _cast_windows(log.symbol_activations)
    hits = []
    for guid in SYMBOL_OF_PROTECTION_EFFECTS:
        for effect in log.effects_by_guid.get(guid, ()):
            src = effect.source_agent_id
            if any(
                effect.time_ms >= start - SERVER_DELAY and end + SERVER_DELAY >= effect.time_ms
                for start, end in windows.get(src, ())
            ):
                continue
            hits.append((src, effect.time_ms))
    return _apply_icd(hits)


def rule_signet_of_air(log: Log) -> list[tuple[int, int]]:
    """Union of EI's DamageCastFinder + EffectCastFinderByDst(SignetOfAir)."""
    hits = [(e.source_agent_id, e.time_ms) for e in log.damage_by_skill.get(5572, ())]
    hits += [
        (e.target_agent_id, e.time_ms)
        for e in log.effects_by_guid.get("30A96C0E559DBD489FEE36DA96CC374A", ())
        if e.is_around_dst
    ]
    return _apply_icd(hits)


def rule_infiltrators_signet(log: Log) -> list[tuple[int, int]]:
    """``EffectCastFinderByDst(InfiltratorsSignet, ThiefInfiltratorsSignet1)``
    + ``UsingDstBaseSpecChecker(Thief)`` + ``UsingSecondaryEffectSameSrcChecker(GUID2)``.
    """
    hits, seen = [], set()
    for effect in log.effects_by_guid.get("23284B87C26C9A41A887F410F930E1A2", ()):
        dst = effect.target_agent_id
        if not effect.is_around_dst or log.profession.get(dst) != Profession.THIEF:
            continue
        if not any(
            abs(other.time_ms - effect.time_ms) < SERVER_DELAY
            and other.source_agent_id == effect.source_agent_id
            for other in log.effects_by_guid.get("2C89A39F7B88614ABED16D4B5A5BD2EB", ())
        ):
            continue
        hit = (dst, effect.time_ms)
        if hit in seen:
            continue
        seen.add(hit)
        hits.append(hit)
    return _apply_icd(hits)


RULES = {
    "lesser-symbol-of-protection": (13684, rule_lesser_symbol_of_protection),
    "spiteful-spirit": (29560, rule_spiteful_spirit),
    "exit-reaper-shroud": (30961, rule_exit_reaper_shroud),
    "advance": (9084, rule_advance),
    "stand-your-ground": (9153, rule_stand_your_ground),
    "cleansing-fire": (5535, rule_cleansing_fire),
    "evoker-familiars": (0, rule_evoker_familiars),

    # BuffLossCastFinder shroud/tome exits -- buff IDs read off SkillIDs.cs.
    "exit-death-shroud": (10585, _exit_shroud_rule(790)),
    "exit-harbinger-shroud": (62540, _exit_shroud_rule(59964)),
    "exit-shadow-shroud": (63251, _exit_shroud_rule(63239)),
    "exit-celestial-avatar": (31411, _exit_shroud_rule(31508)),
    "exit-radiant-forge": (76616, _exit_shroud_rule(77142)),
    "stow-tome": (41380, _exit_shroud_rule({41493, 42404, 44291})),

    # BuffGainCastFinder(Skill, Buff) -- buff IDs read off SkillIDs.cs.
    "enter-reaper-shroud": (30792, _buff_gain_rule(29446)),
    "spectral-walk": (10685, _buff_gain_rule(53476)),
    "shadowstep": (13002, _buff_gain_rule(13135)),
    "dual-fire": (43470, _buff_gain_rule(43470)),
    "desert-shroud": (44663, _buff_gain_rule(40052)),
    "rocky-loop": (62975, _buff_gain_rule(62768)),
    "icy-coil": (62834, _buff_gain_rule(62984)),
    "crescent-wind": (62887, _buff_gain_rule(62707)),
    "weapon-of-remedy": (77022, _buff_gain_rule(78272)),
    "xinrae-weapon": (76941, _buff_gain_rule(78313)),
    "mist-form": (5543, _buff_gain_rule(5543)),
    "arcane-shield": (5641, _buff_gain_rule(5640)),
    "infusing-terror": (29958, _buff_gain_rule(30129)),
    "superior-sigil-of-severance": (43930, _buff_gain_rule(43930)),

    # EffectCastFinder(Skill, EffectGUID) -- GUIDs read off EffectGUIDs.cs.
    "deploy-water-jade-sphere": (62723, _effect_rule("6D7EB5747873484DAF29C01FA51FE175")),
    "deploy-air-jade-sphere": (62940, _effect_rule("A3C8A55C3E530140A7F99AAA1CBB4E09")),
    "tale-honorable-rogue": (76611, _effect_rule("DBECB5867D11264FA19FFCDC487A410E")),
    "syncopate-delayed-wave": (76689, _effect_rule("24498E18DEC97B4094376849EF7A3746")),
    "relic-holosmith": (75748, _effect_rule("DF03FACC6BA66F4BA89BA27636FB39EB")),
    "relic-sorrow": (74410, _effect_rule("3D981397D9C6A44B8898212CE4E3D6F9A")),
    "necromancer-distress": (73116, _effect_rule("239BF9EA9B7B44BACC63B86DC49B0D0")),
    "form-dervish": (76818, _effect_rule("B0CF6359EBF9BF4EB94E1A2A347EE5ECD")),
    "symbiotic-shielding": (76613, _effect_rule("842F977C318FDC4F96C99C385C1D0672")),

    # DamageCastFinder(Skill) -- self-keyed on the skill's own damage.
    "mug": (13014, _damage_rule(13014)),
    "lightning-flash": (5536, _damage_rule(5536)),
    "signet-of-air": (5572, rule_signet_of_air),
    "flame-expulsion": (13334, _damage_rule(13334)),
    "earthen-blast": (56885, _damage_rule(56885)),
    "overcharged-shot": (6154, _damage_rule(6154)),
    "focused-devastation": (73064, _damage_rule(73064)),
    "timebomb": (79359, _damage_rule(79359)),
    "unseen-sword": (62847, _damage_rule(62847)),

    # BuffGiveCastFinder(Skill, Buff).
    "vulture-stance": (40498, _buff_give_rule(44651)),
    "moa-stance": (45970, _buff_give_rule(45038)),
    "dolyak-stance": (45789, _buff_give_rule(41815)),
    "dimensional-aperture": (71792, _buff_give_rule(71890)),

    # MissileCastFinder(Skill), self-keyed on the missile's own skill.
    "blade-burst": (42163, _missile_rule(42163)),

    # More EffectCastFinder -- GUIDs resolved off EffectGUIDs.cs.
    "suffer": (30670, _effect_rule("6C8C388BCD26F04CA6618D2916B8D796")),
    "outrage": (30258, _effect_rule("AC32B7F7BB281B4D94713F180C44F322")),
    "mantra-of-resolve": (10207, _effect_rule("593E668A006AB24D84999AED68F2E4C4")),
    "shift-signet": (63111, _effect_rule("E1C1DD7F866B4149A1BADD216C9AA69D")),
    "bypass-coating": (29665, _effect_rule("D2307A69B227BE4B831C2AA1DAAE646A")),
    "eternal-bond": (59554, _effect_rule("BF0A5B11A4076A4F98C6E1D655D507B1")),
    "infiltrators-signet": (13064, rule_infiltrators_signet),
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
