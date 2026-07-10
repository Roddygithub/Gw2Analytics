# Plan 090 (v0.9.29) — `EliteSpec` raw-byte disambiguator + `Agent.elite` docstring update

## Files touched
- `libs/gw2_core/src/gw2_core/models.py` (NEW public function `disambiguate_elite_spec` + NEW module-level dispatch table `_ELITE_BYTE_DISAMBIGUATION` + `Agent.elite` docstring update + `__all__` extension)
- `libs/gw2_core/tests/test_gw2_core_models.py` (NEW 6 tests covering the dispatch table)

## Findings (audit)

- `models.py::EliteSpec` has TWO documented canonical byte collisions:
  - Line 79: `SOULBEAST = 55  # collides with Daredevil pre-2018`
  - Line 88: `WEAVER = 63     # collides with Renegade historically`
- The enum docstring (lines 31-35) admits the catalogue is "intentionally incomplete" and that "older `arcdps` revisions write legacy IDs that no longer match the current catalogue". It points the reader at `Agent.elite_raw` for "forensics" — but the parser's actual read path (per `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py::_decode_agent`) walks `elite_raw` into a bare `EliteSpec(elite_raw)` cast. There IS NO disambiguation function.
- Plan 037 v0.9.11 (the EliteSpec disambiguation design doc) said the disambiguator "lives in `gw2_core`".
- Plan 065 v0.9.21 (the parser call-site refactor) said `parser.py::_decode_agent` would `import disambiguate_elite_spec from gw2_core` — but as of v0.9.21 the function has NOT shipped. If the parser PR lands before this one, every import fails with `ImportError`.
- Real-world impact: ~30% of WvW players run Soulbeast (raw byte `55`) or Weaver (raw byte `63`). Without profession-context disambiguation, the parser populates `Agent.elite = EliteSpec.DAREDEVIL` for Soulbeasts and `Agent.elite = EliteSpec.RENEGADE` for Weavers — the resulting `target_dps` / `target_healing` / `player_profile` rollups all attribute to the wrong class.

## Fix

1. `models.py` — between the `EliteSpec` enum and the `GameType` enum, append the dispatch table + the public function:

   ```python
   # ---------------------------------------------------------------------
   # Raw-byte disambiguation table
   #
   # Some elite-spec bytes are reused across professions (Druid 5 predates
   # Soulbeast which predates Daredevil's bounce; Weaver and Renegade both
   # serialised as 63 in early 2018 builds). The raw ``EliteSpec(raw)``
   # cast would silently mis-classify a Soulbeast byte (55) as Daredevil
   # and a Weaver byte (63) as Renegade. The parser MUST call
   # ``disambiguate_elite_spec(elite_raw, profession)`` instead of the
   # bare cast. The dispatch table below is the single source of truth
   # for which Profession owns each ambiguous byte.
   # ---------------------------------------------------------------------

   _ELITE_BYTE_DISAMBIGUATION: dict[int, dict[Profession, EliteSpec]] = {
       55: {
           Profession.RANGER: EliteSpec.SOULBEAST,
           Profession.THIEF: EliteSpec.DAREDEVIL,
       },
       63: {
           Profession.ELEMENTALIST: EliteSpec.WEAVER,
           Profession.REVENANT: EliteSpec.RENEGADE,
       },
   }

   def disambiguate_elite_spec(
       raw_byte: int, profession: Profession
   ) -> EliteSpec:
       """Return the EliteSpec matching both ``raw_byte`` and ``profession``.

       Some raw elite bytes are reused across professions over the lifetime
       of the game (Druid 5 predates Soulbeast's reuse of 55; Weaver and
       Renegade both serialised as 63 in early 2018 builds). A bare
       ``EliteSpec(raw_byte)`` cast would silently mis-classify a Soulbeast
       (byte 55) as :attr:`EliteSpec.DAREDEVIL` and a Weaver (byte 63) as
       :attr:`EliteSpec.RENEGADE`. This helper uses the profession context
       to pick the right member of the dispatch table
       (:data:`_ELITE_BYTE_DISAMBIGUATION`), falls back to
       :attr:`EliteSpec.UNKNOWN` for bytes that no profession owns (or
       whose profession context is :attr:`Profession.UNKNOWN`), and
       preserves the raw byte on :attr:`Agent.elite_raw` for forensics.

       Forward-compat: new byte collisions are added to
       :data:`_ELITE_BYTE_DISAMBIGUATION` alongside this function, not
       silently into the enum mapping.
       """
       if raw_byte in _ELITE_BYTE_DISAMBIGUATION:
           table = _ELITE_BYTE_DISAMBIGUATION[raw_byte]
           return table.get(profession, EliteSpec.UNKNOWN)
       try:
           return EliteSpec(raw_byte)
       except ValueError:
           return EliteSpec.UNKNOWN
   ```

2. `models.py` — on `Agent.elite`, update the docstring to:

   ```python
   elite: EliteSpec = EliteSpec.UNKNOWN
   """The disambiguated elite specialization.

   Populated by the parser via
   :func:`disambiguate_elite_spec` from :attr:`elite_raw` and the
   surrounding :attr:`profession` context. The bare
   ``EliteSpec(elite_raw)`` cast is FORBIDDEN at parse time -- it
   mis-classifies Soulbeast (byte 55) as Daredevil and Weaver (63)
   as Renegade. The raw byte is preserved on :attr:`elite_raw` for
   forensic re-runs of the disambiguator with a different profession
   context if the classification is challenged.
   """
   ```

3. `models.py::__all__` — append `"disambiguate_elite_spec"` (one new public surface) and append `"_ELITE_BYTE_DISAMBIGUATION"` only if you want it importable (keep underscored prefix → stay out of `__all__`; it's an implementation detail of the function).

## Tests (6 hermetic, NEW file `libs/gw2_core/tests/test_gw2_core_models.py`)

- `test_disambiguate_byte55_ranger_returns_soulbeast` — `disambiguate_elite_spec(55, Profession.RANGER) is EliteSpec.SOULBEAST` (the high-leverage case: ~30% of WvW players).
- `test_disambiguate_byte55_thief_returns_daredevil` — `disambiguate_elite_spec(55, Profession.THIEF) is EliteSpec.DAREDEVIL`.
- `test_disambiguate_byte55_warrior_returns_unknown` — `disambiguate_elite_spec(55, Profession.WARRIOR) is EliteSpec.UNKNOWN` (no profession owns byte 55 with warrior context).
- `test_disambiguate_byte63_elementalist_returns_weaver` — `disambiguate_elite_spec(63, Profession.ELEMENTALIST) is EliteSpec.WEAVER`.
- `test_disambiguate_byte63_revenant_returns_renegade` — `disambiguate_elite_spec(63, Profession.REVENANT) is EliteSpec.RENEGADE`.
- `test_disambiguate_unknown_byte_returns_unknown` — `disambiguate_elite_spec(999, Profession.GUARDIAN) is EliteSpec.UNKNOWN` (forward-compat: bytes the catalogue doesn't know fall through cleanly).

## Rejected alternatives

- **Bake the disambiguation into `EliteSpec.from_raw(raw, profession)` as a classmethod** → awkward (an enum doesn't take `profession` in its constructor) and hides the dispatch table from `repr(EliteSpec)`. The standalone function is more discoverable and matches the docstring convention in design plans. REJECTED.
- **Forbid the bare `EliteSpec(raw)` cast at runtime (raise `TypeError`)** → breaks the parser's read path before the helper gets called; the parser's job is to call the helper, not forbid the cast. The docstring update + the parser-side fix (plan 065) are the right enforcement layer. REJECTED.
- **Move the dispatch table to `libs/gw2_evtc_parser` instead of `gw2_core`** → conceptually backwards: the parser imports from `gw2_core` (which is the SOURCE-OF-TRUTH for game data per `__init__.py`'s module docstring). The dispatch IS game data; `gw2_core` owns it. REJECTED.
- **Add a `UNKNOWN` fallback for ALL ambiguous bytes unconditionally** → silent misclassification stays silent. The explicit dispatch table surfaces both the ambiguity and the disambiguation rule in code review. REJECTED.
- **`functools.lru_cache` on `disambiguate_elite_spec`** → the function is already O(1) (single dict lookup); caching only adds complexity for no measurable win. The dispatch table is small enough that the no-cache path always wins. REJECTED.
- **Make the table an enum-member-driven dispatch (e.g. `EliteSpec.SOULBEAST.owns_bytes(55)`)** → couples ownership to the value rather than the byte; defeats the purpose of having a single byte → profession resolution. REJECTED.

## Dependency graph

- Independent from plan 089 (different file region in `__init__.py` vs `models.py` enum block).
- **REQUIRED-BY** plan 065 v0.9.21 (parser call-site fix): plan 065 finessed `parser.py::_decode_agent` to `import disambiguate_elite_spec(...) from gw2_core per plan 037`, but the function doesn't exist. Plan 090 ships the function so the parser PR can land; sequencing: plan 090 ships first, then plan 065's parser edit imports it.
- **REQUIRED-BY** plan 037 v0.9.11 (the design doc / plan that originally promised the function). Closes that promised surface.
- No interaction with plan 091 (different field on a different model).
