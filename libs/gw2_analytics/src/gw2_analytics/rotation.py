"""Build EI-style skill casts from raw EVTC activation and instant-cast signals."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping

from pydantic import BaseModel, ConfigDict

from gw2_core import (
    ActivationType,
    BoonApplyEvent,
    BuffApplyEvent,
    DamageEvent,
    EffectEvent,
    EliteSpec,
    Event,
    HealingEvent,
    MissileEvent,
    Profession,
    SkillActivationEvent,
    SpawnEvent,
    WeaponSwapEvent,
)

#: Engineer kit -> the bundle it puts on the bar, as reported by
#: ``/v2/skills``. Elite Insights declares one ``EngineerKitFinder`` per kit
#: and reads the same list off the API at runtime; swapping to the kit set
#: and then casting one of its skills is what identifies the swap.
_ENGINEER_KIT_BUNDLES = {
    5802: {58090, 30521, 29547, 49045, 49082, 58104, 50444},  # Med Kit
    5812: {5813, 5822, 5823, 5842, 76530},  # Bomb Kit
    5904: {5905, 5992, 5995, 5996, 5998, 6175},  # Tool Kit
    5927: {5928, 5929, 5930, 5931, 76493},  # Flamethrower
    5933: {5934, 5935, 5965, 5936, 6102, 5937},  # Elixir Gun
    6020: {5806, 5807, 5808, 5809, 5882, 6167, 6168, 6169, 6170, 6171},  # Grenade Kit
    30800: {30371, 30885, 30307, 30121, 30032},  # Elite Mortar Kit
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
    9103: 9104,
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
    42311: 40274,
    40069: 42944,
    40272: 42944,
    41720: 42944,
    44693: 42944,
    44932: 42944,
    44272: 41858,  # Legendary Renegade Stance
    33162: 31129,
    59964: 62567,
    63239: 63155,
    63317: 63147,
    71431: 71431,
    73071: 73037,
    63145: 63344,
    77095: 76813,
    76351: 76351,
    62769: 62745,
    78624: 76752,
    76868: 77321,
    77362: 77018,
    51664: 14410,  # Signet of Fury (active buff)
    32931: 31187,  # Dash <- UnhinderedCombatant
    62931: 62758,  # Flame Wheel
    9422: 9422,
    29502: 30435,  # Berserk
    76507: 5635,  # Arcane Echo
    53476: 10685,  # Spectral Walk (active)
    13135: 13002,  # Shadowstep (<- Infiltration)
    78272: 77022,  # Weapon of Remedy
    78313: 76941,  # Xinrae Weapon
    5543: 5543,  # Mist Form
    5640: 5641,  # Arcane Shield
    43930: 43930,  # Superior Sigil of Severance
    44597: 13046,  # Assassin's Signet
    62768: 62975,  # Rocky Loop (Catalyst orb)
    62984: 62834,  # Icy Coil (Catalyst orb)
    62707: 62887,  # Crescent Wind (Catalyst orb)
    57031: 16435,  # Shadow Portal (Open)
    73073: 73104,  # Galvanize
    79347: 73104,  # Galvanize (Additional Strike)
    9123: 9082,  # Shield of Wrath
    10582: 10583,  # Spectral Armor
    62919: 62749,  # Legendary Alliance Stance
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
    62769: 62861,
    13135: 13106,
    77265: 76730,
}
_BUFF_GIVE_CASTS = {
    41815: 45789,
    70350: 70350,
    71890: 71792,
    44651: 40498,
    42428: 43532,
    70806: 70806,
    45038: 45970,  # Moa Stance
}
_DAMAGE_CASTS = {
    6154: 50,
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
    76783: 75,
    24305: 50,
    13907: 50,
    # DamageCastFinder(Skill), self-keyed, verified EXACT against EI.
    13014: 50,  # Mug
    5536: 50,  # Lightning Flash
    13334: 50,  # Flame Expulsion
    56885: 50,  # Earthen Blast
    73064: 50,  # Focused Devastation
    79359: 50,  # Time Bomb
    62847: 50,  # Unseen Sword
    31658: 50,  # Glyph of Equality
    5572: 50,  # Signet of Air (damage path; + effect-by-dst below)
}
_DAMAGE_CASTS_BY_DAMAGE = {40071: 44428, 46808: 40813}
_HEALING_CASTS = {
    12542,
    12631,
    12825,
    12826,
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
_MISSILE_CASTS = {26261, 29889, 42163}
_ATTUNEMENT_BUFFS = {5575, 5580, 5585, 5586}
_WEAVER_ATTUNEMENTS = _ATTUNEMENT_BUFFS | {
    40926,
    43236,
    41692,
    43740,
    42811,
    43370,
    43229,
    44822,
    43470,
    41166,
    42264,
    44857,
}
_WEAVER_BASIC_TO_DUAL = {5585: 43470, 5586: 41166, 5575: 42264, 5580: 44857}
_WEAVER_MAJOR_TRANSLATION = {
    5585: {-5, -6, -7, 43470},
    40926: {-5, -6, -7, 43470},
    5586: {-8, -9, -10, 41166},
    43236: {-8, -9, -10, 41166},
    5575: {-11, -12, -13, 42264},
    41692: {-11, -12, -13, 42264},
    5580: {-14, -15, -16, 44857},
    43740: {-14, -15, -16, 44857},
}
_WEAVER_MINOR_TRANSLATION = {
    42811: {-8, -11, -14, 43470},
    43370: {-5, -12, -15, 41166},
    43229: {-6, -9, -16, 42264},
    44822: {-7, -10, -13, 44857},
}
_WEAVER_DUAL_ATTUNEMENTS = {43470, 41166, 42264, 44857}
_BEFORE_SWAP_BUFFS = {29446, 31508, 59964, 63239, 77142, 76958, 41493, 42404, 44291, 62769}
#: ``BuffLossCastFinder`` is typed on ``BuffRemoveAllEvent``, so a partial
#: strip is not a cast. Only the entries verified against Elite Insights are
#: listed; the rest keep the historical "any removal" behaviour until they
#: are checked the same way.
_BUFF_LOSS_REMOVE_ALL_ONLY = {29446, 62769}
#: BuffGainCastFinder books the buff gained by the player itself; arcdps
#: also re-emits these buffs with ``src=0`` (env) for trait/sigil pulses,
#: which EI excludes via ``!bae.Initial``. Self-apply gating reproduces
#: that for the entries where the env applies would otherwise over-book.
_BUFF_GAIN_SELF_ONLY = {29502, 62931}  # Berserk, Flame Wheel (env pulses)
_GRAND_FINALE = 62876  # Weaver hammer 5; its buff-gain collides with Flame Wheel + orbs
#: ``BuffGainCastFinder`` entries whose buff can also be granted by Grand Finale
#: (Weaver hammer 5). EI's finder is gated on ``!IsCasting(GrandFinale)`` so a
#: buff gain that falls inside a Grand Finale cast belongs to the hammer, not
#: the skill itself.
_BUFF_GAIN_GRAND_FINALE_GUARD = {62931, 62768, 62984, 62707}
_AFTER_SWAP_BUFFS = {29703}
_INSTANT_CASTS_BY_EFFECT = {
    "C4E8DD3234E0C647993857940ED79AC1": 29560,  # Spiteful Spirit
    "0BC4AABB74F2AC43963CBB7B52993559": 76607,
    "6E2B9CF3E5C95846B15BBD1EAA9B3E98": 72076,
    "B23157C515072E46B5514419B0F923B7": 12550,
    "8321373FA14B2B4B8761CDC6EEADB161": 13684,
    "E10D2D0DF7803146A69BBB5BD47944FC": 13684,  # Lesser Symbol of Protection (large variant)
    "D6C8F406E4DEE04AB16A215BE068E910": 10302,  # Feedback
    "863E477DA639694AB23E873D93E1B0AE": 76850,
    "2A1D0C23F448C348A83E9A4F2669B73F": 70491,
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
    "23613E6E374EC6429FE9A69CC893984D": 43448,  # Sand Cascade, post-July 2026 effect
    "885B7AAA68F09E48A926BFFE488DB5AD": -37,
    "19C4FA17A38E7E4780722799B48BF2BE": 31406,
    "98C9834C6381204A85DC67C375D135E4": 13677,
    "13D0B65D73B5334D80824EE17B5C257E": 13677,
    "FB78801BB31CAF488B55F2F57EF9B070": 78837,
    "842F977C318FDC4F96C99C385C1D0672": 76613,  # Symbiotic Shielding
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
    "6D7EB5747873484DAF29C01FA51FE175": 62723,  # Deploy Jade Sphere: Water
    "A3C8A55C3E530140A7F99AAA1CBB4E09": 62940,  # Deploy Jade Sphere: Air
    "DBECB5867D11264FA19FFCDC487A410E": 76611,  # Tale of the Honorable Rogue
    "24498E18DEC97B4094376849EF7A3746": 76689,  # Syncopate (Delayed Wave)
    "DF03FACC6BA66F4BA89BA27636FB39EB": 75748,  # Relic of the Holosmith
    "6C8C388BCD26F04CA6618D2916B8D796": 30670,  # Suffer (Reaper)
    "AC32B7F7BB281B4D94713F180C44F322": 30258,  # Outrage (Berserker)
    "BF0A5B11A4076A4F98C6E1D655D507B1": 59554,  # Eternal Bond (Soulbeast)
    "D2307A69B227BE4B831C2AA1DAAE646A": 29665,  # Bypass Coating (Scrapper)
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
    "B59FCEFCF1D5D84B9FDB17F11E9B52E6": 41372,  # Mercy
    "6646D48A2446884998EFADB3EFEF0483": 71989,  # Detonate Jurisdiction
    "3E33C9645D62CF4DBC208511BB3D12F1": 71989,  # Detonate Jurisdiction
    "29F6AADDF5E75348854123B956E4BF0E": 71989,  # Detonate Jurisdiction
    "E1C1DD7F866B4149A1BADD216C9AA69D": 63111,  # Shift Signet
}
#: Familiar skill -> the player skill Elite Insights credits to its owner,
#: transcribed from ``EvokerHelper``'s ``MinionCastCastFinder`` entries. The
#: familiar keeps its own cast; only the owner gains a second, instant one.
#: EI gates these on its default 50 ms ICD, but never refreshes the window
#: after an accepted cast, so the gate is dead there. It is applied normally
#: here: the closest two familiar casts by one owner on the corpus are 1 042
#: ms apart, so the two behaviours cannot diverge on real data.
_MINION_CASTS = {
    76882: 76643,  # Ignite
    76709: 77225,  # Splash
    76803: 77370,  # Zap
    76925: 77226,  # Calcify
}
#: Shared by every guardian shout, so the skill is decided by what the shout
#: applied to its caster rather than by the effect itself.
_GUARDIAN_SHOUT_EFFECT = "122BA55CCDF2B643929F6C4A97226DC9"
_MECHANIST_SHIFT_SIGNET_EFFECT = "E1C1DD7F866B4149A1BADD216C9AA69D"
_MECHANIST_SHIFT_SIGNET_SELF_EFFECT = "DB22850AE209B34BBD11372F56D42D43"
_MECHANIST_CRISIS_ZONE_EFFECT = "956450E1260FB94B8691BC1378086250"
_MECHANIST_MECH_EYE_GLOW_EFFECT = "CDF749672C01964BAEF64CCB3D431DEE"
_FLOWING_RESOLVE_SKILL = 62603
_FLOWING_RESOLVE_BUFF = 62632
#: ``UsingDstBaseSpecChecker``: the effect must sit on its destination, and
#: that destination must be of this base profession. Warriors emit the
#: guardian shout effect too, and EI books nothing for them.
_EFFECT_SPEC_GATE = {
    _GUARDIAN_SHOUT_EFFECT: Profession.GUARDIAN,
    "BFFE3477ECFA26458D69E93EE76EFF6B": Profession.ELEMENTALIST,
    "23284B87C26C9A41A887F410F930E1A2": Profession.THIEF,  # Infiltrator's Signet
    "BB5488951B60B546BB1BD5626DAE83E1": Profession.THIEF,  # Signet of Agility
    "F53E2CE3B06B934085D46FA59468477B": Profession.MESMER,  # Power Return
    "23613E6E374EC6429FE9A69CC893984D": Profession.NECROMANCER,  # Sand Cascade
    "D43DC34DEF81B746BC130F7A0393AAC7": Profession.ELEMENTALIST,  # Armor of Earth
    "D7F8FA5695F8714B99A51EE72EF6E178": Profession.WARRIOR,  # Dolyak Signet
    "68F2C378E6C80548B5A3C89870C5DD86": Profession.GUARDIAN,  # "Save Yourselves!"
}
_EFFECT_SOURCE_SPEC_GATE = {
    "C4E8DD3234E0C647993857940ED79AC1": Profession.NECROMANCER,  # Spiteful Spirit
    "6646D48A2446884998EFADB3EFEF0483": Profession.GUARDIAN,  # Detonate Jurisdiction
    "3E33C9645D62CF4DBC208511BB3D12F1": Profession.GUARDIAN,  # Detonate Jurisdiction
    "29F6AADDF5E75348854123B956E4BF0E": Profession.GUARDIAN,  # Detonate Jurisdiction
}
_EFFECT_ELITE_GATE = {
    "418A090D719AB44AAF1C4AD1473068C4": EliteSpec.HOLOSMITH,  # Flash Spark
}
_AEGIS_BUFF = 743
_STABILITY_BUFF = 1122
_EFFECT_CASTS_BY_DST = {
    _GUARDIAN_SHOUT_EFFECT: 9153,
    "BFFE3477ECFA26458D69E93EE76EFF6B": 5535,  # Cleansing Fire
    "95B52793B838524AB237EB9FED7834BF": -22,
    "F53E2CE3B06B934085D46FA59468477B": 10214,
    "EA9896A81DDF4843B18DBF6EE4F25E18": 12502,
    "9B8A1BE554450B4899B64F7579DF0A8C": 31658,
    "74870558C43E4747955C573CAAC630A7": 31401,
    "734834E7EB7CD74EB129ACBCE5C64C1D": 63095,
    _MECHANIST_CRISIS_ZONE_EFFECT: 63293,
    "9C06D9D9B0E22247A1752C426808CD80": 62671,
    "D43DC34DEF81B746BC130F7A0393AAC7": 5639,  # Armor of Earth
    "1A38CAE72C2F164BA3815441CA643A20": 12542,
    "75D72E2DA47ECF47A6BD009B49B7C708": 9248,
    "D7DCD4ABF9E4A749950AF0175E02EA06": 63256,
    "02154B72900B5740A73CD0ADECED27BF": 10234,
    "9242D10B4F04274EB6E9EBCDB2262181": 77213,
    "B02D3D0FF0A4FC47B23B1478D8E770AE": -29,
    "30A96C0E559DBD489FEE36DA96CC374A": 5572,  # Signet of Air
    "23284B87C26C9A41A887F410F930E1A2": 13064,  # Infiltrator's Signet
    "BB5488951B60B546BB1BD5626DAE83E1": 13062,  # Signet of Agility
    "418A090D719AB44AAF1C4AD1473068C4": 43176,  # Flash Spark
    "D7F8FA5695F8714B99A51EE72EF6E178": 14413,  # Dolyak Signet
    "68F2C378E6C80548B5A3C89870C5DD86": 9085,  # "Save Yourselves!"
}
_SECONDARY_EFFECTS = {
    _MECHANIST_SHIFT_SIGNET_EFFECT: (_MECHANIST_SHIFT_SIGNET_SELF_EFFECT,),
    "BFFE3477ECFA26458D69E93EE76EFF6B": (
        "61F5669F9FAC1F48B47635C9F3833CEF",
        "ABF2332D28C7D6449A5B822E5714ADA4",
    ),
    "FB78801BB31CAF488B55F2F57EF9B070": ("7535B4CB815232418B69092F3390A7AB",),
    "23284B87C26C9A41A887F410F930E1A2": ("2C89A39F7B88614ABED16D4B5A5BD2EB",),
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
    "68F2C378E6C80548B5A3C89870C5DD86": (_GUARDIAN_SHOUT_EFFECT,),
}
#: ``UsingNoAnimatedCastChecker``: a trait that places the same symbol as a
#: real skill must not be booked when the skill itself is being cast. The
#: test is on the *cast window*, widened by a server delay at both ends --
#: not merely on a cast still open at that instant.
_NO_ANIMATED_CAST_GUARDS = {
    # Lesser Symbol of Resolution. Only the first variant collides with
    # Luminous Staff; the large one does not.
    "98C9834C6381204A85DC67C375D135E4": (9146, 76708),
    "13D0B65D73B5334D80824EE17B5C257E": (9146,),
    # Lesser Symbol of Protection.
    "8321373FA14B2B4B8761CDC6EEADB161": (9161,),
    "E10D2D0DF7803146A69BBB5BD47944FC": (9161,),
    # Lesser Symbol of Blades -- trait version excluded inside the real Symbol of Blades cast.
    "FA37E0B77272314AA1ADCFF824F24C27": (9097,),
    "8B05122882E53242A4D4725F0A1537A4": (9097,),
}
_GUARDED_CAST_SKILLS = {skill for skills in _NO_ANIMATED_CAST_GUARDS.values() for skill in skills}
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


def _translate_weaver_attunement(events: list[BoonApplyEvent | BuffApplyEvent]) -> int | None:
    ids = [event.skill_id for event in events]
    if len(ids) == 1 and ids[0] in _WEAVER_BASIC_TO_DUAL:
        return _WEAVER_BASIC_TO_DUAL[ids[0]]
    for skill_id in ids:
        if skill_id in _WEAVER_DUAL_ATTUNEMENTS:
            return skill_id
    major: set[int] | None = None
    minor: set[int] | None = None
    for skill_id in ids:
        if skill_id in _WEAVER_MAJOR_TRANSLATION:
            major = _WEAVER_MAJOR_TRANSLATION[skill_id]
        elif skill_id in _WEAVER_MINOR_TRANSLATION:
            minor = _WEAVER_MINOR_TRANSLATION[skill_id]
    if major is None or minor is None:
        return None
    match = major & minor
    return next(iter(match)) if len(match) == 1 else None


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
    smokescale_agent_ids: Collection[int] = (),
    fern_hound_agent_ids: Collection[int] = (),
    warclaw_agent_ids: Collection[int] = (),
    jungle_stalker_agent_ids: Collection[int] = (),
    jade_mech_agent_ids: Collection[int] = (),
    professions: Mapping[int, Profession] | None = None,
    elite_specs: Mapping[int, EliteSpec] | None = None,
    agent_id_by_instance: Mapping[int, int] | None = None,
) -> list[SkillCast]:
    """Return completed, clipped casts ordered by fight-relative start time.

    ``professions`` and ``agent_id_by_instance`` gate the finders that need
    to know *who* an agent is: a shout effect is told apart from another
    profession's by its caster, and a familiar's cast is credited to the
    owner named by the record's ``src_master_instid``. Both are optional so
    hand-built event streams keep working; the finders that need them are
    simply skipped when they are absent.
    """
    event_list = list(events)
    professions = professions or {}
    elite_specs = elite_specs or {}
    agent_id_by_instance = agent_id_by_instance or {}
    if not event_list:
        return []
    origin = start_time_ms if start_time_ms is not None else min(e.time_ms for e in event_list)
    event_times = [event.time_ms for event in event_list]
    weaver_attunement_groups: dict[int, list[tuple[int, list[BoonApplyEvent | BuffApplyEvent]]]] = (
        defaultdict(list)
    )
    for event in event_list:
        if (
            isinstance(event, (BoonApplyEvent, BuffApplyEvent))
            and event.skill_id in _WEAVER_ATTUNEMENTS
            and elite_specs.get(event.target_agent_id) is EliteSpec.WEAVER
        ):
            groups = weaver_attunement_groups[event.target_agent_id]
            match = next(
                (group for group in groups if abs(group[0] - event.time_ms) < 10),
                None,
            )
            if match is None:
                groups.append((event.time_ms, [event]))
            else:
                match[1].append(event)
    weaver_attunement_casts = [
        (agent_id, skill_id, time_ms)
        for agent_id, groups in weaver_attunement_groups.items()
        for time_ms, group in groups
        if time_ms > origin
        and (
            skill_id := _translate_weaver_attunement(
                [
                    event
                    for event in group
                    if isinstance(event, BuffApplyEvent)
                    or (isinstance(event, BoonApplyEvent) and event.kind == "apply")
                ]
            )
        )
    ]
    swaps_by_agent: dict[int, list[WeaponSwapEvent]] = defaultdict(list)
    activations_by_agent: dict[int, list[SkillActivationEvent]] = defaultdict(list)
    spawn_owner_by_target: dict[int, int] = {}
    cast_windows: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    open_casts: dict[tuple[int, int], int] = {}
    for indexed_event in event_list:
        if isinstance(indexed_event, WeaponSwapEvent):
            swaps_by_agent[indexed_event.source_agent_id].append(indexed_event)
        elif isinstance(indexed_event, SkillActivationEvent):
            activations_by_agent[indexed_event.source_agent_id].append(indexed_event)
            if indexed_event.skill_id in _GUARDED_CAST_SKILLS:
                window_key = (indexed_event.source_agent_id, indexed_event.skill_id)
                if indexed_event.activation in (ActivationType.NORMAL, ActivationType.QUICKNESS):
                    open_casts[window_key] = indexed_event.time_ms
                else:
                    start = open_casts.pop(
                        window_key, indexed_event.time_ms - indexed_event.duration_ms
                    )
                    cast_windows[window_key].append((start, indexed_event.time_ms))
        elif isinstance(indexed_event, SpawnEvent):
            spawn_owner_by_target.setdefault(
                indexed_event.target_agent_id,
                indexed_event.source_agent_id,
            )
    # A cast the log never closes still occupies its start instant.
    for window_key, start in open_casts.items():
        cast_windows[window_key].append((start, start))
    swap_times_by_agent = {
        agent_id: [swap.time_ms for swap in agent_swaps]
        for agent_id, agent_swaps in swaps_by_agent.items()
    }
    active: dict[tuple[int, int], SkillActivationEvent] = {}
    casts: list[SkillCast] = []
    last_instant: dict[tuple[int, int], int] = {}
    active_buff_until: dict[tuple[int, int], int] = {}
    has_flowing_resolve_animation = any(
        isinstance(event, SkillActivationEvent) and event.skill_id == _FLOWING_RESOLVE_SKILL
        for event in event_list
    )

    def is_casting(agent_id: int, skill_id: int, time_ms: int, epsilon: int = 10) -> bool:
        """Whether ``agent_id`` is inside a cast window of ``skill_id``."""
        return any(
            start - epsilon <= time_ms <= end + epsilon
            for start, end in cast_windows.get((agent_id, skill_id), ())
        )

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

    for source, skill_id, time_ms in weaver_attunement_casts:
        add_instant(source, skill_id, time_ms)

    for event in event_list:
        if isinstance(event, SkillActivationEvent):
            key = (event.source_agent_id, event.skill_id)
            if event.activation in (ActivationType.NORMAL, ActivationType.QUICKNESS):
                if pending := active.pop((event.source_agent_id, 63267), None):
                    casts.append(
                        SkillCast(
                            source_agent_id=pending.source_agent_id,
                            skill_id=pending.skill_id,
                            time_ms=pending.time_ms - origin,
                            duration_ms=min(
                                pending.expected_duration_ms,
                                event.time_ms - pending.time_ms + 10,
                            ),
                        )
                    )
                if (pending := active.pop(key, None)) and pending.time_ms >= origin:
                    casts.append(
                        SkillCast(
                            source_agent_id=pending.source_agent_id,
                            skill_id=pending.skill_id,
                            time_ms=pending.time_ms - origin,
                            duration_ms=min(
                                pending.expected_duration_ms,
                                event.time_ms - pending.time_ms + 10,
                            ),
                        )
                    )
                active[event.source_agent_id, event.skill_id] = event
                owner_skill = _MINION_CASTS.get(event.skill_id)
                if owner_skill is not None:
                    owner = agent_id_by_instance.get(event.src_master_instid)
                    if owner:
                        add_instant(owner, owner_skill, event.time_ms)
            elif pending := active.pop(key, None):
                cast_duration = event.time_ms - pending.time_ms
                if cast_duration > 1:
                    casts.append(
                        SkillCast(
                            source_agent_id=event.source_agent_id,
                            skill_id=event.skill_id,
                            time_ms=pending.time_ms - origin,
                            duration_ms=cast_duration,
                        )
                    )
            elif event.duration_ms > 1:
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
            kit_activations = agent_activations[
                bisect_left(activation_times, event.time_ms + 10) : bisect_left(
                    activation_times,
                    next_swap_time,
                )
            ]
            kit_starts = [
                other
                for other in kit_activations
                if other.activation in (ActivationType.NORMAL, ActivationType.QUICKNESS)
            ]
            for kit_skill, bundle_skills in _ENGINEER_KIT_BUNDLES.items():
                if event.swapped_to == 2 and any(
                    other.skill_id in bundle_skills for other in (kit_starts or kit_activations)
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
        elif isinstance(event, BuffApplyEvent):
            if (
                not has_flowing_resolve_animation
                and event.skill_id == _FLOWING_RESOLVE_BUFF
                and elite_specs.get(event.target_agent_id) is EliteSpec.WILLBENDER
            ):
                casts.append(
                    SkillCast(
                        source_agent_id=event.target_agent_id,
                        skill_id=_FLOWING_RESOLVE_SKILL,
                        time_ms=event.time_ms - 440 - origin,
                        duration_ms=500,
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
            if event.kind == "apply" and event.skill_id == 40052:
                mapped = 44663 if event.duration_ms >= 5_000 else 54870
            if event.kind == "remove_all" and event.skill_id == 10686:
                has_walk_loss = any(
                    isinstance(other, BoonApplyEvent)
                    and other.kind == "remove_all"
                    and other.skill_id == 53476
                    and abs(other.time_ms - (event.time_ms + 120)) < 10
                    for other in nearby_events(event.time_ms + 120, 9)
                )
                mapped = None if has_walk_loss else 10687
            if mapped is not None and (
                (event.skill_id == 73955 and event.kind == "apply" and already_active)
                or (event.skill_id in {27581, 73955} and event.kind not in {"apply", "remove_all"})
                or (
                    event.kind != "apply"
                    and event.skill_id in _BUFF_LOSS_REMOVE_ALL_ONLY
                    and event.kind != "remove_all"
                )
                or (
                    event.skill_id in _ATTUNEMENT_BUFFS
                    and elite_specs.get(event.target_agent_id) is EliteSpec.WEAVER
                )
                or (
                    event.skill_id in _BUFF_GAIN_SELF_ONLY
                    and event.source_agent_id != event.target_agent_id
                )
                or (
                    event.skill_id == 13135
                    and event.kind != "apply"
                    and event.source_agent_id != event.target_agent_id
                )
                or (
                    event.skill_id in _BUFF_GAIN_GRAND_FINALE_GUARD
                    and is_casting(event.target_agent_id, _GRAND_FINALE, event.time_ms, 500)
                )
            ):
                mapped = None
            if mapped is not None:
                mapped_time = event.time_ms
                swap = nearby_swap(event.target_agent_id, event.time_ms)
                if swap is not None and event.skill_id in _BEFORE_SWAP_BUFFS:
                    # The earlier of the two: a cast already ahead of the swap
                    # is left where it is rather than pushed onto it.
                    mapped_time = min(swap.time_ms - 1, mapped_time)
                elif swap is not None and event.skill_id in _AFTER_SWAP_BUFFS:
                    mapped_time = max(mapped_time, swap.time_ms + 1)
                icd = 0 if mapped == 41380 else 50
                add_instant(event.target_agent_id, mapped, mapped_time, icd)
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
                owner = spawn_owner_by_target.get(event.target_agent_id) or event.source_agent_id
                if owner:
                    add_instant(owner, 65418, event.time_ms)
            if (
                event.kind == "apply"
                and event.skill_id == 59536
                and event.target_agent_id in fern_hound_agent_ids
            ):
                owner = spawn_owner_by_target.get(event.target_agent_id) or event.source_agent_id
                if owner:
                    add_instant(owner, 12717, event.time_ms)
            if (
                event.kind == "apply"
                and event.skill_id == 59536
                and event.duration_ms >= 1000
                and event.target_agent_id in smokescale_agent_ids
            ):
                owner = spawn_owner_by_target.get(event.target_agent_id) or event.source_agent_id
                if owner:
                    add_instant(owner, 31568, event.time_ms)
            if (
                event.kind == "apply"
                and event.skill_id == 59536
                and event.target_agent_id in warclaw_agent_ids
            ):
                owner = spawn_owner_by_target.get(event.target_agent_id) or event.source_agent_id
                if owner:
                    add_instant(owner, 74314, event.time_ms)
            if (
                event.kind == "apply"
                and event.skill_id == 59536
                and event.target_agent_id in jungle_stalker_agent_ids
            ):
                owner = spawn_owner_by_target.get(event.target_agent_id) or event.source_agent_id
                if owner:
                    add_instant(owner, 12658, event.time_ms)
        elif isinstance(event, DamageEvent) and event.skill_id == 29560:
            source_is_necro = (
                not professions or professions.get(event.source_agent_id) is Profession.NECROMANCER
            )
            if source_is_necro and not any(
                isinstance(other, EffectEvent)
                and other.guid == "C4E8DD3234E0C647993857940ED79AC1"
                and other.source_agent_id == event.source_agent_id
                and abs(other.time_ms - event.time_ms) < 50
                for other in nearby_events(event.time_ms, 49)
            ):
                add_instant(event.source_agent_id, event.skill_id, event.time_ms)
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
                if professions and professions.get(caster) is not Profession.MESMER:
                    continue
                effect_skill_id = (
                    10337
                    if any(
                        isinstance(other, BoonApplyEvent)
                        and other.kind == "remove_all"
                        and other.skill_id == 10353
                        and other.source_agent_id == caster
                        and other.target_agent_id == caster
                        and abs(other.time_ms - event.time_ms) < 2
                        for other in nearby_events(event.time_ms, 1)
                    )
                    else -27
                    if elite_specs.get(caster) is EliteSpec.MIRAGE
                    else 10310
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
                distortion_buff_nearby = any(
                    isinstance(other, BoonApplyEvent)
                    and other.kind == "apply"
                    and other.skill_id == 10243
                    and other.target_agent_id == caster
                    and abs(other.time_ms - event.time_ms) < 10
                    for other in nearby_events(event.time_ms, 9)
                )
                effect_skill_id = (
                    68273
                    if (
                        caster in virtuoso_agent_ids
                        and distortion_buff_nearby
                        and not is_casting(caster, 43343, event.time_ms, 50)
                    )
                    else 10192
                    if distortion_buff_nearby
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
                if (
                    event.guid == _MECHANIST_SHIFT_SIGNET_EFFECT
                    and elite_specs.get(caster) is not EliteSpec.MECHANIST
                ):
                    continue
                gate = _EFFECT_SPEC_GATE.get(event.guid)
                if gate is not None and (
                    not event.is_around_dst or professions.get(caster) is not gate
                ):
                    continue
                source_gate = _EFFECT_SOURCE_SPEC_GATE.get(event.guid)
                if source_gate is not None and professions.get(caster) is not source_gate:
                    continue
                elite_gate = _EFFECT_ELITE_GATE.get(event.guid)
                if elite_gate is not None and (
                    not event.is_around_dst or elite_specs.get(caster) is not elite_gate
                ):
                    continue
                needs_related = by_dst or event.guid in _SECONDARY_EFFECTS
                needs_related = needs_related or event.guid in _MESMER_SHATTER_EFFECTS
                related = nearby_events(event.time_ms, 9) if needs_related else []
                if event.guid == _GUARDIAN_SHOUT_EFFECT:
                    # Every guardian shout shares one effect, so the skill is
                    # read off what the caster granted itself: five-plus
                    # stability stacks is "Stand Your Ground!", a 20-to-40
                    # second aegis is "Advance!". Pure of Voice can extend a
                    # shout's boons, which is why the aegis test is a window
                    # and not an equality. No effect on the corpus satisfies
                    # both, so the two are checked in sequence.
                    self_applied = [
                        other
                        for other in related
                        if isinstance(other, BoonApplyEvent)
                        and other.kind == "apply"
                        and other.source_agent_id == caster
                        and other.target_agent_id == caster
                    ]
                    if sum(other.skill_id == _STABILITY_BUFF for other in self_applied) >= 5:
                        effect_skill_id = 9153
                    elif any(
                        other.skill_id == _AEGIS_BUFF
                        and other.duration_ms + 10 >= 20_000
                        and other.duration_ms - 10 <= 40_000
                        for other in self_applied
                    ):
                        effect_skill_id = 9084
                    else:
                        continue
                guarded = _NO_ANIMATED_CAST_GUARDS.get(event.guid)
                if guarded is not None and any(
                    is_casting(caster, skill_id, event.time_ms) for skill_id in guarded
                ):
                    continue
                secondary = _SECONDARY_EFFECTS.get(event.guid, ())
                # A secondary effect is matched on the finder's *key* agent,
                # which for a by-dst finder is the effect's destination. The
                # two are the same agent for a self-targeted effect, so this
                # only starts to matter with the first by-dst entry.
                related_guids = {
                    other.guid
                    for other in related
                    if isinstance(other, EffectEvent)
                    and (other.target_agent_id if by_dst else other.source_agent_id) == caster
                }
                if event.guid == _MECHANIST_CRISIS_ZONE_EFFECT and (
                    event.target_agent_id not in jade_mech_agent_ids
                    or not any(
                        isinstance(other, EffectEvent)
                        and other.guid == _MECHANIST_MECH_EYE_GLOW_EFFECT
                        and other.source_agent_id == event.source_agent_id
                        for other in related
                    )
                ):
                    continue
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
                    and abs(other.time_ms - event.time_ms) < 10
                    for other in nearby_events(event.time_ms, 9)
                ):
                    add_instant(caster, effect_skill_id, event.time_ms)

    for pending in active.values():
        duration = (
            pending.expected_duration_ms
            if pending.skill_id in {71892, 72940}
            else pending.duration_ms
        )
        casts.append(
            SkillCast(
                source_agent_id=pending.source_agent_id,
                skill_id=pending.skill_id,
                time_ms=pending.time_ms - origin,
                duration_ms=min(
                    duration,
                    max(0, duration_ms - (pending.time_ms - origin)),
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
