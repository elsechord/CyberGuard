#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source .env
set +a

AUTH="Authorization: Bearer ${CYBERGUARD_EXECUTOR_TOKEN}"
PROPOSAL="$(curl -fsS -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"incident_id":"VERIFY-001","action":"isolate_endpoint","target":"FIN-LT-023","reason":"Verified malicious process chain and suspicious outbound transfer.","idempotency_key":"VERIFY-001-isolate-FIN-LT-023"}' \
  http://127.0.0.1:18105/actions/propose)"
ACTION_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["action_id"])' <<<"$PROPOSAL")"

STATUS="$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H "$AUTH" \
  "http://127.0.0.1:18105/actions/${ACTION_ID}/execute")"
[[ "$STATUS" == "409" ]] || { echo "Expected unapproved execution to fail with 409, got $STATUS" >&2; exit 1; }

curl -fsS -H "$AUTH" -H "X-Approval-Secret: ${CYBERGUARD_APPROVAL_SECRET}" \
  -H 'Content-Type: application/json' \
  -d "{\"action_id\":\"${ACTION_ID}\",\"approver\":\"smoke-test\",\"expires_minutes\":5}" \
  http://127.0.0.1:18105/actions/approve >/dev/null
curl -fsS -X POST -H "$AUTH" "http://127.0.0.1:18105/actions/${ACTION_ID}/execute" >/dev/null
curl -fsS -X POST -H "$AUTH" "http://127.0.0.1:18105/actions/${ACTION_ID}/rollback" >/dev/null

echo "Approval, execution, and rollback smoke test passed."
