#!/usr/bin/env bash
set -Eeuo pipefail

ACTION_ID="${1:?usage: approve-action.sh ACTION_ID APPROVER}"
APPROVER="${2:?usage: approve-action.sh ACTION_ID APPROVER}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source .env
set +a

curl -fsS \
  -H "Authorization: Bearer ${CYBERGUARD_EXECUTOR_TOKEN}" \
  -H "X-Approval-Secret: ${CYBERGUARD_APPROVAL_SECRET}" \
  -H 'Content-Type: application/json' \
  -d "{\"action_id\":\"${ACTION_ID}\",\"approver\":\"${APPROVER}\",\"expires_minutes\":15}" \
  http://127.0.0.1:18105/actions/approve
echo

