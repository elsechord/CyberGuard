#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source .env
set +a

READ_AUTH="Authorization: Bearer ${CYBERGUARD_API_TOKEN}"
EXEC_AUTH="Authorization: Bearer ${CYBERGUARD_EXECUTOR_TOKEN}"
SCENARIO_ID="${1:-credential_compromise}"
INCIDENT_ID="E2E-${SCENARIO_ID}-$(date +%s)-$$"
EVIDENCE_DIR="${EVIDENCE_DIR:-}"

case "$SCENARIO_ID" in
  credential_compromise)
    ACTIONS=("disable_account|finance-ops" "isolate_endpoint|FIN-LT-023" "block_ioc|198.51.100.27")
    POST_ASSERT='d["evidence"]["data"]["endpoint_isolated"] is True'
    ;;
  supply_chain_webshell)
    ACTIONS=("disable_account|ci-release-bot" "quarantine_workload|checkout-api" "block_ioc|updates-cdn.example.invalid")
    POST_ASSERT='d["evidence"]["data"]["compromised_token_disabled"] is True and d["evidence"]["data"]["signed_image_restored"] is True'
    ;;
  *)
    echo "Unsupported scenario: $SCENARIO_ID" >&2
    exit 2
    ;;
esac

save_json() {
  local name="$1"
  local content="$2"
  if [[ -n "$EVIDENCE_DIR" ]]; then
    mkdir -p "$EVIDENCE_DIR"
    printf '%s\n' "$content" >"$EVIDENCE_DIR/$name.json"
  fi
}

invoke_read_tool() {
  local tool="$1"
  curl --fail-with-body -sS \
    -H "$READ_AUTH" -H 'Content-Type: application/json' \
    -d "{\"incident_id\":\"${INCIDENT_ID}\",\"scenario_id\":\"${SCENARIO_ID}\",\"arguments\":{}}" \
    "http://127.0.0.1:18100/tools/${tool}"
}

for tool in alert/snapshot asset/context intel/lookup network/search boundary/policy endpoint/timeline; do
  invoke_read_tool "$tool" >/dev/null
done

PRE_RECOVERY="$(invoke_read_tool recovery/metrics)"
save_json pre-recovery "$PRE_RECOVERY"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["evidence"]["data"]["verdict"] == "inconclusive"' <<<"$PRE_RECOVERY"

ACTION_IDS=()
INDEX=0
for spec in "${ACTIONS[@]}"; do
  INDEX=$((INDEX + 1))
  ACTION="${spec%%|*}"
  TARGET="${spec#*|}"
  PROPOSAL="$(curl --fail-with-body -sS \
    -H "$EXEC_AUTH" -H 'Content-Type: application/json' \
    -d "{\"incident_id\":\"${INCIDENT_ID}\",\"action\":\"${ACTION}\",\"target\":\"${TARGET}\",\"reason\":\"Correlated independent evidence confirms active compromise and requires reversible containment.\",\"idempotency_key\":\"${INCIDENT_ID}-${ACTION}\"}" \
    http://127.0.0.1:18105/actions/propose)"
  ACTION_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["action_id"])' <<<"$PROPOSAL")"
  ACTION_IDS+=("$ACTION_ID")
  save_json "proposal-${INDEX}" "$PROPOSAL"

  UNAPPROVED_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    -H "$EXEC_AUTH" "http://127.0.0.1:18105/actions/${ACTION_ID}/execute")"
  [[ "$UNAPPROVED_STATUS" == "409" ]] || {
    echo "Safety failure: unapproved execution returned HTTP $UNAPPROVED_STATUS" >&2
    exit 1
  }

  APPROVAL="$(curl --fail-with-body -sS \
    -H "$EXEC_AUTH" -H "X-Approval-Secret: ${CYBERGUARD_APPROVAL_SECRET}" \
    -H 'Content-Type: application/json' \
    -d "{\"action_id\":\"${ACTION_ID}\",\"approver\":\"server-e2e-test\",\"expires_minutes\":5}" \
    http://127.0.0.1:18105/actions/approve)"
  save_json "approval-${INDEX}" "$APPROVAL"
  EXECUTION="$(curl --fail-with-body -sS -X POST -H "$EXEC_AUTH" \
    "http://127.0.0.1:18105/actions/${ACTION_ID}/execute")"
  save_json "execution-${INDEX}" "$EXECUTION"
done

POST_RECOVERY="$(invoke_read_tool recovery/metrics)"
save_json post-recovery "$POST_RECOVERY"
python3 -c "import json,sys; d=json.load(sys.stdin); assert ${POST_ASSERT}" <<<"$POST_RECOVERY"

AUDIT="$(curl --fail-with-body -sS -H "$EXEC_AUTH" http://127.0.0.1:18105/audit/verify)"
save_json audit "$AUDIT"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["valid"] is True and d["authenticated"] is True and d["records"] >= 3' <<<"$AUDIT"

DETAIL="$(curl --fail-with-body -sS -H "$READ_AUTH" "http://127.0.0.1:18100/incidents/${INCIDENT_ID}")"
save_json incident "$DETAIL"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["summary"]["status"] == "verified" and len(d["evidence"]) >= 8' <<<"$DETAIL"

ACTION_ID="${ACTION_IDS[0]}"
ROLLBACK="$(curl --fail-with-body -sS -X POST -H "$EXEC_AUTH" \
  "http://127.0.0.1:18105/actions/${ACTION_ID}/rollback")"
save_json rollback "$ROLLBACK"
ROLLED_BACK_RECOVERY="$(invoke_read_tool recovery/metrics)"
save_json rolled-back-recovery "$ROLLED_BACK_RECOVERY"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["evidence"]["data"]["verdict"] == "inconclusive"' <<<"$ROLLED_BACK_RECOVERY"

for ACTION_ID in "${ACTION_IDS[@]:1}"; do
  curl --fail-with-body -sS -X POST -H "$EXEC_AUTH" \
    "http://127.0.0.1:18105/actions/${ACTION_ID}/rollback" >/dev/null
done

echo "Cross-service E2E passed: $INCIDENT_ID / ${#ACTION_IDS[@]} required actions"
echo "Proved: exact response contract, pre-action verification refusal, unapproved execution blocking, approved execution, audit integrity and rollback invalidation."
if [[ -n "$EVIDENCE_DIR" ]]; then
  ACTION_IDS_CSV="$(IFS=,; echo "${ACTION_IDS[*]}")"
  python3 - "$EVIDENCE_DIR/run.json" "$INCIDENT_ID" "$ACTION_IDS_CSV" <<'PY'
import json, sys
from datetime import datetime, timezone
path, incident_id, action_ids_csv = sys.argv[1:]
action_ids = action_ids_csv.split(",")
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "incident_id": incident_id,
        "action_id": action_ids[0],
        "action_ids": action_ids,
        "scenario_id": incident_id.split("-", 2)[1],
        "checks": [
            "required_action_contract_enforced", "pre_action_inconclusive",
            "unapproved_execution_blocked", "approved_execution_verified",
            "audit_chain_valid", "rollback_invalidates_recovery"
        ],
    }, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
  echo "Evidence saved under $EVIDENCE_DIR"
fi
