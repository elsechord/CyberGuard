#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source .env
set +a

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18100/health >/dev/null \
    && curl -fsS http://127.0.0.1:18105/health >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS http://127.0.0.1:18100/health
curl -fsS http://127.0.0.1:18105/health
curl -fsS http://127.0.0.1:18100/console >/dev/null

HEADER="Authorization: Bearer ${CYBERGUARD_API_TOKEN}"
TOOLS="$(curl -fsS -H "$HEADER" http://127.0.0.1:18100/tools)"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert "boundary.policy" in d["tools"]' <<<"$TOOLS"
printf '%s\n' "$TOOLS"
curl -fsS -H "$HEADER" -H 'Content-Type: application/json' \
  -d '{"incident_id":"VERIFY-001","scenario_id":"credential_compromise","arguments":{}}' \
  http://127.0.0.1:18100/tools/alert/snapshot
curl -fsS -H "$HEADER" http://127.0.0.1:18100/incidents >/dev/null

echo
echo "CyberGuard read-only gateway verification passed."
