# Elite Insights baseline

**Decision: pin `v3.26.0.0` for this refoundation.** It is the version the entire
certification corpus and the executed field-coverage gate are anchored to. The
current upstream release is recorded below as the next baseline, with the exact
reason it could not be adopted here.

## Pinned baseline

| Item | Value |
| --- | --- |
| Upstream repository | `https://github.com/baaron4/GW2-Elite-Insights-Parser` |
| Release / version | `v3.26.0.0` (`eliteInsightsVersion` in the export: `3.26.0.0`) |
| Upstream commit | `e4e548bf95b8a4901018a2c6a70058fc9c9e539f` ("updated versions") |
| CLI binary identity | `GuildWars2EliteInsights-CLI.dll` sha256 `5ffe8565a55f2f80a88dc28f4ec0f383fd84a64954c360c47264ecafed7faa38` |
| Distribution archive | `GW2EICLI-v3.26.0.0.zip` sha256 `19fb297e7268f3d4078ce12605382e015768c0be7786b1b0adc0960eb9a11b63` |
| .NET runtime | `Microsoft.NETCore.App 8.0.31` (private `dotnet` host, no SDK required to run the shipped CLI) |
| Export type | detailed WvW (`detailedWvW: true`) |
| Config identity | `.tooling/ei-local.conf` — `SaveOutJSON=true`, `IndentJSON=false`, `SingleThreaded=true`, `ParseCombatReplay=false`, `RawTimelineArrays=true`, `DetailledWvW=true`, all uploads off |
| Schema assumptions | the JSON keys enumerated empirically in `docs/validation/ei-field-coverage.json` |

The `cli_sha256` recorded in `scripts/ei-parity/corpus-baseline.json` resolves to
`GuildWars2EliteInsights-CLI.dll`, not to the zip — verified, so the existing
identity record is accurate and is not a mismatched hash.

`.tooling/` is a developer-local cache and is **not** part of the production
architecture. Where EI is packaged for dev, CI, Docker and the Arq worker is an
open question the process-adapter work must answer (see `parser-boundary.md`).
It is not answered by pointing production code at `.tooling/`.

## Current upstream (not adopted)

| Item | Value |
| --- | --- |
| Latest release | `v3.30.2.0` |
| Default branch HEAD | `99169f511` (= `v3.30.2.0-18-g99169f511`) |
| Releases since the pin | `v3.27.0.0`, `v3.27.1.0`, `v3.28.0.0`, `v3.28.0.1`, `v3.29.0.0`, `v3.30.0.0`, `v3.30.1.0`, `v3.30.2.0` |
| Non-merge parser commits in `v3.26.0.0..v3.30.2.0` | 31 |

Where those commits land inside `GW2EIEvtcParser`, by file count:

`ParsedData/CombatEvents` (116), `EIData/CombatReplay` (106),
`EIData/Mechanics` (81), `LogLogic/Raids` (73), `EIData/Buffs` (54),
`EIData/ProfHelpers` (46), `EIData/DamageModifiers` (30),
`LogLogic/Fractals` (28), `EIData/InstantCastFinders` (17),
`EIData/Statistics` (16), `EIData/Actors` (13).

That is relevant to several of the areas the refoundation cares about:
combat-event/EVTC-adjacent parsing, buffs, actors/identity, instant-cast
detection (which backs EI's rotation output) and combat replay (which backs the
position row the coverage gate flags). Commit subjects include
"split agent info events", "maybe found rank added to name flag",
"when useEIPreProcess, raw log adjusts skill icons using buffs" and
"adjusted slice through reality to avoid parsing errors".

## Why the pin is 3.26.0.0 and not 3.30.2.0

1. All 35 certification exports were produced by the pinned CLI, and
   `corpus-manifest.json` records a per-log `export_sha256`. Moving the baseline
   invalidates every one of those hashes and the executed coverage matrix built
   on top of them.
2. Adopting 3.30.2.0 requires **rebuilding** it. This host has the .NET *runtime*
   only (no SDK) and `/usr/bin/dotnet` is not a working host, so no 3.30.x
   binary can be produced or verified here. A move must therefore be done
   deliberately, on a machine with the .NET 8 SDK, as its own change.
3. The coverage gate's open question (an EI export change for the event stream)
   is orthogonal to the version. Resolving it first, then re-certifying once
   against the then-current release, avoids paying for two re-certifications.

## Upgrade path when the baseline does move

1. Build the new tagged release with the .NET SDK; record the new CLI artifact
   hash and .NET version here.
2. Re-run the pinned corpus through it; refresh `corpus-manifest.json`'s
   `export_sha256` values and `corpus-baseline.json`.
3. Re-run `scripts/ei-parity/field_coverage.py --write`; the gate fails loudly if
   any claimed EI path disappeared in the new schema.
4. Diff `eliteInsightsVersion` and the key set between the two exports and review
   the changes above that touch buffs, actors/ownership, instant casts and
   combat replay, since those back the rows this gate flags.
