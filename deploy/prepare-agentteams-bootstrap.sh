#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="/srv/cyberguard/host-share/cyberguard-bootstrap"
[[ "$ROOT" == "/srv/cyberguard" ]] || { echo "Run from /srv/cyberguard." >&2; exit 1; }

bash scripts/package-skills.sh
install -d -m 0750 "$DEST/skills"
install -m 0640 agentteams/create-team-message.md "$DEST/create-team-message.md"
install -m 0640 agentteams/bootstrap-manager-request.md "$DEST/bootstrap-manager-request.md"
for package in dist/skills/*.zip dist/skills/SHA256SUMS; do
  install -m 0640 "$package" "$DEST/skills/$(basename "$package")"
done
(cd "$DEST/skills" && sha256sum --check --strict SHA256SUMS)
(cd "$DEST" && find . -type f ! -name BOOTSTRAP-SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum >BOOTSTRAP-SHA256SUMS)
(cd "$DEST" && sha256sum --check --strict BOOTSTRAP-SHA256SUMS)

find "$DEST" -type f -exec chmod 0640 {} +
echo "Prepared AgentTeams bootstrap assets at $DEST (Manager path: /host-share/cyberguard-bootstrap)."
