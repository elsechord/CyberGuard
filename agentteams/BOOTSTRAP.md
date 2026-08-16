# CyberGuard AgentTeams bootstrap

Run this after AgentTeams and the CyberGuard containers are healthy.

The server installer pins AgentTeams `v1.2.2` to commit `849182af8e017168a5a200a87b1062142caf462d` and verifies the official installer SHA256 before execution. Do not change the tag, commit or checksum independently; re-run the compatibility suite and update all three together.

## 1. Register tool services

In the `Manager: default` Matrix room, ask the Manager to register two OpenAPI/MCP services through Higress:

- `cyberguard-readonly`: `http://security-tool-gateway:8080/openapi.json`
- `cyberguard-response`: `http://response-executor:8080/openapi.json`

Configure the bearer credentials in Higress, not in Worker prompts or Matrix messages. Assign `cyberguard-readonly` to all investigation Workers. Assign `cyberguard-response` only to `controlled-responder` and the Team Leader. The approval secret must remain human-controlled and must not be exposed to any Worker.

Verify from the Manager that both schemas are discoverable before creating the Team.

Do not paste bearer tokens into Matrix. This is the only secret-bearing setup step and must be completed directly in the loopback-only Higress administration surface or its authenticated API.

## 2. Automated Skill and Team bootstrap

After both tool schemas are discoverable, run:

```bash
sudo bash deploy/bootstrap-agentteams.sh
```

This packages and verifies all Skills, stages them at `/host-share/cyberguard-bootstrap`, logs into Matrix as the configured admin, locates the unique Manager DM, sends one hash-bound idempotent request, waits for the exact Manager completion marker, and validates the resulting seven-Worker manifest. No service, approval or audit credential is included in the Matrix request.

The automated assignments are:

Recommended assignments:

| Worker | Skills |
|---|---|
| `alert-fusion` | alert-triage, hypothesis-testing |
| `threat-intel` | threat-intel-enrichment, hypothesis-testing |
| `network-hunter` | network-hunting, boundary-defense, hypothesis-testing |
| `endpoint-forensics` | endpoint-forensics, hypothesis-testing |
| `response-planner` | response-planning, incident-reporting |
| `controlled-responder` | controlled-response |
| `recovery-verifier` | recovery-verification, incident-reporting |

## 3. Cross-check live AgentTeams resources

Run the fail-closed readiness gate after bootstrap:

```bash
sudo bash deploy/competition-readiness.sh
```

It compares the Manager-written manifest with live `agt get workers/teams` snapshots, validates CyberGuard configuration and services, and exports an authenticated audit checkpoint plus checksummed `readiness.json`.

## 4. Run the demo

Send the contents of `agentteams/demo-task.md` to the Team room and mention the Team Leader. Do not send the incident to the default Manager.

Success means that the Team produces cited evidence, competing hypotheses, a proposed response, an explicit approval pause, an independently verified result and an auditable final report.
