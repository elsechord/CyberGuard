#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_ROOT="${CYBERGUARD_EVIDENCE_ROOT:-$ROOT/artifacts/acceptance}"
RUN_DIR="$EVIDENCE_ROOT/$STAMP"
mkdir -p "$RUN_DIR/e2e"

exec > >(tee "$RUN_DIR/acceptance.log") 2>&1

collect_failure_evidence() {
  local status="$?"
  trap - ERR
  set +e
  printf '{"status":%s,"line":%s,"captured_at":"%s"}\n' \
    "$status" "${BASH_LINENO[0]:-0}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >"$RUN_DIR/failure.json"
  docker compose ps --all --format json >"$RUN_DIR/failure-compose-ps.json" 2>&1
  for failed_service in security-tool-gateway response-executor; do
    docker compose logs --no-color --tail 500 "$failed_service" 2>&1 \
      | sed -E 's/(Bearer|token|secret|password)([=: ]+)[^ ]+/\1\2[REDACTED]/Ig' \
      >"$RUN_DIR/failure-${failed_service}.log"
  done
  echo "Acceptance failed with status $status. Diagnostics: $RUN_DIR" >&2
  exit "$status"
}
trap collect_failure_evidence ERR

echo "CyberGuard server acceptance: $STAMP"
echo "Evidence directory: $RUN_DIR"

python3 deploy/validate_config.py --cyberguard-env .env \
  --agentteams-env "${AGENTTEAMS_ENV_FILE:-$ROOT/agentteams.env}" \
  --expected-root /srv/cyberguard --json >"$RUN_DIR/config-validation.json"

docker version >"$RUN_DIR/docker-version.txt"
docker compose version >"$RUN_DIR/compose-version.txt"
docker compose config --services >"$RUN_DIR/compose-services.txt"
docker compose config --images >"$RUN_DIR/compose-images.txt"

if [[ "${CYBERGUARD_SKIP_BUILD:-0}" != "1" ]]; then
  docker compose build --pull
fi
docker compose up -d --remove-orphans
bash deploy/verify.sh
EVIDENCE_DIR="$RUN_DIR/e2e" bash tests/e2e_demo.sh

docker compose ps --format json >"$RUN_DIR/compose-ps.json"
while IFS= read -r image; do
  [[ -n "$image" ]] || continue
  docker image inspect "$image" \
    --format '{"reference":{{json .RepoTags}},"id":{{json .Id}},"repo_digests":{{json .RepoDigests}}}'
done < <(docker compose config --images) >"$RUN_DIR/image-identities.jsonl"

for service in security-tool-gateway response-executor; do
  docker compose logs --no-color --tail 500 "$service" \
    | sed -E 's/(Bearer|token|secret|password)([=: ]+)[^ ]+/\1\2[REDACTED]/Ig' \
    >"$RUN_DIR/${service}.log"
done

curl -fsS http://127.0.0.1:18100/openapi.json >"$RUN_DIR/gateway-openapi.json"
curl -fsS http://127.0.0.1:18105/openapi.json >"$RUN_DIR/executor-openapi.json"
set -a
# shellcheck disable=SC1091
source .env
set +a
curl --fail-with-body -sS -H "Authorization: Bearer ${CYBERGUARD_EXECUTOR_TOKEN}" \
  http://127.0.0.1:18105/audit/checkpoint >"$RUN_DIR/audit-checkpoint.json"

if docker ps --format '{{.Names}}' | grep -qx 'agentteams-controller'; then
  docker exec agentteams-controller agt version >"$RUN_DIR/agentteams-version.txt" 2>&1 || true
  docker exec agentteams-controller agt get managers >"$RUN_DIR/agentteams-managers.txt" 2>&1 || true
fi

python3 - "$RUN_DIR/acceptance-manifest.json" "$STAMP" <<'PY'
import json, platform, sys
from pathlib import Path

output, stamp = Path(sys.argv[1]), sys.argv[2]
root = Path.cwd()
manifest = {
    "schema_version": 1,
    "acceptance_id": stamp,
    "cyberguard_version": (root / "VERSION").read_text(encoding="utf-8").strip(),
    "agentteams_version": "v1.2.2",
    "host": {"system": platform.system(), "machine": platform.machine()},
    "scenario": "credential_compromise",
    "evidence_policy": {
        "secrets_included": False,
        "runtime_logs_redacted": True,
        "acceptance_log_checksummed": False,
        "acceptance_log_reason": "stream remains open until script exit",
    },
    "required_proofs": [
        "configuration_valid", "services_healthy", "unapproved_execution_blocked",
        "approved_execution_verified", "audit_chain_valid", "rollback_observed",
    ],
}
output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

(cd "$RUN_DIR" && find . -type f ! -name 'SHA256SUMS' ! -name 'acceptance.log' -print0 \
  | sort -z | xargs -0 sha256sum >SHA256SUMS)

ARCHIVE="$EVIDENCE_ROOT/CyberGuard-acceptance-$STAMP.tar.gz"
tar -C "$EVIDENCE_ROOT" -czf "$ARCHIVE" "$STAMP"
sha256sum "$ARCHIVE" >"$ARCHIVE.sha256"

trap - ERR

echo "Acceptance passed. Evidence archive: $ARCHIVE"
echo "SHA256 file: $ARCHIVE.sha256"
