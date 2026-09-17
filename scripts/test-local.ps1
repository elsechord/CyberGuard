$ErrorActionPreference = "Stop"
function Invoke-Python {
    & python @args
    if ($LASTEXITCODE -ne 0) {
        throw "Python validation failed (exit $LASTEXITCODE): $args"
    }
}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Invoke-Python -m compileall -q services cyberguard_investigation benchmark deploy tests scripts
Get-ChildItem tests -Filter 'test_*.py' | Sort-Object Name | ForEach-Object {
    Invoke-Python $_.FullName
}
Invoke-Python benchmark/evaluate.py benchmark/fixtures/complete-report.json | Out-Null

Get-ChildItem contracts,scenarios -Filter *.json -Recurse | ForEach-Object {
    Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json | Out-Null
}

Write-Host "Local validation passed."
