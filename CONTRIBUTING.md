# Contributing to CyberGuard

CyberGuard welcomes narrowly scoped improvements to security tools, evidence contracts, Skills, deployment, evaluation and AgentTeams integration.

## Development workflow

1. Create a branch from the current default branch.
2. Keep changes free of customer telemetry, credentials and raw Matrix traces.
3. Run `powershell -ExecutionPolicy Bypass -File scripts/test-local.ps1` on Windows or `bash scripts/test-local.sh` on Linux.
4. If a contract changes, update its scenario, test, documentation and benchmark ground truth together.
5. Open a pull request using the repository checklist and describe both the intended benefit and new failure modes.

Container, dependency and GitHub Action references should be digest or full-commit pinned. Do not replace the validated AgentTeams version independently of its commit and installer checksum. New response actions must remain deny-by-default, approval-gated, idempotent, reversible where possible and independently verifiable.

Generated benchmark scores are accepted only with prompts, run metadata, failed runs, independent labels and model/tool telemetry. Do not submit self-graded model outputs as ground truth.

## Upstream contributions

Changes that improve AgentTeams itself should be proposed upstream as a small generic patch with an independent reproduction. Keep CyberGuard-specific policy and security-domain behavior in this repository unless it exposes a reusable AgentTeams infrastructure gap.
