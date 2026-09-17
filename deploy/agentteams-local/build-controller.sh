#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="/root/.cache/cyberguard/AgentTeams-849182a"
COMMIT="849182af8e017168a5a200a87b1062142caf462d"
if [[ ! -d "$SOURCE/.git" ]]; then
  mkdir -p /root/.cache/cyberguard
  git clone --depth 1 --branch v1.2.2 https://github.com/agentscope-ai/AgentTeams.git "$SOURCE"
fi
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$COMMIT" ]] || { echo 'Unexpected upstream revision' >&2; exit 1; }
git -C "$SOURCE" archive --format=tar HEAD agentteams-controller > /root/.cache/cyberguard/agentteams-controller-849182a.tar
sha256sum /root/.cache/cyberguard/agentteams-controller-849182a.tar
# Build exclusively from committed archive, never from a possibly dirty cache.
BUILD_DIR="$(mktemp -d /root/.cache/cyberguard/controller-build.XXXXXX)"
tar -xf /root/.cache/cyberguard/agentteams-controller-849182a.tar -C "$BUILD_DIR"
cd "$BUILD_DIR/agentteams-controller"
patch --batch --forward -p1 < "$SCRIPT_DIR/controller-localhost.patch"
cp "$SCRIPT_DIR/console_localhost_test.go" internal/backend/console_localhost_test.go
docker build -f "$SCRIPT_DIR/controller.Dockerfile" -t cyberguard/agentteams-embedded:v1.2.2-localhost .
docker image inspect cyberguard/agentteams-embedded:v1.2.2-localhost --format '{{.Id}}'
