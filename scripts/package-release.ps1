$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

powershell -ExecutionPolicy Bypass -File scripts/test-local.ps1
powershell -ExecutionPolicy Bypass -File scripts/package-skills.ps1

$Version = (Get-Content -LiteralPath VERSION -Raw).Trim()
$OutDir = Join-Path $Root "dist"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Archive = Join-Path $OutDir "CyberGuard-server-v$Version.zip"
$SourceSbom = Join-Path $OutDir "CyberGuard-source-v$Version.spdx.json"
$SourceSbomHash = "$SourceSbom.sha256"
if (Test-Path -LiteralPath $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}
python scripts/generate-source-sbom.py --output $SourceSbom
$SourceSbomDigest = Get-FileHash -Algorithm SHA256 -LiteralPath $SourceSbom
Set-Content -LiteralPath $SourceSbomHash -Value "$($SourceSbomDigest.Hash.ToLower())  $(Split-Path -Leaf $SourceSbom)" -Encoding ascii

# bsdtar on some Windows hosts mishandles non-ASCII command-line arguments.
# Keep the official Chinese-named deck for direct submission and stage an ASCII
# alias inside the server bundle so packaging is deterministic across hosts.
$DeckCandidates = @(Get-ChildItem -LiteralPath $OutDir -Filter "CyberGuard-GOAI-*-v${Version}.pptx" | Where-Object { $_.Name -notlike "CyberGuard-GOAI-preliminary-*" })
if ($DeckCandidates.Count -ne 1) {
    throw "Expected exactly one official GOAI deck for version $Version, found $($DeckCandidates.Count)"
}
$Deck = $DeckCandidates[0].FullName
$DeckHash = "$Deck.sha256"
$BundleDeck = Join-Path $OutDir "CyberGuard-GOAI-preliminary-v${Version}.pptx"
$BundleDeckHash = "$BundleDeck.sha256"
$OfficialDeckDigest = Get-FileHash -Algorithm SHA256 -LiteralPath $Deck
Set-Content -LiteralPath $DeckHash -Value "$($OfficialDeckDigest.Hash.ToLower())  $(Split-Path -Leaf $Deck)" -Encoding utf8
Copy-Item -LiteralPath $Deck -Destination $BundleDeck -Force
$BundleDeckDigest = Get-FileHash -Algorithm SHA256 -LiteralPath $BundleDeck
Set-Content -LiteralPath $BundleDeckHash -Value "$($BundleDeckDigest.Hash.ToLower())  $(Split-Path -Leaf $BundleDeck)" -Encoding ascii

$Items = @(
    ".env.example", ".dockerignore", ".gitignore", ".github", "compose.yaml", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE", "README.md", "VERSION",
    "agentteams", "benchmark", "config", "contracts", "deploy", "docs", "scenarios", "scripts", "services", "skills", "tests", "dist/skills",
    "dist/CyberGuard-GOAI-preliminary-v${Version}.pptx", "dist/CyberGuard-GOAI-preliminary-v${Version}.pptx.sha256",
    "dist/CyberGuard-source-v${Version}.spdx.json", "dist/CyberGuard-source-v${Version}.spdx.json.sha256"
)
tar --exclude='*/__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='benchmark/results' --exclude='benchmark/room-map.json' --exclude='artifacts' -a -cf $Archive @Items
if ($LASTEXITCODE -ne 0) {
    throw "tar failed with exit code $LASTEXITCODE"
}

$RequiredArchiveEntries = @(
    "README.md",
    "compose.yaml",
    "deploy/bootstrap-server.sh",
    "deploy/preflight.sh",
    "deploy/init_secrets.py",
    "deploy/validate_config.py",
    "docs/RELEASE.md",
    "docs/JUDGE_DEMO.md",
    "deploy/judge-demo.sh",
    "benchmark/audit_results.py",
    "deploy/bootstrap-agentteams.py",
    "deploy/bootstrap-agentteams.sh",
    "deploy/prepare-agentteams-bootstrap.sh",
    "deploy/validate-agentteams-state.py",
    "deploy/competition-readiness.sh",
    "agentteams/bootstrap-manager-request.md",
    ".github/workflows/ci.yml",
    ".github/dependabot.yml",
    "dist/CyberGuard-GOAI-preliminary-v${Version}.pptx",
    "dist/CyberGuard-GOAI-preliminary-v${Version}.pptx.sha256",
    "dist/CyberGuard-source-v${Version}.spdx.json",
    "dist/CyberGuard-source-v${Version}.spdx.json.sha256",
    "dist/skills/SHA256SUMS"
)
$ArchiveEntries = @(tar -tf $Archive)
if ($LASTEXITCODE -ne 0) {
    throw "tar listing failed with exit code $LASTEXITCODE"
}
foreach ($Entry in $RequiredArchiveEntries) {
    if ($Entry -notin $ArchiveEntries) {
        throw "Release archive is missing required entry: $Entry"
    }
}

$ForbiddenArchivePrefixes = @(
    "benchmark/results/",
    "benchmark/room-map.json",
    "artifacts/"
)
foreach ($Entry in $ArchiveEntries) {
    foreach ($Prefix in $ForbiddenArchivePrefixes) {
        if ($Entry -eq $Prefix.TrimEnd('/') -or $Entry.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Release archive contains restricted runtime evidence: $Entry"
        }
    }
}

$Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $Archive
Set-Content -LiteralPath "$Archive.sha256" -Value "$($Hash.Hash.ToLower())  $(Split-Path -Leaf $Archive)" -Encoding ascii
$Hash | Format-List
Write-Host "Release archive: $Archive"
