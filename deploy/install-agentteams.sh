#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${1:-/srv/cyberguard/agentteams.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy deploy/agentteams/agentteams.env.example and fill it first." >&2
  exit 1
fi

python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/validate_config.py" \
  --agentteams-env "$ENV_FILE" --expected-root /srv/cyberguard

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ "${AGENTTEAMS_LLM_API_KEY:-replace-me}" == "replace-me" ]]; then
  echo "Refusing to install with a placeholder LLM API key." >&2
  exit 1
fi

EXPECTED_VERSION="v1.2.2"
EXPECTED_COMMIT="849182af8e017168a5a200a87b1062142caf462d"
EXPECTED_SHA256="8ef28c5bf239a0af2d6b57b946ecee977bf39e6c874cd786b85c7bd094668f9d"
if [[ "${AGENTTEAMS_VERSION:-}" != "$EXPECTED_VERSION" ]]; then
  echo "This release is validated only with AgentTeams $EXPECTED_VERSION; got ${AGENTTEAMS_VERSION:-unset}." >&2
  exit 1
fi
if [[ "${AGENTTEAMS_INSTALL_COMMIT:-}" != "$EXPECTED_COMMIT" ]]; then
  echo "AgentTeams installer commit does not match the validated v1.2.2 commit." >&2
  exit 1
fi
if [[ "${AGENTTEAMS_INSTALL_SHA256:-}" != "$EXPECTED_SHA256" ]]; then
  echo "AgentTeams installer checksum does not match the validated release." >&2
  exit 1
fi

install -d -m 0750 /srv/cyberguard/agentteams-manager /srv/cyberguard/host-share
INSTALLER="$(mktemp /tmp/agentteams-install.XXXXXX.sh)"
trap 'rm -f "$INSTALLER"' EXIT
curl --proto '=https' --tlsv1.2 -fsSL \
  "https://raw.githubusercontent.com/agentscope-ai/AgentTeams/${AGENTTEAMS_INSTALL_COMMIT}/install/agentteams-install.sh" \
  -o "$INSTALLER"
printf '%s  %s\n' "$AGENTTEAMS_INSTALL_SHA256" "$INSTALLER" | sha256sum --check --strict
bash "$INSTALLER"

# AgentTeams v1.2.2 may generate an OpenAI upstream or an unresolved raw-domain
# destination for OpenAI-compatible providers. Normalize the embedded Higress
# objects to one DeepSeek-compatible provider and one resolvable DNS service.
python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/configure-agentteams-deepseek.py" \
  --env "$ENV_FILE"

docker ps --filter name=agentteams
docker exec agentteams-controller agt get managers
