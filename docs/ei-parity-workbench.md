# Elite Insights parity workbench

Elite Insights is the reference implementation. This document describes how to
reproduce its output locally and diff the in-house parser against it, so parity
work is measured rather than asserted.

Everything below runs offline. No log ever leaves the machine — dps.report and
the EI web uploader are not involved.

## 1. One-time setup

Elite Insights ships a framework-dependent .NET 8 CLI that runs on macOS and
Linux unchanged.

```bash
curl -sSL -o /tmp/dotnet-install.sh https://dot.net/v1/dotnet-install.sh && chmod +x /tmp/dotnet-install.sh && /tmp/dotnet-install.sh --channel 8.0 --runtime dotnet --install-dir "$HOME/.dotnet"
```

```bash
mkdir -p .tooling && curl -sL -o .tooling/GW2EICLI.zip https://github.com/baaron4/GW2-Elite-Insights-Parser/releases/download/v3.26.0.0/GW2EICLI.zip && unzip -oq .tooling/GW2EICLI.zip -d .tooling/GW2EICLI
```

`.tooling/` and `zevtc files/` are gitignored: the vendored CLI, the raw logs
and the reference JSON are all local artefacts.

## 2. Generating reference JSON

`scripts/ei-parity/ei.conf` pins the settings that matter for parity — most importantly
`DetailledWvW=true`, which is what makes EI emit per-player WvW detail instead
of a summary, and `RawTimelineArrays=true`.

```bash
export PATH="$HOME/.dotnet:$PATH" && cd .tooling/GW2EICLI && while read -r stem; do dotnet GuildWars2EliteInsights-CLI.dll -c ../../scripts/ei-parity/ei.conf "../../zevtc files/${stem}.zevtc"; done < ../../scripts/ei-parity/corpus.txt
```

Output lands in `.tooling/ei-out/<stem>_detailed_wvw_kill.json`.

## 3. Diffing

```bash
uv run python scripts/ei-parity/ei_diff.py
```

Runs `gw2_analytics.ei_compare.compare_elite_insights` over every corpus log
that has a reference, and prints per-log difference counts plus a histogram of
difference kinds with the per-player and per-target subscripts collapsed
(`players[x].statsAll.totalDmg` → `players.statsAll.totalDmg`), so a systemic
error reads as one large bucket instead of hundreds of unrelated rows.

Useful flags: `--show <regex>` prints raw expected/actual pairs for matching
buckets, `--json <path>` dumps the full report, and positional arguments
restrict the run to named log stems.

Supporting probes in `scripts/ei-parity/`:

| Script | Answers |
| --- | --- |
| `probe_stats.py` | Is a field biased high or low, and by how much? |
| `probe_spec.py` | Does our (profession, elite) decoding match EI's `profession`? |
| `probe_targets.py` | Do EI's `targets[]` resolve onto exactly one agent? |
| `probe_raw_events.py` | Full raw cbtevent fields for one (account, skill). |
| `probe_connected.py` | Which events does EI count as hits that we don't? |
| `solve_results.py` | Which `result` bytes mean "connected" / "invulned"? |

## 4. The corpus

`scripts/ei-parity/corpus.txt` holds 35 stems drawn from the 7 758-log sink, stratified
across all seven months present (2026-01 → 2026-07) and four size tiers per
month. The spread matters because arcdps changes the wire format between
builds: the corpus covers ten distinct `arcVersion` values, including the
2026-05-07 break described in `docs/EVTC2025_FORMAT.md`.

Re-running EI over the whole 7 758-log sink is possible but produces roughly
100 GB of JSON; the stratified corpus is the working set, and a full sweep is
only worth it to confirm a release.
