# Judge demo runbook

## Prepared deterministic service check

Prerequisite: a Linux/Bash host with Python 3, curl and GNU coreutils, a generated `.env`, and the baseline `compose.yaml` services already healthy. Follow [QUICKSTART.md](QUICKSTART.md) first, including creation of the external `agentteams-net` network. No model key or running AgentTeams/Matrix deployment is needed for this script.

1. Open the read-only audit view at `http://127.0.0.1:18100/console` (SSH-forward this loopback port when using a server).
2. Run `bash deploy/judge-demo.sh` as a user able to read the local `.env`. It does not rebuild or alter configuration, but creates test incidents and response records.
3. Select the newly generated `E2E-*` incidents in the audit view and inspect evidence, approval records, recovery results and rollback.
4. Open `artifacts/demo/<timestamp>/demo-summary.json` and `SHA256SUMS` as the machine-readable result. Check with `(cd artifacts/demo/<timestamp> && sha256sum -c SHA256SUMS)`.

The script runs both fixed scenarios with **simulation execution** in the baseline Compose deployment. Each collects fixture evidence and executes the three exact actions declared by that scenario's recovery contract. It checks recovery before the response set, rejects unapproved execution, verifies the complete approved set, validates the audit chain, and checks that rollback invalidates recovery. The harness supplies the approval credential itself (`server-e2e-test`); this is not actual human review or an Agent/LLM investigation.

The current script does **not** check recovery between the first and third actions and does **not** demonstrate a failed post-execution verification followed by a revised proposal. Do not present it as that full exception-handling storyline. The separately retained [live AgentTeams task evidence](LIVE_TASK_EVIDENCE.md) records a wrong-target proposal and subsequent correction; its recovery contract is deterministic too. The [host laboratory](HOST_LAB.md) independently observes harmless real processes restarting after termination and is the separate entry point for an actual-state failure demonstration. Neither is a production intrusion remediation claim.

The multi-user operations console is a separate surface on port **18120**, with first-admin setup and session requirements described in [OPERATIONS_DEPLOY.md](OPERATIONS_DEPLOY.md). Matrix role lanes belong to a separately running AgentTeams task; the deterministic script does not generate them.

## Run correlation one-pager

`scripts/export-run-correlation.py` renders an offline Markdown + JSON one-pager per incident (optionally per `--run-id`) from a gateway data directory's `evidence.jsonl` / `workflow.jsonl`: one merged timeline of workflow transitions (including human approval waits) and evidence collection, plus quality metrics, envelope-integrity checks and pointers to the authenticated run export and audit chain. No service needs to be running. See `docs/examples/run-correlation-CG-2026-0002.md` for the console-demo incident.

```bash
python scripts/export-run-correlation.py CG-2026-0002 --data-dir <gateway-data-dir> \
  --output run-correlation-CG-2026-0002.md --json-output run-correlation-CG-2026-0002.json
```

The view correlates gateway-side evidence and workflow only. Native Matrix/AgentTeams task events (Task, Worker, Skill versions, model usage) are referenced as a pointer to [LIVE_TASK_EVIDENCE.md](LIVE_TASK_EVIDENCE.md), not covered by this view.

## Claims boundary

- The deterministic service demo proves control and audit semantics, not LLM quality.
- AgentTeams/real-model quality claims require the separately audited 40-run benchmark matrix.
- If the demo fails, preserve the terminal output and run `sudo bash deploy/server-acceptance.sh`; its ERR trap records redacted service logs and Compose state under `artifacts/acceptance/`.
