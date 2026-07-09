# Plan 064 — v0.9.20: `docs/v0.9.0-combat-readout-design.md` "deferred to v1.0+" banner

## Drift base

`44ea862`. Docs cleanup only — no code changes, no migration.

## Surface

`docs/v0.9.0-combat-readout-design.md` (the canonical combat
readout design doc, 13 sections + the §9 build sequence),
`docs/ROADMAP.md` (for the "v1.0 candidates" shortlist).

## Finding

The design doc has a header that reads:

```
**Status:** Draft (post-v0.8.0)
**Backend dependency:** parser extension (statechange), skills DB, role classifier
**Web dependency:** new AG Grid components + 4 table layouts
**Target:** v0.9.0 (backend first, then web as a follow-up minor — the v0.7.0 / v0.7.1 / v0.8.0 pattern)
```

The "Target: v0.9.0" makes the doc look like an upcoming-cycle
doc. But the v0.9.0 cycle did NOT ship the combat readout (the
v0.9.0 close-out shipped shared timeline chart + filter by
profession + visual regression suite expansion per the ROADMAP
"v0.9.0 close-out" section). The combat readout is now a v1.0+
candidate (per ROADMAP §1, "Combat readout (4 tables: Damage /
Heal / Boons / Defense)", marked "**XL+**" effort, "Blocked on
the statechange parser + the skills DB").

A new reader who finds the design doc (e.g., via a search
for "combat readout" or "lecture combat") will see the
"Target: v0.9.0" + "Status: Draft" and may believe it's the
next-cycle doc. The actual shortlist is in ROADMAP §1.2.

## Fix

Add a banner at the top of the doc, between the `# v0.9.0
combat readout design` heading and the `**Status:**` line:

```
> **⚠️ DEFERRED TO v1.0+** (NOT scheduled for v0.9.x)
>
> This design doc was authored for the v0.9.0 cycle but was
> deferred because the v0.9.0 cycle shipped higher-priority
> items (shared timeline chart, filter by profession, visual
> regression suite). The combat readout is the longest-cycle
> v1.0 candidate; it is blocked on the statechange parser
> extension (a v1.4+ parser change) + a new `libs/gw2_skills`
> library (a static JSON dataset of ~1000 entries) + the role
> classifier heuristic (calibration against the user's local
> "thousands of logs" is required before the heuristic
> ships).
>
> The canonical shortlist is in `docs/ROADMAP.md` §1.2. The
> build sequence in §9 below is **not** the current
> implementation plan; it is the design-AS-WRITTEN at the
> v0.8.0 brainstorming sessions. A future maintainer who
> picks up this work should re-estimate the build sequence
> against the current code (the §9 dependencies on a v1.4+
> parser + a new `libs/gw2_skills` library have not landed
> in the codebase as of v0.9.2).
>
> This doc is preserved as the design specification; the
> "Target: v0.9.0" header is historical context. The actual
> implementation cycle will start from a fresh spike + a
> refined build sequence.
```

Also update the `**Status:**` line to add the deferral:

```
**Status:** Draft (post-v0.8.0) — **DEFERRED to v1.0+** (see
banner above; not scheduled for v0.9.x; canonical shortlist in
`docs/ROADMAP.md` §1.2)
```

## Why preserve the doc instead of deleting

The doc is the canonical specification of the combat readout
feature (§2-§7 are the table-by-table column definitions +
clarifications + icon source; §9 is the build sequence; §11 is
the open questions; §13 is the default sort). A future
maintainer who picks up the combat readout work will need this
spec to drive the implementation. Deleting it would force the
maintainer to re-derive the spec from the brainstorming
sessions.

The banner preserves the doc AS-A-SPEC while making it clear
that the implementation is deferred. This is the canonical
"historical spec + deferral banner" pattern for design docs
that have not landed in their target cycle.

## Risks

- A future implementer who reads the doc + the banner + the
  ROADMAP §1.2 shortlist may still be confused by the
  §9 build sequence (which says "1. Statechange parser
  (libs/gw2_evtc_parser)" — a real prerequisite, not yet
  built). The banner explicitly calls this out: "the §9
  dependencies on a v1.4+ parser + a new `libs/gw2_skills`
  library have not landed in the codebase as of v0.9.2".
- The "Target: v0.9.0" in the original header is a historical
  fact (the doc was authored for v0.9.0). The banner
  preserves this fact but makes the deferral explicit. A
  future maintainer who reads only the original header (and
  misses the banner) may still be confused; the in-header
  `**DEFERRED to v1.0+**` annotation is the belt-and-braces
  safeguard.

## Tests

1. `test_doc_has_deferred_banner` — read the doc; assert the
   "DEFERRED TO v1.0+" banner is present (the exact
   `> **⚠️ DEFERRED TO v1.0+**` line).
2. `test_doc_status_line_includes_deferred` — read the doc;
   assert the `**Status:**` line includes the
   "DEFERRED to v1.0+" annotation.
3. `test_doc_references_roadmap_shortlist` — read the doc;
   assert the doc references `docs/ROADMAP.md` §1.2 (the
   canonical shortlist).

## Rejected alternatives

- **Delete the doc + re-derive from the brainstorming
  sessions**: out of scope (the doc is the canonical
  specification; deleting it would force the maintainer to
  re-derive the column definitions + the role classifier
  heuristic + the default sort).
- **Move the doc to a `docs/deferred/` subdirectory + add a
  top-level "see also" in `docs/README.md`**: out of scope
  (the docs directory does not have a `README.md`; the
  `CONTRIBUTING.md` mentions the design docs implicitly
  via the "Regenerating the web TypeScript client" section
  + the ROADMAP §6 "open questions" references). A future
  plan can add a `docs/README.md` if the doc count grows.
- **Update the §9 build sequence to reflect the v0.9.2
  codebase** (i.e., drop the "statechange parser" + "skills
  DB" prerequisites that have not landed): out of scope. The
  build sequence is a forward-looking plan; the prerequisites
  are the canonical blockers. Refreshing the build sequence
  would require re-estimating the effort + re-deriving the
  dependency graph, which is a future maintainer's
  responsibility when they pick up the work.
- **Add a CI drift check that asserts the banner is
  present**: out of scope (the banner is a human-curated
  marker; a CI check would force a regex match on the
  banner text, which is fragile).
