# Plan 099 (v0.9.32) — `interface.py::parse_events` docstring UPDATE for Phase 8

## Files touched
- `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py` (docstring update on `parse_events` only; no signature or behaviour change)

## Findings (audit)

- `interface.py::EvtcParser::parse_events` docstring (lines 66-95) lists the yielded event types as "`DamageEvent` + `HealingEvent`" only:
  > "Yield every ``DamageEvent`` + ``HealingEvent`` from the cbtevent block."
- The return-type annotation `Iterator[Event]` correctly delegates to the discriminated union (Pydantic v2 PEP 695 `type Event = Annotated[DamageEvent | HealingEvent | BuffRemovalEvent, Field(...)]` per `gw2_core.models` Phase 8).
- So the Runtime TYPE is correct (PEPs pull `Event` from `gw2_core`, which after plan 090 v0.9.29 includes `BuffRemovalEvent`).
- But the docstring is OUT-OF-DATE. A reader of the protocol-facing docstring would model the parser as yielding ONLY damage + healing events, contradicting what `gw2_core.models.BuffRemovalEvent` actually says (Phase 8 ships the third Event union member, and plan 083 v0.9.27 plans an `EventBucket.buff_removal_total` field that depends on the parser yielding `BuffRemovalEvent`).
- The downstream Effect: a maintainer reading `parse_events`'s docstring would think "Phase 8 hasn't shipped" because the protocol doesn't mention it. Real-world impact: low (mypy / runtime catches the type), but documentation drift can mislead future audits and contributor reviews.

## Fix

Replace the docstring on `parse_events` (lines 66-95):

```python
def parse_events(self, source: BinaryIO | bytes) -> Iterator[Event]:
    """Yield every event from the cbtevent block.

    Phase 8 ships the full heterogeneous ``Iterable[Event]`` stream:
    the discriminated union over ``DamageEvent`` + ``HealingEvent``
    + ``BuffRemovalEvent``. ``Event`` lives in :mod:`gw2_core.models`.

    The ``is_statechange`` flag is the primary discriminator:
    records with ``is_statechange != 0`` are statechange /
    buff-apply / defiance-bar events and are NOT yielded here.

    For records with ``is_statechange == 0``, the ``is_nondamage``
    flag picks the event kind:

    - ``is_nondamage == 0``: direct damage. Yield a
      :class:`~gw2_core.DamageEvent` carrying the damage
      magnitude (clamped via ``max(0, value)``).
    - ``is_nondamage > 0`` AND ``buff_dmg == 0``:
      outgoing-heal (arcdps Convention A + Elite Insights
      parity). Yield a :class:`~gw2_core.HealingEvent`
      carrying the heal magnitude (also clamped).
    - ``is_nondamage > 0`` AND ``buff_dmg > 0``: outgoing
      buff-strip (Phase 8). A single arcdps ``cbtevent``
      record represents BOTH an outgoing heal AND a buff
      strip (corrupting / confusion skills); the parser
      yields BOTH a :class:`~gw2_core.HealingEvent` (with
      ``healing = value``) AND a
      :class:`~gw2_core.BuffRemovalEvent` (with
      ``buff_removal = buff_dmg``). See
      :class:`~gw2_core.BuffRemovalEvent` for the
      decision rule on when a single record yields two
      events vs one.

    The heterogeneous stream is routed through
    ``gw2_analytics`` aggregators by ``isinstance``
    branching on the subclass; consumers do not need to
    decode ``event_type`` literally.

    Truncation is lenient: trailing bytes < 64 yield no
    event and produce no exception. Callers should check
    the yielded count against the expected arcdps fight
    length.

    Args:
        source: Either raw EVTC bytes, or any
            seekable/readable binary IO object exposing
            :py:meth:`read`.
    """
    ...
```

Net effect on the file: ~30 lines of docstring replace ~30 lines of docstring; no signature change, no behaviour change, no import change, no test fixtures needed (the runtime-bearing lines of code are unaffected). The only observable change in the test suite is that `inspect.getsource(EvtcParser.parse_events)` reflects the new docstring text.

## Tests (3 hermetic, NEW or append to `libs/gw2_evtc_parser/tests/test_interface.py`)

- `test_parse_events_docstring_mentions_buff_removal_event` — `inspect.getsource(EvtcParser.parse_events)` regex finds the literal phrase `"BuffRemovalEvent"` in the docstring. Defensive: catches a future regression where the docstring drift back to Phase 7 wording.
- `test_parse_events_docstring_mentions_phase_8` — same idea: regex finds `"Phase 8"` in the docstring. Defensive: catches a regression where the version anchor falls out of date.
- `test_parse_events_signature_unchanged` — `inspect.signature(EvtcParser.parse_events).parameters == {"self", "source"}` AND return annotation `Iterator[Event]` (sourcing via `get_type_hints(EvtcParser.parse_events)`). Defensive: confirms the signature is byte-identical; only the docstring changed.

## Rejected alternatives

- **Also update the implementation `parse_events` docstring in `parser.py`** to match — the Protocol's docstring is the canonical contract; the implementation docstring should mirror it (DRY refactor: have the implementation docstring `"""See :meth:`EvtcParser.parse_events` for the contract."""`). Cross-file dedup is a separate concern, recommended as a v0.9.x follow-up after this audit. REJECTED (out of scope for this plan; flagged as a v0.9.x+ follow-up).
- **Add a `parse_buff_strips(self, source) -> Iterator[BuffRemovalEvent]` separate method to the Protocol** — splits the API surface; legacy callers would have to switch method calls. The Phase 8 discriminated-union design is the cleaner single-method abstraction; the protocol stays as-is. REJECTED.
- **Make `parse_events` yield STRICTLY `Iterator[DamageEvent | HealingEvent]` (no buffs) and add a SEPARATE `parse_buffs` for `Iterator[BuffRemovalEvent]`** — re-fragments the API. A discriminated union IS the single-call abstraction. REJECTED.
- **Skip the fix (the type annotation is correct, only the docstring is stale)** — leaves the maintenance hazard in place. A 30-line docstring update + 3 regression tests is the minimum cost. REJECTED.

## Dependency graph

- Independent: touches `interface.py` docstring only.
- Parallel-safe with plans 098 / 100 (different file regions).
- Documentation-alignment with `gw2_core::models::BuffRemovalEvent` docstring (Phase 8 cross-link): the two docstrings are now cross-referenced; the `parser.py` docstring alignment is a v0.9.x+ follow-up.
