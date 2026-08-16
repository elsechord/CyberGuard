$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m compileall -q services benchmark tests
python tests/test_security_gateway.py
python tests/test_normalization.py
python tests/test_response_executor.py
python tests/test_benchmark.py
python tests/test_benchmark_runner.py
python tests/test_benchmark_audit.py
python tests/test_agentteams_bootstrap.py
python tests/test_deploy_config.py
python tests/test_init_secrets.py
python tests/test_llm_preflight.py
python tests/test_deploy_contracts.py
python tests/test_source_sbom.py
python tests/test_ci_contracts.py
python benchmark/evaluate.py benchmark/fixtures/complete-report.json | Out-Null

Get-ChildItem contracts,scenarios -Filter *.json -Recurse | ForEach-Object {
    Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json | Out-Null
}

Write-Host "Local validation passed."
