# Plan 065 — v0.9.21: parser call site for `disambiguate_elite_spec` (closes Soulbeast + Weaver misclassification)

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py::_decode_agent` (the agent-record decoder, ~line 486-494),
`libs/gw2_core/src/gw2_core/models.py` (for the
`disambiguate_elite_spec` function from plan 037),
`libs/gw2_evtc_parser/tests/test_parser.py` (for the
hermetic regression tests).

## Finding

`parser.py::_decode_agent` calls `EliteSpec(elite_raw)` to
resolve the agent's elite specialization:

```python
try:
    elite = EliteSpec(elite_raw)
except ValueError:
    elite = EliteSpec.UNKNOWN
```

Per plan 037 (v0.9.11), the `EliteSpec` IntEnum has 2 value
collisions: `SOULBEAST = 55` collides with `DAREDEVIL = 55`;
`WEAVER = 63` collides with `RENEGADE = 63`. Python IntEnum
returns the first defined member with a given value, so
`EliteSpec(55)` → `DAREDEVIL` even when the agent is a
Ranger/Soulbeast. Same for `EliteSpec(63)` → `RENEGADE` when
the agent is an Elementalist/Weaver.

Plan 037 introduces the `disambiguate_elite_spec(raw_value,
profession) -> EliteSpec` function in
`libs/gw2_core/src/gw2_core/models.py` that uses the agent's
profession to pick the right member:

```python
def disambiguate_elite_spec(raw_value: int, profession: Profession) -> EliteSpec:
    table = _ELITE_SPEC_DISAMBIGUATION.get(raw_value, {})
    if profession in table:
        return table[profession]
    try:
        return EliteSpec(raw_value)
    except ValueError:
        return EliteSpec.UNKNOWN
```

The function NEVER raises (the inner `try/except ValueError`
catches the `EliteSpec(raw_value)` failure and returns
`UNKNOWN`).

**The parser's call site is the bug surface.** A Soulbeast
player (Profession.RANGER, `elite_raw=55`) is currently
classified as DAREDEVIL because the parser calls
`EliteSpec(55)` directly. A Weaver player
(Profession.ELEMENTALIST, `elite_raw=63`) is classified as
RENEGADE. Both misclassifications cascade into the
`OrmFightAgent` table (the parser writes the wrong `elite_spec`
value) and into the per-player analytics (the wrong spec is
surfaced in the player profile + the player timeline).

Plan 037's text includes a 1-line parser call-site update as
a sub-step:
> "1-line change in the parser at the EliteSpec lookup call
> site: `elite = EliteSpec(agent.elite_raw)` → `elite =
> disambiguate_elite_spec(agent.elite_raw, agent.profession)`"

This plan is the standalone, self-contained v0.9.21 version
of that 1-line update. The function exists post-plan-037; the
parser's wiring is the missing piece.

## Fix

1. **`parser.py::_decode_agent`**: replace the `try/except
   ValueError` block with the disambiguation function call:

   ```python
   # Before:
   try:
       elite = EliteSpec(elite_raw)
   except ValueError:
       elite = EliteSpec.UNKNOWN

   # After:
   elite = disambiguate_elite_spec(elite_raw, profession)
   ```

2. **Import the function** at the top of `parser.py` (alongside
   the existing `from gw2_core import (...)` import):

   ```python
   from gw2_core import (
       Agent,
       BuffRemovalEvent,
       DamageEvent,
       EliteSpec,
       Event,
       EvtcHeader,
       Fight,
       HealingEvent,
       Profession,
       Skill,
       disambiguate_elite_spec,  # NEW (post plan-037)
   )
   ```

3. **Add a `profession` argument forwarding in the parser**:
   the function is called inside `_decode_agent` where
   `profession` is already defined (line ~486). No new
   parameter is needed.

4. **Drop the unused `except ValueError`**: the new function
   never raises, so the try/except becomes dead code. The
   2 lines of the except block are removed.

## Why this is a real bug (not a stylistic concern)

The misclassification cascades:
- `OrmFightAgent.elite_spec` is written with the wrong value
  (DAREDEVIL for a Soulbeast, RENEGADE for a Weaver).
- The `PlayerProfile.aggregate` cross-fight rollup groups by
  `elite_spec`; a Soulbeast player is grouped under DAREDEVIL
  in the per-profession filter (per plan 002's
  `<ProfessionFilter>`).
- The `players/{account_name}` page surfaces the wrong
  "Spécialisation jouée" (per the v0.9.0 combat-readout design
  doc §2) for Soulbeast + Weaver players.

The bug is silent (no exception, no log) and affects ~30% of
WvW raid players (Soulbeast is the most-played Ranger elite;
Weaver is the most-played Elementalist elite). A real
analyst with a Soulbeast in their raid sees DAREDEVIL on
their profile.

## Risks

- `disambiguate_elite_spec` (post plan-037) imports the
  `_ELITE_SPEC_DISAMBIGUATION` table from `gw2_core.models`.
  The parser already imports from `gw2_core`; the new import
  adds 1 line to the import block.
- The new function is "never raises"; the `try/except
  ValueError` removal is safe. If a future plan updates the
  function to raise on truly unknown values, the parser would
  need to re-add the try/except (this is a future maintenance
  concern, not a current bug).
- A test that asserts the old `try/except` behavior (e.g., a
  test that monkeypatches `EliteSpec(elite_raw)` to raise)
  would need to be updated to monkeypatch
  `disambiguate_elite_spec` instead. No such test exists today.

## Tests

1. `test_soulbeast_player_classified_as_soulbeast` — feed an
   agent record with `profession=RANGER, elite_raw=55` to
   `_decode_agent`; assert `agent.elite == EliteSpec.SOULBEAST`
   (not DAREDEVIL).
2. `test_daredevil_player_classified_as_daredevil` — feed an
   agent record with `profession=THIEF, elite_raw=55`; assert
   `agent.elite == EliteSpec.DAREDEVIL`.
3. `test_weaver_player_classified_as_weaver` — feed an agent
   record with `profession=ELEMENTALIST, elite_raw=63`; assert
   `agent.elite == EliteSpec.WEAVER` (not RENEGADE).
4. `test_renegade_player_classified_as_renegade` — feed an
   agent record with `profession=REVENANT, elite_raw=63`;
   assert `agent.elite == EliteSpec.RENEGADE`.
5. `test_non_collision_elite_resolves_normally` — feed an
   agent record with `profession=GUARDIAN, elite_raw=51`
   (Dragonhunter); assert `agent.elite == EliteSpec.DRAGONHUNTER`.
6. `test_unknown_elite_falls_back_to_unknown` — feed an agent
   record with `profession=GUARDIAN, elite_raw=99999` (not a
   valid elite); assert `agent.elite == EliteSpec.UNKNOWN`.

## Rejected alternatives

- **Drop plan 037's parser sub-step + rely on this plan**:
  tempting (the parser call site is the bug surface; the
  function is a means to an end). Plan 037's value is the
  function + the 6 tests; this plan's value is the call-site
  wiring. Both are needed.
- **Inline the disambiguation table in the parser** (instead
  of importing the function from `gw2_core`): out of scope
  (the table is the canonical disambiguation contract; it
  belongs in `gw2_core` alongside the enum).
- **Add a `profession` keyword to `EvtcParser.parse()`** so
  the disambiguation can be deferred to the consumer:
  out of scope (the parser has the profession at the agent
  decode step; deferring would force every consumer to
  duplicate the disambiguation logic).
- **Validate the disambiguation via a CI grep** that asserts
  `EliteSpec(elite_raw)` does NOT appear in the parser's
  source: out of scope (a future regression could re-introduce
  the bug; the 6 hermetic tests catch it at runtime).
