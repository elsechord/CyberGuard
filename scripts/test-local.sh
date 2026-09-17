#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m compileall -q services cyberguard_investigation benchmark deploy tests scripts
for test_file in tests/test_*.py; do
    python3 "$test_file"
done
python3 benchmark/evaluate.py benchmark/fixtures/complete-report.json >/dev/null

python3 - <<'PY'
import json
from pathlib import Path
for directory in (Path("contracts"), Path("scenarios")):
    for path in directory.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
PY

find deploy scripts tests -type f -name '*.sh' -print0 | sort -z | xargs -0 -n1 bash -n
echo "Local validation passed."
