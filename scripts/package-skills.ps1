$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "dist\skills"
if (Test-Path -LiteralPath $Out) {
    Remove-Item -LiteralPath $Out -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Out | Out-Null

Get-ChildItem -LiteralPath (Join-Path $Root "skills") -Directory | ForEach-Object {
    $SkillFile = Join-Path $_.FullName "SKILL.md"
    if (-not (Test-Path -LiteralPath $SkillFile)) {
        throw "Missing SKILL.md in $($_.FullName)"
    }
    $Archive = Join-Path $Out "$($_.Name).zip"
    Compress-Archive -Path (Join-Path $_.FullName "*") -DestinationPath $Archive -CompressionLevel Optimal
}

$Lines = Get-ChildItem -LiteralPath $Out -Filter *.zip | Sort-Object Name | ForEach-Object {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLower()
    "$Hash  $($_.Name)"
}
Set-Content -LiteralPath (Join-Path $Out "SHA256SUMS") -Value $Lines -Encoding ascii
Write-Host "Packaged Skills in $Out"

