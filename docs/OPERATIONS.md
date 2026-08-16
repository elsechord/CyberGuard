# Operations runbook

## Health

```bash
docker ps --filter name=agentteams
docker compose ps
curl -fsS http://127.0.0.1:18100/health
curl -fsS http://127.0.0.1:18105/health
```

The audit console is available only on host loopback at `http://127.0.0.1:18100/console`. Use an SSH tunnel or private VPN; do not expose port 18100 directly to the Internet.

## End-to-end acceptance

```bash
sudo bash deploy/bootstrap-server.sh
```

The bootstrap performs host preflight, creates `.env` securely when absent, validates both environment files, installs AgentTeams when its network is absent, then runs server acceptance. Acceptance builds (unless `CYBERGUARD_SKIP_BUILD=1`), starts and verifies the services, creates a unique simulated incident, proves the approval/execute/verify/rollback path, and writes a timestamped evidence archive under `artifacts/acceptance/`. The archive contains versions, image digests, service state, redacted logs, OpenAPI schemas, API evidence and SHA256 manifests. It must pass before a competition demonstration or release.

The evidence archive intentionally excludes `.env`, approval secrets, bearer tokens and full container inspection output. It includes a machine-readable acceptance manifest, immutable image IDs, an HMAC-authenticated audit checkpoint, checksums for every closed evidence file and failure diagnostics when any gate aborts. `acceptance.log` is deliberately identified as unhashed because its stream remains open until script exit. Store the archive with the submission evidence; do not commit customer telemetry.

The five generated secrets have separate roles: Worker read access, response proposal/execution, human approval, audit-record authentication and read-only audit-state verification. Do not give the approval or audit-HMAC secret to an Agent. Rotate the audit HMAC key only at a documented checkpoint boundary; old records require the old key for verification.

Recovery is contract-bound: the authenticated executor state returns exact active action/target pairs, and the gateway compares them with the selected scenario's `required_actions`. An unrelated action, wrong target, partial action set, expired approval or rollback cannot produce `verdict=verified`.

## AgentTeams bootstrap and readiness

After the one-time Higress tool registration, `deploy/bootstrap-agentteams.sh` replaces the baseline's manual copy/paste flow. It stages checksum-verified Skill ZIPs through AgentTeams' configured `/host-share`, sends a hash-bound request to the unique Manager DM and validates the exact seven-role manifest. `deploy/competition-readiness.sh` then cross-checks that manifest against live Worker and Team CR snapshots and emits a checksummed readiness report. A Manager reply alone is not accepted as proof of readiness.

## Logs

```bash
docker compose logs --tail=200 security-tool-gateway
docker compose logs --tail=200 response-executor
docker exec agentteams-manager cat /var/log/agentteams/manager-agent.log
```

Do not publish `.env`, `agentteams-manager.env` or raw logs. Use the AgentTeams redacted debug export for upstream reports.

## Backup

Back up these independently:

- Docker volume `agentteams-data`;
- Docker volumes `cyberguard-evidence` and `cyberguard-actions`;
- `/srv/cyberguard/agentteams-manager`;
- source-controlled Skills, schemas and scenarios.

Stop new tasks before taking a consistent backup. Test restoration on a separate host before relying on it.

## Upgrade

CyberGuard pins AgentTeams v1.2.2. Do not switch to `latest` on the competition server. Test an upgrade on a cloned volume, rerun the baseline and CyberGuard smoke tests, then update the pinned version deliberately.

## Incident reset for a fresh demo

Use a new `incident_id` for every run. The deterministic scenario may be reused. Do not delete audit records between runs; filter by incident ID. If a clean-room performance measurement is required, clone the stack into a separate benchmark environment rather than erasing the primary audit history.
