#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! docker network inspect agentteams-net >/dev/null 2>&1; then
  echo "agentteams-net does not exist. Install AgentTeams first." >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example and replace every placeholder." >&2
  exit 1
fi
python3 deploy/validate_config.py --cyberguard-env .env

docker compose config --quiet
docker compose build --pull
docker compose up -d --remove-orphans
bash deploy/verify.sh
bash tests/e2e_demo.sh
