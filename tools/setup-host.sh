#!/usr/bin/env bash
#
# setup-host.sh -- consolidated host-prep script for the Gw2Analytics zevtc-ingest
#                 + SSD auto-mount + GitHub PR workflow.
#
# Bundles the 3 follow-ups that are sudo-bound (smartmontools install + SMART
# probe + /etc/fstab edit + mount -a verification) into ONE sudo block, then
# runs the interactive gh-auth + `gh pr create` step separately. Idempotent:
# each step exits 0 if already done.
#
# Usage:   ./tools/setup-host.sh [--no-pr]
#   --no-pr   skip the gh auth + PR-creation block (useful when working
#             without GitHub internet access)
#
# Requires: bash 5+, systemd (auto-mount at /run/media/$USER/<label>), sudo.

set -euo pipefail

# --------------------------------------------------------------------------
# 0. PRELUDE
# --------------------------------------------------------------------------

readonly SSD_DEV=/dev/sdb1
readonly SSD_MNT="/run/media/${USER}/Raspberry-P"
readonly SSD_UUID=1E18-2168
# umask=0022 → mode 0644 (user:rw, group:r, world:r) — acceptable for a single-user
# desktop where the drive holds personal photos + backups. If the host runs a
# multi-user system, tighten to umask=0077 (mode 0600, owner-only). The
# nofail flag is mandatory: keeps boot working even when the SSD is unplugged.
# uid=1000 hardcoded (NOT ${UID}): the script runs under sudo, where
# ``\$\{UID\}`` resolves to 0 (root) -- roddy's actual uid is 1000
# regardless of sudo context. Tests: ``id -u roddy`` returns 1000 on
# this host. umask=0022 keeps the drive world-readable by default
# (safe for a single-user desktop; tighten to umask=0077 if
# multi-user).
readonly SSD_FSTAB_LINE="UUID=${SSD_UUID}  ${SSD_MNT}  exfat  defaults,nofail,noatime,uid=1000,gid=1000,umask=0022  0  0"

MODE_PR=1
for arg in "$@"; do
  case "$arg" in
    --no-pr)  MODE_PR=0 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

echo "=================================================================="
echo " Gw2Analytics host-prep :: setup-host.sh"
echo "=================================================================="
echo " SSD device:    $SSD_DEV"
echo " SSD mountpoint: $SSD_MNT"
echo " SSD UUID:       $SSD_UUID"
echo " Mode:           $([ $MODE_PR -eq 1 ] && echo 'full (smart + fstab + gh)' || echo 'smart + fstab only (--no-pr)')"
echo "=================================================================="

# --------------------------------------------------------------------------
# STEP 1 -- smartmontools install + SMART health probe (OPTIONAL).
#
# Without smartmontools, you cannot query the SSD's wear-leveling count,
# reallocated sectors, or temperature. The Micron CT2000X8SSD9 (the X8
# portable) supports SMART over USB; the bus_type matters and may report
# via a vendor-specific bridge driver.
# --------------------------------------------------------------------------

if command -v smartctl >/dev/null 2>&1; then
  echo "[1/4] smartctl already present -- probe only"
  sudo smartctl -i "$SSD_DEV" 2>&1 || true
  sudo smartctl -H "$SSD_DEV" 2>&1 || true
  sudo smartctl -A "$SSD_DEV" 2>&1 || echo "  (SMART attribute probe failed -- bridge may not support SMART)"
else
  echo "[1/4] smartmontools not installed -- attempting install now"
  if command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm smartmontools
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y smartmontools
  else
    echo "  ! No pacman/apt detected -- install smartmontools manually then re-run."
    exit 1
  fi
  sudo smartctl -i "$SSD_DEV"
  sudo smartctl -H "$SSD_DEV"
fi

# --------------------------------------------------------------------------
# STEP 2 -- /etc/fstab permanent auto-mount for /dev/sdb1.
#
# The `nofail` flag means the system will keep booting even if the SSD is
# physically absent; the `umask=0022` gives the world read-only access
# which is right for a media+backup drive. Backup is mandatory before the
# edit; abort on collision (line already exists).
# --------------------------------------------------------------------------

echo "[2/4] /etc/fstab auto-mount line for $SSD_UUID"
FSTAB=/etc/fstab
FSTAB_BAK="${FSTAB}.bak-$(date +%F-%H%M%S)"

if grep -qE "^UUID=${SSD_UUID}\\b" "$FSTAB" 2>/dev/null; then
  echo "  ! UUID=${SSD_UUID} is already in $FSTAB -- skipping the append"
else
  sudo cp -p "$FSTAB" "$FSTAB_BAK"
  echo "  + backed up to $FSTAB_BAK"
  echo "$SSD_FSTAB_LINE" | sudo tee -a "$FSTAB" >/dev/null
  echo "  + appended: $SSD_FSTAB_LINE"
fi

# Verify the new entry parses. Process stderr + stdout separately so we
# can distinguish "line parsed cleanly" (mount reports it) from a real
# fstab-syntax error. The SSD line will be parenthesized in the verbose
# output as `(UUID=1E18-2168)` if mounted, or simply reported if remounted.
MOUNT_OUT=$(sudo mount -a -v 2>&1) || MOUNT_RC=$?
MOUNT_RC=${MOUNT_RC:-0}
echo "$MOUNT_OUT" | grep -E "$SSD_UUID|$SSD_MNT" || true
if [ "$MOUNT_RC" -ne 0 ]; then
  echo "  ! mount -a exited non-zero ($MOUNT_RC) -- fstab line may be malformed. Check:sudo mount -a -v 2>&1 | grep -B2 -A2 "error""
fi

# --------------------------------------------------------------------------
# STEP 3 -- findmnt verification
# --------------------------------------------------------------------------

echo "[3/4] findmnt verification"
findmnt "$SSD_MNT" 2>&1 || echo "  (device not currently mounted -- plug it in to verify)"

# --------------------------------------------------------------------------
# STEP 4 -- gh auth + PR creation (interactive).
#
# `gh auth login --web` prints a one-time code + a URL; the user pastes
# the code into https://github.com/login/device within ~1 hour. After
# auth, we open TWO PRs:
#   * feat/combat-readout-wave6-7           (the wave6/7 UI commit 2528855)
#   * feat/integrate-zevtc-fixture          (the 3 zevtc-ingest commits)
# --------------------------------------------------------------------------

if [ "$MODE_PR" -eq 1 ]; then
  echo "[4/4] gh auth + PR creation"
  if ! [ -t 0 ] || ! [ -t 1 ]; then
    echo "  ! gh auth login requires a TTY. Re-run from an interactive shell, or run with --no-pr if you only need smart + fstab."
  elif gh auth status >/dev/null 2>&1; then
    echo "  + gh CLI is already authenticated -- skipping login"
  else
    echo "  + gh auth login (device-flow)"
    echo "    Paste the one-time code at https://github.com/login/device"
    gh auth login --web --git-protocol https --hostname github.com
  fi

  PR_DESC="/tmp/PR-description-wave6-7.md"
  if [ -f "$PR_DESC" ]; then
    echo "  + Opening PR for feat/combat-readout-wave6-7 (using $PR_DESC)"
    gh pr create --base main --head feat/combat-readout-wave6-7 \
      --title "feat(web): Wave 6/7 Combat-Readout UI" \
      --body-file "$PR_DESC"
  else
    echo "  ! $PR_DESC is missing -- falling back to inline body"
    gh pr create --base main --head feat/combat-readout-wave6-7 \
      --title "feat(web): Wave 6/7 Combat-Readout UI" \
      --body "See commit 2528855 on the branch. TSC=0; runtime=HTTP 200; 4 data-testids + 4 player names render via 4 AG Grid tables on /fights/[id]?tab=readout."
  fi

  echo "  + Opening PR for feat/integrate-zevtc-fixture"
  gh pr create --base feat/combat-readout-wave6-7 --head feat/integrate-zevtc-fixture \
    --title "test(web): add EVTC binary fixture + magic-bytes integrity test" \
    --body "Companion PR to feat/combat-readout-wave6-7.

Adds 648-byte stub EVTC fixture lifted from WvW_Analytics/uploads/ + a 4-test vitest module asserting the EVTC magic-bytes + digit-shape header + non-zero prefix byte.

TSC=0; vitest=4 PASS.

Commits: fd4d018 (add fixture + tests) + 2e46d5e (relax bytes 4-11 to digit-shape regex) + e721796 (mark *.evtc binary in .gitattributes; replace hand-typed evtc.md URL with non-URL forward reference)."
else
  echo "[4/4] --no-pr set -- skipping gh auth + PR create"
fi

# --------------------------------------------------------------------------
# FIN
# --------------------------------------------------------------------------

echo "=================================================================="
echo " setup-host.sh DONE"
echo "=================================================================="
echo "Next steps:"
echo "  - Verify the wave6/7 UI serves at:"
echo "       http://localhost:3000/fights/fixture-fight-001?tab=readout"
echo "  - Run pnpm test once sharp is approved:"
echo "       cd web && pnpm approve-builds && pnpm test --run"
echo "  - Real zevtc parser: see feat/integrate-zevtc-fixture commits for"
echo "    the SCAFFOLD landing pad (web/src/lib/evtc-parser.ts is TBD)."
echo "=================================================================="
