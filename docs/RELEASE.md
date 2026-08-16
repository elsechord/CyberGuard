# Release process

The checked-in Python lock file targets CPython 3.12 on Linux x86_64. Regenerate and verify it before introducing another CPU architecture.

1. Update `VERSION`, `CHANGELOG.md`, service metadata, Compose image tags and competition materials together.
2. Run both local validation entry points where available.
3. Generate and inspect the deterministic source SBOM:

   ```bash
   python3 scripts/generate-source-sbom.py --output artifacts/sbom/source.spdx.json
   ```

4. Build the release; the packaging gate reruns tests, packages Skills, refreshes the official deck checksum, generates the source SBOM and rejects missing or restricted archive entries:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/package-release.ps1
   ```

5. On a clean target server, run `sudo ./deploy/bootstrap-server.sh` and retain the checksummed acceptance archive.
6. Run all benchmark variants without discarding failures. Freeze ground truth before reviewing outputs and retain independent annotations and telemetry.
7. Tag exactly `v$(cat VERSION)`. Attach the server ZIP, checksum, official deck, checksum, source SPDX SBOM, container SBOMs from CI and a redacted acceptance manifest.
8. Publish only claims supported by those artifacts. Container/model performance remains pending until server evidence exists.

GitHub Actions and third-party scanners are pinned to full commit SHAs. Dependabot proposals must pass the same workflow before pins are updated.
