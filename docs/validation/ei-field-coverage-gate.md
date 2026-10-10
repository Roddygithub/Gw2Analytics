# Elite Insights field-coverage gate

**Status: OPEN — not yet executed.** This is the hard gate that must pass before
the home-grown parser's event path is removed. It cannot be satisfied by
inspection alone; it requires running the pinned EI build over the 35-log
certification corpus and comparing each product projection field-by-field.

## Why this gate exists

The product reads typed, raw-ish event JSONL sources for timelines, readout,
positions/heatmaps, damage windows, buff events, rotation and time-aware
identity. EI detailed-WvW JSON is a different shape. Deleting the old event path
before proving each consumer can be fed from EI would silently change product
behaviour.

Do **not** fabricate old raw-event semantics from insufficient aggregated EI
data. Where EI cannot supply the required granularity, choose deliberately:
extend the EI fork with a narrow WvW export, use a more detailed EI output mode,
materialize normalized events at ingestion, or redesign the product projection.

## Current event consumers (evidence from code)

Sources that consume `gw2_core` events / the compressed event blob
(`events_blob_uri` -> `_event_dispatch.build_event_iterator`):

| Product surface | Current module(s) |
| --- | --- |
| Damage / DPS (incl. per-target) | `gw2_analytics/player_damage.py`, `target_dps.py`, `damage_predicates.py`, `condi_power_split.py` |
| Healing | `gw2_analytics/player_heal.py`, `target_healing.py` |
| Strips / cleanses | `gw2_analytics/target_buff_removal.py`, `player_boons.py` |
| Boons / uptime | `gw2_analytics/buff_state.py`, `buff_uptime.py`, `buff_dispatch.py`, `initial_buffs.py` |
| Rotation / casts | `gw2_analytics/rotation.py`, `skill_usage.py` |
| Down / death / CC | `gw2_analytics/down_contribution.py`, `player_defense.py` |
| Timelines | `gw2_analytics/per_fight_timeline.py`, `per_player_timeline.py`, `event_window.py` |
| Identity / ownership | `gw2_analytics/temporal_identity.py` |
| Positions / heatmaps | `gw2_analytics/position_analysis.py` |
| Squad / cross-fight | `gw2_analytics/squad_rollup.py`, `multi_fight.py`, `cross_account_timeline.py` |
| API aggregation from the blob | `apps/api/src/gw2analytics_api/routes/fights/blob_loader.py`, `fight_aggregators.py`, `player_aggregators.py`, `_event_dispatch.py` |

## Matrix (to be completed against EI 3.26 detailed-WvW output)

Fidelity statuses: `exact`, `equivalent-after-transformation`,
`aggregated-but-sufficient`, `missing`, `ambiguous`,
`requires-EI-fork-export-change`, `product-feature-must-be-redesigned`.

| Current field / event | Consumer(s) | EI source | Normalization rule | Status |
| --- | --- | --- | --- | --- |
| `DamageEvent` (value, result, connected, absorbed, condi flag) | damage/DPS, readout, timelines | EI damage events / `DamageModifiers` | map result bitfield, separate arcdps channel vs EI condition class | **unverified** |
| `HealingEvent` | healing, readout | EI healing events | heal magnitude + peer gating | **unverified** |
| Buff apply / remove / extension / activation | boons, uptime, initial state | EI `buffUptimes` + extension/removal data | regenerate queue/stack semantics | **unverified — high risk** |
| Skill casts / instant casts | rotation, skill usage | EI rotation data (`RawTimelineArrays`, casts) | ordering + ICD | **unverified** |
| Down / death / grouped outcomes | down contribution, defense | EI mechanics / death events | classify | **unverified** |
| CC / statechange events | down contribution, defense | EI CC/statechange data | map statechange constants | **unverified** |
| Agent identity / awareness windows | temporal identity, all per-player | EI player entries (`firstAware`/`lastAware`, multiple slices) | time-aware account/character resolution | **unverified — high risk** |
| Ownership / minion / pet attribution | identity, damage attribution | EI master/minion relationships | resolve at event time | **unverified — high risk** |
| Positions / position samples | heatmaps, `dist_to_commander` | EI combat replay | requires `ParseCombatReplay` or a dedicated export | **unverified — may require fork export** |

## How to run the gate

1. Use the pinned EI build (`GW2EICLI-v3.26.0.0`, config
   `.tooling/ei-local.conf` with `DetailledWvW=true`).
2. Run it over the 35-log certification set (`scripts/ei-parity/corpus.txt`,
   SHA-256 manifests in the recovery root). The raw logs and EI exports stay
   private and must never be committed.
3. Fill in the "EI source", "normalization rule" and "status" columns from
   actual output, one consumer at a time.
4. For every `missing` / `ambiguous` / `requires-EI-fork-export-change` row,
   record the deliberate decision (fork export, detailed mode, ingestion-time
   materialization, or product redesign) before deleting the old path.
5. Add a synthetic-fixture acceptance test per row so the gate cannot regress.

## Related

- `docs/architecture/parser-boundary.md` — the adapter the EI boundary will land in.
- `docs/validation/ei-parity-certification/` — SPEC, certification matrix and stories.
