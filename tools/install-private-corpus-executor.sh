#!/usr/bin/env bash
# EXPERIMENTAL / NOT OPERATIONAL — DO NOT USE WITH REAL PRIVATE CORPUS.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run with sudo as root" >&2
  exit 1
fi

group_name=gw2analytics-private-readers
if ! getent group "$group_name" >/dev/null; then
  groupadd --system "$group_name"
fi
if id -nG gw2agent | tr ' ' '\n' | grep -Fx "$group_name" >/dev/null; then
  echo "gw2agent must not be a permanent member of $group_name" >&2
  exit 1
fi

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
source_dir="$root/ops/private-corpus"
uv_source=/home/gw2agent/.local/share/mise/installs/uv/0.12.5/uv-x86_64-unknown-linux-musl/uv
uv_target=/usr/local/lib/gw2analytics-private/uv/0.12.5/uv
uv_sha256=6470fe2ab573e01f703fd76cada1952f7755dd0fc7f2f6ac0bee1d5f8ba4413e
uv_version='uv 0.12.5 (x86_64-unknown-linux-musl)'
if [[ ! -x $uv_source ]] || [[ $(sha256sum "$uv_source" | awk '{print $1}') != "$uv_sha256" ]] \
  || [[ $("$uv_source" --version) != "$uv_version" ]] \
  || ! file "$uv_source" | grep -Fq 'static-pie linked'; then
  echo "verified static uv 0.12.5 source is required" >&2
  exit 1
fi
install -D -o root -g root -m 0511 "$uv_source" "$uv_target"
if [[ $(stat -c '%U:%G:%a' "$uv_target") != root:root:511 ]] \
  || [[ $(sha256sum "$uv_target" | awk '{print $1}') != "$uv_sha256" ]] \
  || [[ $("$uv_target" --version) != "$uv_version" ]]; then
  echo "installed uv integrity verification failed" >&2
  exit 1
fi
install -D -m 0750 "$source_dir/executor.py" /usr/local/sbin/gw2analytics-private-corpus-executor
chown root:gw2analytics-private-readers /usr/local/sbin/gw2analytics-private-corpus-executor
install -D -m 0640 "$source_dir/contract.json" /usr/local/sbin/gw2analytics-private-corpus-contract.json
chown root:gw2analytics-private-readers /usr/local/sbin/gw2analytics-private-corpus-contract.json
install -D -m 0644 "$source_dir/gw2analytics-private-corpus@.service" /etc/systemd/system/gw2analytics-private-corpus@.service
install -D -m 0440 "$source_dir/gw2analytics-private-corpus.sudoers" /etc/sudoers.d/gw2analytics-private-corpus
visudo -cf /etc/sudoers.d/gw2analytics-private-corpus

# Corpus synthétique de validation seulement. gw2agent n'est jamais ajouté au
# groupe : seule l'unité reçoit ce groupe supplémentaire pendant son exécution.
synthetic_root=/var/lib/gw2analytics/private-corpus-synthetic
install -d -o root -g "$group_name" -m 0750 "$synthetic_root/fixture-a"
install -o root -g "$group_name" -m 0640 /dev/null "$synthetic_root/fixture-a/probe.txt"
printf '%s\n' 'synthetic private-corpus probe' > "$synthetic_root/fixture-a/probe.txt"
chown root:"$group_name" "$synthetic_root/fixture-a/probe.txt"
install -d -o root -g "$group_name" -m 0750 /etc/gw2analytics
install -o root -g "$group_name" -m 0640 "$source_dir/private-test-registry.json" /etc/gw2analytics/private-corpus-registry.json
systemctl daemon-reload
