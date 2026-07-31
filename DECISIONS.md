# Decisions

## 2026-07-31 — Elite Insights is verified locally, not trusted from memory

**Decision.** Vendor the Elite Insights 3.26.0.0 CLI plus a .NET 8 runtime under
`.tooling/` (both gitignored) and generate reference JSON on this machine.

**Why.** Parity work needs ground truth for the same logs we parse. The
alternative — uploading logs to dps.report for its EI JSON — sends a user's
combat logs to a third party for no benefit, and pins us to whatever version
that service runs. Running EI locally is offline, version-pinned and
reproducible.

It also changes what the parser can be checked against: EI's `Content/*.json`
data files are the authoritative catalogues (`SpecList.json` settled the elite
specialization IDs), and its per-skill `connectedHits` / `invulned` counters are
dense enough to *solve* for arcdps enum semantics rather than guess them.

## 2026-07-31 — Wire-format semantics are resolved in the parser

**Decision.** `DamageEvent` carries `connected`, `absorbed`, `is_condition` and
`shield_damage`, all set by the parser. Consumers ask "did this land" rather
than re-deriving it from the `result` byte.

**Why.** arcdps writes two different enums into `result` and renumbered one of
them on 2026-05-07. Reading it correctly needs the build version, which only the
parser has. Leaving that to every consumer guarantees they drift apart — the
audit found exactly that, with the comparison layer holding one interpretation
and the parser another.

The consequence to accept: hand-built `DamageEvent`s (tests, fixtures) do not
set the flags, so `ei_compare` keeps a documented fallback to the direct-hit
enum for non-condition records.

## 2026-07-31 — Corrected catalogues over preserved comments

**Decision.** Rewrite `EliteSpec` and `_VALID_ELITE_BY_PROFESSION` against EI's
`SpecList.json` and delete the "collision" comments describing shared elite IDs.

**Why.** No such collisions exist — every elite specialization has a unique ID
in the GW2 catalogue. The comments documented an invented constraint, and the
table built on it silently downgraded every Thief and Elementalist elite spec to
its core profession. Verified against every (profession, elite_raw) pair in the
corpus before changing anything.

## 2026-07-31 — Thresholds are not parity

**Position, not yet acted on.** The EI-alignment tests assert
`len(differences) <= 17 / 9 / 7` against logs at hardcoded paths that exist on
one machine. Everywhere else they skip, and pytest reports a skip and a pass
identically. Every defect in `docs/parser-audit-2026-07-31.md` survived a green
suite that way, and the thresholds were last *raised* in PR #89.

Buckets that reach zero should be pinned at zero on a committed fixture. Tracked
in `BACKLOG.md`.
