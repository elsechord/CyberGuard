#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/agentteams.env}"

python3 "$ROOT/deploy/llm_preflight.py" --env "$ENV_FILE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

worker="$(docker ps --format '{{.Names}}' | grep '^agentteams-worker-' | head -1 || true)"
if [[ -z "$worker" ]]; then
  echo "worker_gateway_preflight=SKIP reason=no_running_worker"
  exit 2
fi

docker exec -e CYBERGUARD_PROBE_MODEL="$AGENTTEAMS_DEFAULT_MODEL" "$worker" sh -lc '
  set -e
  response=/tmp/cyberguard-llm-preflight.json
  trap "rm -f \"$response\"" EXIT
  code=$(curl -sS --max-time 90 -o "$response" -w "%{http_code}" \
    -H "Authorization: Bearer ${AGENTTEAMS_WORKER_GATEWAY_KEY}" \
    -H "Content-Type: application/json" \
    -H "Host: aigw-local.agentteams.io" \
    --data "{\"model\":\"${CYBERGUARD_PROBE_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply only: ok\"}],\"max_tokens\":8,\"stream\":false}" \
    http://agentteams-controller:8080/v1/chat/completions)
  if [ "$code" -ge 200 ] && [ "$code" -lt 300 ] && grep -q "\"choices\"" "$response"; then
    echo "worker_gateway_preflight=PASS http=$code"
    exit 0
  fi
  echo "worker_gateway_preflight=FAIL http=$code"
  sed -E "s/(Bearer|api[_-]?key|token|secret|password)([=: ]+)[^ ]+/\1\2[REDACTED]/Ig" "$response" | head -c 500
  echo
  exit 1
'
