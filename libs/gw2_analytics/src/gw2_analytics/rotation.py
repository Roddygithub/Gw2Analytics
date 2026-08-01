"""Build EI-style skill casts from raw EVTC activation and instant-cast signals."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Collection, Iterable

from pydantic import BaseModel, ConfigDict

from gw2_core import (
    ActivationType,
    BoonApplyEvent,
    DamageEvent,
    EffectEvent,
    Event,
    HealingEvent,
    MissileEvent,
    SkillActivationEvent,
    SpawnEvent,
    WeaponSwapEvent,
)

_WEAPON_ACTIVATIONS = {23284, 23285}
_ENGINEER_KIT_BUNDLES = {
    5802: {58090, 30521, 29547, 49045, 49082, 58104, 50444},
    5933: {5934, 5935, 5965, 5936, 6102, 5937},
    5927: {5928, 5929, 5930, 5931, 76493},
    30800: {30371, 30885, 30307, 30121, 30032},
}
_INSTANT_CASTS_BY_BUFF = {
    29446: (30792, True),  # Reaper's Shroud, immediately before its weapon swap
    30129: (29958, False),  # Infusing Terror
    76736: (77300, False),  # Valorous Stance
    77283: (77163, False),  # Defensive Protocol: Thorns
}
_BUFF_GAIN_CASTS = {
    883: 42470,
    10198: 10197,
    9441: 9441,
    12536: 12537,
    16553: 10199,
    40408: -17,
    5575: 5494,
    5580: 5495,
    5582: 5635,
    5586: 5493,
    5585: 5492,
    5863: 5861,
    9235: 9247,
    27376: 26644,
    27581: 27107,
    27732: 28085,
    27890: 28134,
    27928: 28494,
    27983: 27760,
    28036: 28379,
    28243: 27014,
    73955: 73955,
    790: 10574,
    30136: 29830,
    76559: 77371,
    77142: 77073,
    76958: 77238,
    41493: 41780,
    42404: 42259,
    44291: 44364,
    787: 14392,
    77234: 76610,
    27205: 28419,
    27273: 26557,
    29703: 29703,
    31508: 31869,
    34778: 14412,
    40052: 54870,
    42311: 40274,
    40069: 42944,
    40272: 42944,
    41720: 42944,
    44693: 42944,
    44932: 42944,
    33162: 31129,
    59964: 62567,
    63239: 63155,
    63317: 63147,
    71431: 71431,
    73071: 73037,
    63145: 63344,
    77095: 76813,
    76351: 76351,
    76868: 77321,
    77362: 77018,
}
_BUFF_LOSS_CASTS = {
    29446: 30961,
    790: 10585,
    30136: 30747,
    40069: 43014,
    40272: 43014,
    41720: 43014,
    44693: 43014,
    44932: 43014,
    27581: 28382,
    73955: -40,
    69855: -32,
    77142: 76616,
    76958: 76933,
    41493: 41380,
    42404: 41380,
    44291: 41380,
    27273: 26956,
    31508: 31411,
    59579: 59562,
    59964: 62540,
    63239: 63251,
    77265: 76730,
}
_BUFF_GIVE_CASTS = {41815: 45789, 70350: 70350}
_DAMAGE_CASTS = {
    5561: 50,
    9292: 500,
    9428: 500,
    9433: 500,
    9101: 50,
    9284: 500,
    13906: 50,
    14268: 50,
    22499: 50,
    26261: 50,
    29414: 50,
    29604: 50,
    31289: 50,
    38767: 50,
    41612: 50,
    46843: 50,
    46856: 50,
    46857: 50,
    45534: 50,
    45449: 50,
    56883: 50,
    59591: 50,
    77021: 50,
}
_DAMAGE_CASTS_BY_DAMAGE = {40071: 44428, 46808: 40813}
_HEALING_CASTS = {
    12542,
    12631,
    12825,
    12836,
    13594,
    13629,
    13980,
    14282,
    20462,
    24061,
    70765,
    70001,
    71356,
    72115,
}
_MISSILE_CASTS = {26261, 29889}
_BEFORE_SWAP_BUFFS = {31508, 59964, 63239, 77142, 76958, 41493, 42404, 44291}
_AFTER_SWAP_BUFFS = {29703}
_INSTANT_CASTS_BY_EFFECT = {
    "C4E8DD3234E0C647993857940ED79AC1": 29560,  # Spiteful Spirit
    "0BC4AABB74F2AC43963CBB7B52993559": 76607,
    "6E2B9CF3E5C95846B15BBD1EAA9B3E98": 72076,
    "B23157C515072E46B5514419B0F923B7": 12550,
    "8321373FA14B2B4B8761CDC6EEADB161": 13684,
    "863E477DA639694AB23E873D93E1B0AE": 76850,
    "2A1D0C23F448C348A83E9A4F2669B73F": 70491,
    "D43DC34DEF81B746BC130F7A0393AAC7": 5639,
    "2BC033D40C0AEB40A77EEF28D51AE263": 69855,
    "0131D1C31514044381C4F7F2DF009C30": 5780,
    "3D01B04C5700904BA279E9F135A3FAB3": -21,
    "8F0C77784AFD7F40B27446617DC05CDC": -20,
    "86CC98C9D9D2B64689F8993AB02B09E5": -23,
    "5B488D552E316045AD99C4A98EEDDB1E": 10238,
    "98E9E5F26FF76F449A181654E4F39695": 77003,
    "A8FA2AFABB3FC840893E441F47693524": 76732,
    "81146A66FCE3A342B00D4D2EB2A7643E": 76602,
    "2DD44AFA1B4A6947AD63CB785CF9B172": 77178,
    "69ACA314CE3DB04D9B5A67324E6F0A57": 76611,
    "87B761200637AC48B71469F553BA6F60": 62597,
    "E4002B7AD7DF024394D0184B47A316E7": 24755,
    "75EF160EAFC0394CACC436CF89819148": 14404,
    "42C2B92716D9174EBC43420D1D55FB92": 76769,
    "44092AEF6D619F4093FEA4E9D9142D01": 43448,
    "885B7AAA68F09E48A926BFFE488DB5AD": -37,
    "19C4FA17A38E7E4780722799B48BF2BE": 31406,
    "98C9834C6381204A85DC67C375D135E4": 13677,
    "13D0B65D73B5334D80824EE17B5C257E": 13677,
    "FB78801BB31CAF488B55F2F57EF9B070": 78837,
    "4A83F0B627B75C47894941C4D35BA89F": 78604,
    "03850757F14FD44A9998D4CAD71CC589": 78358,
    "611D90C69ECF8142BEEE84139F333388": 30101,
    "C6A40B12F9E6E046A98223F30E717633": 30101,
    "9E2D190A92E2B5498A88722910A9DECD": 30027,
    "F53F05F041957A47AD62B522FE030408": 45537,
    "B63D192DED78B1489DDB6E742D603CE5": 45537,
    "FB066A1F03294D4D850D22B26650FFA9": 77164,
    "3A5A38C26A1FFB438EAD734F3ED42E5E": 45449,
    "37242DF51D238A409E822E7A1936D7A6": 29414,
    "2C40B0741111444F98895A658A7F978F": 63258,
    "71B04F91F9B3DF4A8954059FCFAD630E": 72363,
    "E725FC2FD486A84EBEAC403DB4DA30DE": 72359,
    "72FC15613B4B2C44A1906617998859F9": 72389,
    "C8FDB04E59C1034CABEFBECE470AA1BC": 72366,
    "52F65A4D9970954BA849CB57A46A65A8": 10190,
    "916D8385083F144EBAA5BEEDE21FD47A": 10287,
    "C035166E3E4C414ABE640F47797D9B4A": 56930,
    "DC1C8A043ADCD24B9458688A792B04BA": 56928,
    "AB2E22E7EE74DA4C87DA777C62E475EA": 56873,
    "C1F1E386CC1E0B448435269DBBFB34D7": 76787,
    "25908EB455863D43AE70FB3F4A22D6E4": -39,
    "40C9F5FE5BD3BD449B5E48DF1E5FD348": 73149,
    "0DBE4F7115EADC4889F1E00232B2398B": 29739,
    "86DC533FBB84BC43BBA03EC3B3E13034": 29739,
    "3CF1D1228CBC3740AA33EDA357EABED4": 12494,
    "28346F32FD199C4B8F9B15438F27A434": 31749,
    "D7006AC247BBE74BA54E912188EF6B12": 29786,
    "AFC5D5C7DA63D64BAAD55F787205B64F": 62813,
    "A674D3E7BC0C4342BC7A4EF0EE8FF8F0": 62837,
    "842F977C318FDC4F96C99C385C1D0672": 76613,
    "EEDCAB61CD35E840909B03D398878B1C": 62660,
    "F2FB8A03178A2B43B82E0113F20DF932": 76798,
    "FA37E0B77272314AA1ADCFF824F24C27": 79336,
    "8B05122882E53242A4D4725F0A1537A4": 79336,
    "60BE4692A455B140A05AD794BF4753F6": 63209,
    "F2B1B61970FC59418AC049BF3A07FFD4": 63094,
    "C668B5DB6220D9448817B3E5F7DE6E46": 30662,
    "52FEF389CF7D014BAA375EACF1826BB6": 30047,
    "0D388D23FF313F489794881A540E5A24": 41612,
    "5E77D6C93F3D0747B0B81169C7C0E506": 31289,
    "1066BEACB107C743908D860DA2D59796": 71252,
    "E78ED095E97F1D4A8BEB901796449E2F": 10562,
}
_EFFECT_CASTS_BY_DST = {
    "122BA55CCDF2B643929F6C4A97226DC9": 9153,
    "95B52793B838524AB237EB9FED7834BF": -22,
    "F53E2CE3B06B934085D46FA59468477B": 10214,
    "EA9896A81DDF4843B18DBF6EE4F25E18": 12502,
    "9B8A1BE554450B4899B64F7579DF0A8C": 31658,
    "74870558C43E4747955C573CAAC630A7": 31401,
    "734834E7EB7CD74EB129ACBCE5C64C1D": 63095,
    "956450E1260FB94B8691BC1378086250": 63293,
    "9C06D9D9B0E22247A1752C426808CD80": 62671,
    "1A38CAE72C2F164BA3815441CA643A20": 12542,
    "75D72E2DA47ECF47A6BD009B49B7C708": 9248,
    "D7DCD4ABF9E4A749950AF0175E02EA06": 63256,
    "02154B72900B5740A73CD0ADECED27BF": 10234,
    "9242D10B4F04274EB6E9EBCDB2262181": 77213,
    "B02D3D0FF0A4FC47B23B1478D8E770AE": -29,
}
_SECONDARY_EFFECTS = {
    "FB78801BB31CAF488B55F2F57EF9B070": ("7535B4CB815232418B69092F3390A7AB",),
    "4A83F0B627B75C47894941C4D35BA89F": ("FBA4C4F041E78748AC1CA5FF5D37D2DA",),
    "03850757F14FD44A9998D4CAD71CC589": ("08E6D231507CDD458EDECF67D264228C",),
    "FB066A1F03294D4D850D22B26650FFA9": ("D23CB7F8A2755F4FA2A68A6834ABAD98",),
    "3A5A38C26A1FFB438EAD734F3ED42E5E": (
        "B6557C336041B24FA7CC198B6EBDAD9A",
        "D7A05478BA0E164396EB90C037DCCF42",
    ),
    "37242DF51D238A409E822E7A1936D7A6": (
        "FEE4F26C2866E34C9D75506A8ED94F5E",
        "ED6A8440CB49B248A352B2073FAF1F5F",
    ),
    "C035166E3E4C414ABE640F47797D9B4A": ("4C7A5E148F7FD642B34EE4996DDCBBAB",),
    "DC1C8A043ADCD24B9458688A792B04BA": ("4C7A5E148F7FD642B34EE4996DDCBBAB",),
    "AB2E22E7EE74DA4C87DA777C62E475EA": ("4C7A5E148F7FD642B34EE4996DDCBBAB",),
    "40C9F5FE5BD3BD449B5E48DF1E5FD348": ("1B3ACEE36F61DE42AB1C24BD33B5B5AD",),
}
_BASE_SKILL_BY_ENHANCED_EFFECT = {
    "71B04F91F9B3DF4A8954059FCFAD630E": 42949,
    "E725FC2FD486A84EBEAC403DB4DA30DE": 40485,
    "72FC15613B4B2C44A1906617998859F9": 45686,
    "C8FDB04E59C1034CABEFBECE470AA1BC": 41220,
}
_MESMER_SHATTER_EFFECTS = {
    "52F65A4D9970954BA849CB57A46A65A8",
    "916D8385083F144EBAA5BEEDE21FD47A",
    "3D29ABD39CB5BD458C4D50A22FCC0E4B",
}
_MESMER_CLONE_SHATTER_EFFECT = "5FA6527231BB8041AC783396142C6200"


class SkillCast(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent_id: int
    skill_id: int
    time_ms: int
    duration_ms: int


def build_skill_rotation(  # noqa: PLR0912, PLR0915
    events: Iterable[Event],
    duration_ms: int,
    start_time_ms: int | None = None,
    virtuoso_agent_ids: Collection[int] = (),
    mesmer_agent_ids: Collection[int] = (),
    clone_agent_ids: Collection[int] = (),
    ranger_pet_agent_ids: Collection[int] = (),
    siege_turtle_agent_ids: Collection[int] = (),
) -> list[SkillCast]:
    """Return completed, clipped casts ordered by fight-relative start time."""
    event_list = list(events)
    if not event_list:
        return []
    origin = start_time_ms if start_time_ms is not None else min(e.time_ms for e in event_list)
    event_times = [event.time_ms for event in event_list]
    swaps_by_agent: dict[int, list[WeaponSwapEvent]] = defaultdict(list)
    activations_by_agent: dict[int, list[SkillActivationEvent]] = defaultdict(list)
    spawn_owner_by_target: dict[int, int] = {}
    for indexed_event in event_list:
        if isinstance(indexed_event, WeaponSwapEvent):
            swaps_by_agent[indexed_event.source_agent_id].append(indexed_event)
        elif isinstance(indexed_event, SkillActivationEvent):
            activations_by_agent[indexed_event.source_agent_id].append(indexed_event)
        elif isinstance(indexed_event, SpawnEvent):
            spawn_owner_by_target.setdefault(
                indexed_event.target_agent_id,
                indexed_event.source_agent_id,
            )
    swap_times_by_agent = {
        agent_id: [swap.time_ms for swap in agent_swaps]
        for agent_id, agent_swaps in swaps_by_agent.items()
    }
    active: dict[tuple[int, int], SkillActivationEvent] = {}
    casts: list[SkillCast] = []
    last_instant: dict[tuple[int, int], int] = {}
    active_buff_until: dict[tuple[int, int], int] = {}

    def nearby_events(time_ms: int, radius_ms: int) -> list[Event]:
        return event_list[
            bisect_left(event_times, time_ms - radius_ms) : bisect_right(
                event_times,
                time_ms + radius_ms,
            )
        ]

    def nearby_swap(agent_id: int, time_ms: int, radius_ms: int = 5) -> WeaponSwapEvent | None:
        agent_swaps = swaps_by_agent.get(agent_id, [])
        agent_swap_times = swap_times_by_agent.get(agent_id, [])
        for swap in agent_swaps[
            bisect_left(agent_swap_times, time_ms - radius_ms) : bisect_right(
                agent_swap_times,
                time_ms + radius_ms,
            )
        ]:
            if abs(swap.time_ms - time_ms) < radius_ms:
                return swap
        return None

    def next_swap_time_after(agent_id: int, time_ms: int) -> int:
        agent_swap_times = swap_times_by_agent.get(agent_id, [])
        index = bisect_right(agent_swap_times, time_ms + 10)
        return agent_swap_times[index] if index < len(agent_swap_times) else 1 << 63

    def add_instant(source: int, skill_id: int, time_ms: int, icd: int = 50) -> None:
        key = (source, skill_id)
        if time_ms - last_instant.get(key, -(1 << 63)) >= icd:
            casts.append(
                SkillCast(
                    source_agent_id=source,
                    skill_id=skill_id,
                    time_ms=time_ms - origin,
                    duration_ms=0,
                )
            )
        last_instant[key] = time_ms

    for event in event_list:
        if isinstance(event, SkillActivationEvent):
            key = (event.source_agent_id, event.skill_id)
            if event.activation in (ActivationType.NORMAL, ActivationType.QUICKNESS):
                if event.skill_id not in _WEAPON_ACTIVATIONS:
                    active[key] = event
            elif start := active.pop(key, None):
                cast_duration = event.time_ms - start.time_ms
                if cast_duration > 1:
                    casts.append(
                        SkillCast(
                            source_agent_id=event.source_agent_id,
                            skill_id=event.skill_id,
                            time_ms=start.time_ms - origin,
                            duration_ms=cast_duration,
                        )
                    )
            elif event.skill_id not in _WEAPON_ACTIVATIONS and event.duration_ms > 1:
                casts.append(
                    SkillCast(
                        source_agent_id=event.source_agent_id,
                        skill_id=event.skill_id,
                        time_ms=event.time_ms - event.duration_ms - origin,
                        duration_ms=event.duration_ms,
                    )
                )
        elif isinstance(event, WeaponSwapEvent):
            next_swap_time = next_swap_time_after(event.source_agent_id, event.time_ms)
            agent_activations = activations_by_agent.get(event.source_agent_id, [])
            activation_times = [activation.time_ms for activation in agent_activations]
            for kit_skill, bundle_skills in _ENGINEER_KIT_BUNDLES.items():
                if event.swapped_to == 2 and any(
                    other.skill_id in bundle_skills
                    for other in agent_activations[
                        bisect_left(activation_times, event.time_ms + 10) : bisect_left(
                            activation_times,
                            next_swap_time,
                        )
                    ]
                ):
                    add_instant(event.source_agent_id, kit_skill, event.time_ms - 1)
                    break
            casts.append(
                SkillCast(
                    source_agent_id=event.source_agent_id,
                    skill_id=-2,
                    time_ms=event.time_ms - origin,
                    duration_ms=0,
                )
            )
        elif isinstance(event, BoonApplyEvent):
            buff_key = (event.target_agent_id, event.skill_id)
            already_active = active_buff_until.get(buff_key, -1) > event.time_ms
            instant = _INSTANT_CASTS_BY_BUFF.get(event.skill_id) if event.kind == "apply" else None
            if instant is not None:
                skill_id, before_swap = instant
                time_ms = event.time_ms
                if before_swap and nearby_swap(event.target_agent_id, event.time_ms):
                    time_ms -= 1
                add_instant(event.target_agent_id, skill_id, time_ms)
            mapped = (
                _BUFF_GAIN_CASTS.get(event.skill_id)
                if event.kind == "apply"
                else _BUFF_LOSS_CASTS.get(event.skill_id)
            )
            if mapped is not None and (
                (event.skill_id == 73955 and event.kind == "apply" and already_active)
                or (event.skill_id in {27581, 73955} and event.kind not in {"apply", "remove_all"})
            ):
                mapped = None
            if mapped is not None:
                mapped_time = event.time_ms
                swap = nearby_swap(event.target_agent_id, event.time_ms)
                if swap is not None and event.skill_id in _BEFORE_SWAP_BUFFS:
                    mapped_time = swap.time_ms - 1
                elif swap is not None and event.skill_id in _AFTER_SWAP_BUFFS:
                    mapped_time = max(mapped_time, swap.time_ms + 1)
                add_instant(event.target_agent_id, mapped, mapped_time)
            if event.kind == "apply":
                active_buff_until[buff_key] = max(
                    active_buff_until.get(buff_key, -1), event.time_ms + event.duration_ms
                )
            else:
                active_buff_until[buff_key] = 0
            given = _BUFF_GIVE_CASTS.get(event.skill_id) if event.kind == "apply" else None
            if given is not None:
                add_instant(event.source_agent_id, given, event.time_ms)
            if (
                event.kind == "apply"
                and event.skill_id == 59536
                and event.target_agent_id in siege_turtle_agent_ids
            ):
                owner = spawn_owner_by_target.get(event.target_agent_id, 0)
                if owner:
                    add_instant(owner, 65418, event.time_ms)
        elif isinstance(event, DamageEvent) and event.skill_id in _DAMAGE_CASTS:
            add_instant(
                event.source_agent_id,
                event.skill_id,
                event.time_ms,
                _DAMAGE_CASTS[event.skill_id],
            )
        elif isinstance(event, DamageEvent) and event.skill_id in _DAMAGE_CASTS_BY_DAMAGE:
            add_instant(
                event.source_agent_id,
                _DAMAGE_CASTS_BY_DAMAGE[event.skill_id],
                event.time_ms,
            )
        elif (isinstance(event, HealingEvent) and event.skill_id in _HEALING_CASTS) or (
            isinstance(event, MissileEvent) and event.skill_id in _MISSILE_CASTS
        ):
            add_instant(event.source_agent_id, event.skill_id, event.time_ms)
        elif isinstance(event, SpawnEvent) and event.target_agent_id in ranger_pet_agent_ids:
            add_instant(event.source_agent_id, -28, event.time_ms)
        elif isinstance(event, EffectEvent):
            by_dst = event.guid in _EFFECT_CASTS_BY_DST
            effect_skill_id: int | None
            caster = (
                event.target_agent_id if by_dst else event.source_agent_id or event.target_agent_id
            )
            if event.guid == "C34E250B01FF534292EE6AB36D768337":
                effect_skill_id = (
                    10310
                    if any(
                        isinstance(other, SpawnEvent)
                        and other.source_agent_id == caster
                        and other.target_agent_id in clone_agent_ids
                        and abs(other.time_ms - event.time_ms) < 30
                        for other in nearby_events(event.time_ms, 29)
                    )
                    else -27
                )
            elif event.guid == "3D29ABD39CB5BD458C4D50A22FCC0E4B":
                effect_skill_id = (
                    68273
                    if caster in virtuoso_agent_ids
                    else 10192
                    if any(
                        isinstance(other, BoonApplyEvent)
                        and other.kind == "apply"
                        and other.skill_id == 10243
                        and other.target_agent_id == caster
                        and abs(other.time_ms - event.time_ms) < 10
                        for other in nearby_events(event.time_ms, 9)
                    )
                    else 10191
                    if caster in mesmer_agent_ids
                    else None
                )
            else:
                effect_skill_id = (
                    _EFFECT_CASTS_BY_DST.get(event.guid)
                    if by_dst
                    else _INSTANT_CASTS_BY_EFFECT.get(event.guid)
                )
            if effect_skill_id is not None:
                if event.guid in _MESMER_SHATTER_EFFECTS and caster not in (
                    virtuoso_agent_ids if effect_skill_id == 68273 else mesmer_agent_ids
                ):
                    continue
                needs_related = by_dst or event.guid in _SECONDARY_EFFECTS
                needs_related = needs_related or event.guid in _MESMER_SHATTER_EFFECTS
                related = nearby_events(event.time_ms, 9) if needs_related else []
                if (
                    event.guid == "122BA55CCDF2B643929F6C4A97226DC9"
                    and sum(
                        isinstance(other, BoonApplyEvent)
                        and other.kind == "apply"
                        and other.skill_id == 1122
                        and other.source_agent_id == caster
                        and other.target_agent_id == caster
                        for other in related
                    )
                    < 5
                ):
                    continue
                if event.guid in {
                    "98C9834C6381204A85DC67C375D135E4",
                    "13D0B65D73B5334D80824EE17B5C257E",
                } and any((caster, skill_id) in active for skill_id in (9146, 76708)):
                    continue
                secondary = _SECONDARY_EFFECTS.get(event.guid, ())
                related_guids = {
                    other.guid
                    for other in related
                    if isinstance(other, EffectEvent) and other.source_agent_id == caster
                }
                if not all(guid in related_guids for guid in secondary):
                    continue
                if (
                    event.guid in _MESMER_SHATTER_EFFECTS
                    and _MESMER_CLONE_SHATTER_EFFECT in related_guids
                ):
                    continue
                base_skill = _BASE_SKILL_BY_ENHANCED_EFFECT.get(event.guid)
                if base_skill is not None and (caster, base_skill) in active:
                    continue
                if event.guid != "C4E8DD3234E0C647993857940ED79AC1" or not any(
                    isinstance(other, DamageEvent)
                    and other.source_agent_id == caster
                    and other.skill_id == 38767
                    and abs(other.time_ms - event.time_ms) < 50
                    for other in nearby_events(event.time_ms, 49)
                ):
                    add_instant(caster, effect_skill_id, event.time_ms)

    for start in active.values():
        casts.append(
            SkillCast(
                source_agent_id=start.source_agent_id,
                skill_id=start.skill_id,
                time_ms=start.time_ms - origin,
                duration_ms=min(
                    start.duration_ms,
                    max(0, duration_ms - (start.time_ms - origin)),
                ),
            )
        )
    unique = {
        (cast.source_agent_id, cast.skill_id, cast.time_ms, cast.duration_ms): cast
        for cast in casts
    }
    result: list[SkillCast] = []
    last_swap: dict[int, int] = {}
    for cast in sorted(
        unique.values(), key=lambda item: (item.time_ms, item.skill_id, item.duration_ms == 0)
    ):
        previous = last_swap.get(cast.source_agent_id)
        if (
            cast.skill_id == -2
            and previous is not None
            and cast.time_ms - result[previous].time_ms <= 1
        ):
            result[previous] = cast
        else:
            if cast.skill_id == -2:
                last_swap[cast.source_agent_id] = len(result)
            result.append(cast)
    return result


__all__ = ["SkillCast", "build_skill_rotation"]
