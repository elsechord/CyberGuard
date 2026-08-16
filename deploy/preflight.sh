#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE="${1:-host}"
if [[ "$PHASE" != "host" && "$PHASE" != "cyberguard" ]]; then
  echo "Usage: $0 [host|cyberguard]" >&2
  exit 2
fi
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "CyberGuard server deployment requires Linux." >&2
  exit 1
fi
architecture="$(uname -m)"
if [[ "$architecture" != "x86_64" && "$architecture" != "amd64" ]]; then
  echo "CyberGuard's hash-locked Python wheel set currently requires x86_64/amd64; found $architecture." >&2
  exit 1
fi

missing=()
for command_name in bash curl docker python3 sha256sum tar; do
  command -v "$command_name" >/dev/null 2>&1 || missing+=("$command_name")
done
if ((${#missing[@]})); then
  echo "Missing required commands: ${missing[*]}" >&2
  exit 1
fi
docker version --format '{{.Server.Version}}' >/dev/null
docker compose version >/dev/null

cpu_count="$(getconf _NPROCESSORS_ONLN)"
memory_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
free_kib="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
if ((cpu_count < 4)); then
  echo "At least 4 CPU cores are required; found $cpu_count." >&2
  exit 1
fi
if ((memory_kib < 8 * 1024 * 1024)); then
  echo "At least 8 GiB RAM is required; found $((memory_kib / 1024 / 1024)) GiB." >&2
  exit 1
fi
if ((free_kib < 20 * 1024 * 1024)); then
  echo "At least 20 GiB free disk is required; found $((free_kib / 1024 / 1024)) GiB." >&2
  exit 1
fi
((cpu_count < 8)) && echo "Warning: 8 CPU cores are recommended; found $cpu_count." >&2
((memory_kib < 16 * 1024 * 1024)) && echo "Warning: 16 GiB RAM is recommended." >&2
((free_kib < 100 * 1024 * 1024)) && echo "Warning: 100 GiB free disk is recommended." >&2

if [[ "$PHASE" == "cyberguard" ]]; then
  [[ -f "$ROOT/.env" ]] || { echo "Missing $ROOT/.env" >&2; exit 1; }
  [[ -f "$ROOT/agentteams.env" ]] || { echo "Missing $ROOT/agentteams.env" >&2; exit 1; }
  python3 "$ROOT/deploy/validate_config.py" --cyberguard-env "$ROOT/.env" \
    --agentteams-env "$ROOT/agentteams.env" --expected-root /srv/cyberguard
  docker network inspect agentteams-net >/dev/null
fi

echo "Preflight passed: phase=$PHASE arch=$architecture cpu=$cpu_count memory_gib=$((memory_kib / 1024 / 1024)) free_disk_gib=$((free_kib / 1024 / 1024))"
