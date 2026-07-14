# Host-prep tooling

This directory collects the one-shot setup scripts that bring a fresh
checkout of Gw2Analytics up to a runnable shell.

## setup-host.sh

Bundles the three sudo-bound + interactive follow-ups that the agent
cannot complete unattended:

1. **smartmontools install + SMART probe** — surfaces the SSD's health
   attributes (wear, temperature, reallocated sectors) over the USB
   bridge. Required for any long-term data retention on the Micron
   CT2000X8SSD9 external.
2. **/etc/fstab permanent auto-mount** — adds a `nofail` line for the
   1.8 TB Raspberry-P partition so it remounts automatically on boot.
   The backup is mandatory before the append (see `*.bak-*` files).
3. **`gh auth login --web` + 2 PR creations** — opens the device-flow
   auth (paste the one-time code at https://github.com/login/device)
   then creates the two PRs from the wave6/7 + zevtc-ingest branches.

### Usage

```
./tools/setup-host.sh           # full mode (smart + fstab + gh)
./tools/setup-host.sh --no-pr   # skip gh auth + PR creation
```

The script is **idempotent**: each step exits 0 if already complete
and skips re-running. Backups are timestamped (e.g. fstab.bak-2026-07-14).

### Pre-conditions

- Run as user `roddy` (uid 1000) with `sudo` available.
- The Micron CT2000X8SSD9 SSD must be physically connected at
  `/dev/sdb1` for SMART probes. The script will still succeed (and
  the fstab entry will be added) if the SSD is unplugged at runtime.
- A GitHub account with push access to `Roddygithub/Gw2Analytics`.

### What it does NOT do

- It does not parse real `.zevtc` ArcDPS logs — that's a separate
  TypeScript effort currently SCAFFOLD'd at
  `web/tests/unit/evtc-magic.test.ts`.
- It does not push local commits — those need to land on the
  feature branches first (see `feat/integrate-zevtc-fixture`).
- It does not run `pnpm approve-builds` (the sharp@0.34.5 native
  binary build) — that's an interactive `pnpm` decision and must
  be done before `pnpm test --run` will succeed.
