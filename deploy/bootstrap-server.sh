#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$ROOT" != "/srv/cyberguard" ]]; then
  echo "For the reproducible competition profile, extract CyberGuard to /srv/cyberguard (current: $ROOT)." >&2
  exit 1
fi
cd "$ROOT"

bash deploy/preflight.sh host
if [[ ! -f .env ]]; then
  python3 deploy/init_secrets.py
fi
if [[ ! -f agentteams.env ]]; then
  echo "Missing $ROOT/agentteams.env. Copy deploy/agentteams/agentteams.env.example and fill the LLM/model/admin values." >&2
  exit 1
fi
python3 deploy/validate_config.py --cyberguard-env .env --agentteams-env agentteams.env \
  --expected-root /srv/cyberguard

# CyberGuard may create its required shared network before AgentTeams is
# installed.  A network alone is not evidence of a usable AgentTeams runtime.
if ! docker ps --format '{{.Names}}' | grep -qx 'agentteams-controller'; then
  bash deploy/install-agentteams.sh "$ROOT/agentteams.env"
fi
bash deploy/preflight.sh cyberguard
bash deploy/server-acceptance.sh
bash deploy/prepare-agentteams-bootstrap.sh

echo
echo "CyberGuard bootstrap and acceptance passed."
echo "Next: register the two credential-brokered tools, then run sudo bash deploy/bootstrap-agentteams.sh."
