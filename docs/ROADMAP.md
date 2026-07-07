# Roadmap

**Status:** Living document. Last refreshed after the v0.8.0 release.

This file is the **single source of truth** for "what's left to do" on
the project. It supersedes any ad-hoc "what's next" list in the README
or the CHANGELOG. It is meant to be edited at every release tag so
that the next session can pick up exactly where the previous one left
off.

---

## Current state (v0.8.0)

- **Latest shipped tag:** `v0.8.0` (Phase 9 of web: account-level
  historical timelines).
- **Test count:** 165 active tests (115 pytest across `libs/gw2_*` +
  `apps/api`, 50 vitest across `web/`, plus 1 conditionally skipped
  real-fixture integration test in
  `libs/gw2_evtc_parser/tests/test_parser.py`).
- **Phase status (per README):** Phase 0 through Phase 9 of web all
  marked ✅.
- **Architecture:** `gw2_evtc_parser` → `gw2_core` → `gw2_analytics` →
  `apps/api` (FastAPI) + `gw2_api_client` (outbound) → `web` (Next.js
  16). Pure-Python parser, gated behind an `EvtcParser` Protocol so a
  Rust + PyO3 binding is a drop-in replacement (no churn elsewhere).

---

## 1. v0.9.0 candidates (designed, not yet implemented)

| Item | Source | Effort | Why now |
|---|---|---|---|
| **Backend v0.8.0 "webhooks"** — `POST/GET/DELETE /api/v1/webhooks`, HMAC-SHA256 outbound signature, retry+DLQ worker, `webhook_subscriptions` table | `docs/v0.8.0-backend-design.md` (Draft) | **L** | The design doc is complete (SQL schema + API contract + worker design + future-work section). Discord bot + CI integration are the explicit use cases. **Lowest-effort, highest-leverage candidate.** |
| **Cross-account comparison** — overlay 2-4 accounts' timelines on the same chart | `docs/v0.8.0-web-design.md` §6 | **M** | Reuses `PlayerTimelineChart` from v0.8.0; the multi-series overlay is the main extension. |
| **Per-day bucketing on the timeline** — aggregate all fights in a day to one chart point | `docs/v0.8.0-web-design.md` §7 | **S** | Analyst use case. Tweak on the v0.8.0 endpoint + chart, no new infra. |
| **Skill build analyser** — parse the loadout from the EVTC header, show per-skill DPS contribution | `docs/v0.8.0-web-design.md` §6 | **M** | Builds on `SkillUsageTable` from v0.7.1. |
| **Real-time DPS meter** — WebSocket-based live DPS display during a parse in progress | `docs/v0.8.0-web-design.md` §6 | **XL** | Auth + reconnect + partial-parse handling. Own dedicated cycle. |
| **Combat readout (4 tables: Damage / Heal / Boons / Defense)** | `docs/v0.9.0-combat-readout-design.md` | **XL+** | The user spec from the brainstorming sessions. Blocked on the statechange parser + the skills DB. **Longest cycle, highest analyst value.** |

### 1.1 "Ready to implement" shortlist (design doc complete)

The 4 items above with a complete design doc. Any of these can be
started as soon as the maintainer gives the green light:

1. **Webhooks backend** — `docs/v0.8.0-backend-design.md` is
   shippable as-is.
2. **Cross-account comparison** — reuses v0.8.0 chart.
3. **Per-day bucketing** — small tweak to v0.8.0 endpoint.
4. **fight_player_summaries materialization** (see §2) — perf debt
   with a clear SQL design (trivial migration).

---

## 2. Tech debt / performance (signaled in the CHANGELOG, never resolved)

| Item | Source | Effort | Impact |
|---|---|---|---|
| **Materialise `fight_player_summaries` table** | CHANGELOG v0.7.0 "Notes" | **M** | Avoids the 5-30s O(fights × events) per-request re-walk on `/players` when there are 100+ fights. Route becomes a pure SQL aggregation. |
| **DRY refactor of `_compute_contributions`** | CHANGELOG v0.7.0 + code-reviewer round 72 | **M** | Function has a documented `noqa: PLR0912`. To split once `fight_player_summaries` lands (less critical then). |
| **Rust + PyO3 parser binding** | `CONTRIBUTING.md` ("anticipated but not in scope") | **XL** | The `EvtcParser` Protocol is already in place for the swap. Pure perf wins (10-100x). Long-term investment, not a v0.9.0 priority. |
| **Resolve player names in `TargetFilter`** (instead of raw `agent_id`) | CHANGELOG v0.6.0 "Notes" | **S** | UX win. Needs either a new `GET /api/v1/fights/{id}/agents` endpoint or denormalisation of names into the events response. |
| **Log scale on the `PlayerTimelineChart` Y-axis** | `docs/v0.8.0-web-design.md` §7 | **XS** | When `damage = 1M` and `strip = 50` the strip line is visually crushed even after per-series normalisation. Add a `scale: "linear" | "log"` prop. |

---

## 3. Strategic items (v1.0+)

- **Multi-tenant scoping** on the webhooks + the gateway
  (single-tenant is the current assumption).
- **Mobile-first redesign** of `/fights/[id]` (desktop is the
  canonical analyst surface today).
- **GraphQL subscription channel** (alternative to webhooks for
  live dashboards).
- **PNG / SVG export of the timeline** (CSV is already covered
  by `CsvDownloadButton`).

---

## 4. Update protocol

At each release tag (`v0.X.Y`):

1. Update the **"Current state"** section (test count, latest
   tag, any new ✅ in the README).
2. Walk §1-3 and **check off** any item that landed in the
   release (move to a "Shipped" subsection at the bottom or
   delete — your call, but the decision must be deliberate).
3. **Re-prioritise** §1 if a new candidate has emerged (e.g.
   a new design doc has been added under `docs/`).
4. **Re-estimate** the effort column if the code-reviewer
   surfaced a hidden cost.
5. Commit the update in the same release PR (or a follow-up
   `docs(roadmap): refresh after v0.X.Y` commit).

---

## 5. Anti-drift notes

- The "Effort" column is **relative** (XS / S / M / L / XL),
  not hours. Keep it coarse so the table stays scannable.
- The "Why now" column is the most valuable: it forces a
  justification for the priority. An item without a "why
  now" reason should be demoted or deleted.
- If a row has been in the table for >2 releases without
  progress AND without a "Why now" update, **delete it** —
  it's noise, not signal.
