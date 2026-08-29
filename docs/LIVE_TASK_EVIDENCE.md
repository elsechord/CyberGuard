# Live AgentTeams Task Evidence Pack

How the "single real AgentTeams Task" evidence for the GOAI 复赛 was produced, and how to reproduce it. The judge-facing requirement: one native AgentTeams task from creation to terminal state, including the native event chain, approval, execution, independent re-verification, exception recovery and terminal state.

Reference run: incident `CG-2026-0002` (scenario `supply_chain_webshell`), AgentTeams v1.2.2, model `deepseek-v4-flash`, 2026-08-28/29. Packaged under `artifacts/live-task/webshell-<ts>/` with `evidence-manifest.json` and `SHA256SUMS`.

## Prerequisites

- Server deployment completed (`deploy/bootstrap-server.sh`), both CyberGuard services healthy.
- AgentTeams v1.2.2 installed; DeepSeek (or configured provider) reachable with funded balance — a full 8-agent run makes well over a hundred LLM calls.

## Tool service registration: three gotchas found on v1.2.2

The stock `setup-mcp-server.sh` path needed three adjustments on this version:

1. **Single-label Docker DNS names are rejected** by the Higress console (`ValidationException: serviceSource body is not valid`). Register the service source with a dotted alias instead, e.g. connect the CyberGuard containers to `agentteams-net` with alias `security-tool-gateway.cyberguard.local` / `response-executor.cyberguard.local` and use those as `--api-domain`.
2. **`--api-domain` without an explicit port defaults to `https:443`**, producing a dead `*.dns:443` service reference (503 on tool calls). Fix the `services` ref to port `8080` on the mcpServer object afterwards via `PUT /v1/mcpServer`.
3. **Consumer authorization must use the real consumer names**, which carry the `worker-` prefix (`worker-alert-fusion`, ...). Authorizing plain role names leaves every Worker at `auth required`. Correct with `PUT /v1/mcpServer/consumers` (full replace — always include `manager` and every previously authorized consumer).

Also note: `GET /v1/mcpServer` list responses omit `rawConfigurations`; never PUT a fetched list object back without restoring it, or the tool definitions are wiped (result: 404 on the MCP endpoint). Rebuild `rawConfigurations` from `agentteams/mcp/*.yaml` with the real bearer token substituted.

Verify end-to-end from a Worker container, not just the Manager:

```bash
docker exec agentteams-worker-alert-fusion mcporter call mcp-cyberguard-readonly \
  collect_alert_snapshot --args '{"incident_id":"CG-2026-0002","scenario_id":"supply_chain_webshell"}'
```

A real `evidence_id` in the response proves the Worker→Higress→gateway path including per-Worker credentials.

## Team bootstrap

`deploy/bootstrap-agentteams.sh` + `deploy/bootstrap-agentteams.py` send the hash-bound request to the Manager DM. Expect the Manager to refuse the first attempt: it treats unsigned chat instructions as potential injection and requires explicit admin authorization in the room. Reply in the Manager DM authorizing access to `/host-share/cyberguard-bootstrap/`. Keep an eye on runaway shell commands the Manager may issue (a full-filesystem `grep` was observed); `docker restart agentteams-manager` safely resumes its loop.

After the Manager reports `CYBERGUARD_BOOTSTRAP_COMPLETE` and writes `manager-result.json`, run the fail-closed gate:

```bash
bash deploy/competition-readiness.sh
```

Two consistency notes for this release:

- `deploy/validate-agentteams-state.py` expects `metadata.name` CR shapes, while `agt get workers -o json` exports plain `name`. Wrap entries as `{"metadata": {"name": ...}, "spec": {...}}` before validation.
- The validator expects `response-planner` to hold **both** `cyberguard-readonly` and `cyberguard-response` (it proposes through the response service but never executes), while `agentteams/BOOTSTRAP.md` grants response tools only to the responder and Team Leader. The validator reflects the intended design.

## Running the task and capturing evidence

```bash
python3 scripts/capture-agentteams-task.py \
  --env-file agentteams.env --cyberguard-env .env \
  --task-file agentteams/demo-task-supply-chain.md \
  --out artifacts/live-task/webshell-$(date -u +%Y%m%dT%H%M%SZ) \
  --timeout 21600
```

The capturer prints `PENDING APPROVAL: ACT-…` lines when the responder pauses at the approval gate. Approvals are a human step:

```bash
bash scripts/approve-action.sh ACT-xxxxxxxxxxxx <approver-name>
```

Approvals expire after 15 minutes; if the LLM provider stalls past expiry, re-approve — the executor accepts re-approval of an unexpired proposal.

## Exception recovery demonstration

After the final report (verdict `verified`), roll back one executed action and re-query recovery: the verdict must return to `inconclusive` naming the missing action. This mirrors the `rollback_invalidates_recovery` gate of `tests/e2e_demo.sh`, now on the live path.

```bash
curl -fsS -H "Authorization: Bearer $CYBERGUARD_EXECUTOR_TOKEN" \
  -X POST http://127.0.0.1:18105/actions/ACT-xxxxxxxxxxxx/rollback
```

## Reference run highlights (2026-08-29)

- Team `cyberguard-soc` Active, 7/7 Workers ready; readiness gate `valid: true`, zero issues.
- 4 actions proposed, human-approved (hash-bound), executed; audit chain 14 records, `valid` + `authenticated`.
- Independent re-verification round 1 returned `inconclusive`: the deterministic contract caught that A2 targeted the full pod name instead of the exact contract target `checkout-api` — the exception branch reopened the plan, a corrected proposal was approved and executed, round 2 returned `verified`.
- The scenario-embedded injection marker (`CYBERGUARD_INJECTION_MARKER_DO_NOT_COPY`) appeared twice in tool output and was ignored and reported by the team both times.
- Two LLM provider outages (402) occurred mid-run; Workers failed visibly and resumed after recovery — the full failure/recovery sequence is retained in the event chain.
