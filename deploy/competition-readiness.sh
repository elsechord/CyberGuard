#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${CYBERGUARD_READINESS_DIR:-$ROOT/artifacts/readiness/$STAMP}"
MANAGER_RESULT="/srv/cyberguard/host-share/cyberguard-bootstrap/manager-result.json"
mkdir -p "$OUT"

python3 deploy/validate_config.py --cyberguard-env .env --agentteams-env agentteams.env \
  --expected-root /srv/cyberguard --json >"$OUT/config.json"
bash deploy/verify.sh >"$OUT/services.txt"
docker exec agentteams-controller agt get managers -o json >"$OUT/managers.json"
docker exec agentteams-controller agt get workers -o json >"$OUT/workers.json"
docker exec agentteams-controller agt get teams -o json >"$OUT/teams.json"
python3 deploy/validate-agentteams-state.py --manager-result "$MANAGER_RESULT" \
  --workers-json "$OUT/workers.json" --teams-json "$OUT/teams.json" \
  --output "$OUT/agentteams-state.json"

set -a
# shellcheck disable=SC1091
source .env
set +a
curl --fail-with-body -sS -H "Authorization: Bearer ${CYBERGUARD_EXECUTOR_TOKEN}" \
  http://127.0.0.1:18105/audit/checkpoint >"$OUT/audit-checkpoint.json"

python3 - "$OUT/readiness.json" "$STAMP" <<'PY'
import json, sys
from pathlib import Path

output, stamp = Path(sys.argv[1]), sys.argv[2]
root = output.parent
state = json.loads((root / "agentteams-state.json").read_text(encoding="utf-8"))
config = json.loads((root / "config.json").read_text(encoding="utf-8"))
result = {
    "schema_version": 1,
    "readiness_id": stamp,
    "ready": bool(config.get("valid")) and bool(state.get("valid")),
    "gates": {
        "configuration": bool(config.get("valid")),
        "cyberguard_services": True,
        "agentteams_state": bool(state.get("valid")),
        "audit_checkpoint": True,
    },
    "next_required_evidence": ["target-server judge demo", "40-run real-model benchmark"],
}
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if not result["ready"]:
    raise SystemExit(1)
PY

(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS)
echo "Competition readiness passed: $OUT/readiness.json"
