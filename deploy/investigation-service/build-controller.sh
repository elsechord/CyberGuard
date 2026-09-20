#!/usr/bin/env bash
# Build only the pinned upstream source; no model credentials or running services.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/cyberguard"
SOURCE="$CACHE/AgentTeams-v1.2.3"
COMMIT=223ddc2b8073e4c8b93bcbb15e1d717f196c04d9
mkdir -p "$CACHE"
if [[ ! -d "$SOURCE/.git" ]]; then
  git clone --depth 1 --branch v1.2.3 https://github.com/agentscope-ai/AgentTeams.git "$SOURCE"
fi
[[ "$(git -C "$SOURCE" rev-parse HEAD)" == "$COMMIT" ]] || { echo 'Unexpected upstream revision' >&2; exit 1; }
BUILD_DIR="$(mktemp -d "$CACHE/native-controller-build.XXXXXX")"
git -C "$SOURCE" archive HEAD agentteams-controller | tar -x -C "$BUILD_DIR"
cd "$BUILD_DIR/agentteams-controller"
patch --batch --forward -p1 < "$SCRIPT_DIR/../agentteams-local/controller-localhost.patch"
docker build -f "$SCRIPT_DIR/controller-native.Dockerfile" -t cyberguard/agentteams-embedded:v1.2.3-localhost .
docker image inspect cyberguard/agentteams-embedded:v1.2.3-localhost --format '{{.Id}}'
