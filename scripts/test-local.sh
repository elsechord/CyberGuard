#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m compileall -q services benchmark deploy tests
python3 tests/test_security_gateway.py
python3 tests/test_normalization.py
python3 tests/test_response_executor.py
python3 tests/test_benchmark.py
python3 tests/test_benchmark_runner.py
python3 tests/test_benchmark_audit.py
python3 tests/test_agentteams_bootstrap.py
python3 tests/test_deploy_config.py
python3 tests/test_init_secrets.py
python3 tests/test_llm_preflight.py
python3 tests/test_deploy_contracts.py
python3 tests/test_source_sbom.py
python3 tests/test_ci_contracts.py
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
