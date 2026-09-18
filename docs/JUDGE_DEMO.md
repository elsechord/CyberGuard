# Judge demo runbook

## 90-second path

1. Open the AgentTeams Matrix room and the read-only audit console through the prepared SSH tunnels.
2. Show seven role lanes, Evidence IDs and competing hypotheses in Matrix.
3. Run `sudo bash deploy/judge-demo.sh` on the server. It does not rebuild or alter configuration.
4. In the console, select each new incident and show evidence provenance, approval history, independent verification and rollback.
5. Open `artifacts/demo/<timestamp>/demo-summary.json` and `SHA256SUMS` as the machine-verifiable result.

The script runs both fixed scenarios. Each collects boundary-policy evidence and executes the three exact actions declared by that scenario's recovery contract. It proves that recovery is inconclusive before the complete response set, every unapproved execution is rejected, the approved reversible action set changes independent recovery evidence, the audit chain remains valid, and rolling back any required action returns recovery to inconclusive.

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
