#!/usr/bin/env bash
# Installation système ponctuelle des wrappers lifecycle GW2Analytics.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo tools/install-gw2a-lifecycle.sh" >&2
    exit 1
fi

readonly repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

install -D -m 0755 "$repo_root/ops/gw2a/gw2a" /usr/local/bin/gw2a
install -D -m 0755 "$repo_root/ops/gw2a/gw2a-attach" /usr/local/libexec/gw2a-attach
install -D -m 0755 "$repo_root/ops/gw2a/gw2a-pane-shell" /usr/local/libexec/gw2a-pane-shell
systemctl --global disable gw2agent-herdr.service >/dev/null 2>&1 || true
rm -f /etc/systemd/user/gw2agent-herdr.service

cmp -s "$repo_root/ops/gw2a/gw2a" /usr/local/bin/gw2a
cmp -s "$repo_root/ops/gw2a/gw2a-attach" /usr/local/libexec/gw2a-attach
cmp -s "$repo_root/ops/gw2a/gw2a-pane-shell" /usr/local/libexec/gw2a-pane-shell

echo "Installed gw2a lifecycle wrappers and disabled the legacy Herdr user service."
