#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ "$ROOT" == "/srv/cyberguard" ]] || { echo "Run from /srv/cyberguard." >&2; exit 1; }

bash deploy/prepare-agentteams-bootstrap.sh
set -a
# shellcheck disable=SC1091
source agentteams.env
set +a
export MATRIX_BASE_URL="${MATRIX_BASE_URL:-http://127.0.0.1:18080}"
export MATRIX_USERNAME="${MATRIX_USERNAME:-${AGENTTEAMS_ADMIN_USER}}"
export MATRIX_PASSWORD="${MATRIX_PASSWORD:-${AGENTTEAMS_ADMIN_PASSWORD}}"
python3 deploy/bootstrap-agentteams.py \
  --bundle-manifest /srv/cyberguard/host-share/cyberguard-bootstrap/BOOTSTRAP-SHA256SUMS \
  --evidence artifacts/agentteams-bootstrap/request-response.json
python3 deploy/validate-agentteams-state.py \
  --manager-result /srv/cyberguard/host-share/cyberguard-bootstrap/manager-result.json \
  --output artifacts/agentteams-bootstrap/state.json

echo "AgentTeams CyberGuard Team bootstrap passed."
