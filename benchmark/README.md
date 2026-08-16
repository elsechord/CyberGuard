# CyberGuard evaluation

The benchmark demonstrates that the AgentTeam provides measurable value beyond a single large prompt.

Run both deterministic scenarios five times for each variant in `variants.json`. Use a fresh incident ID per run, export the Matrix/task trace, and save the final structured report as:

```text
benchmark/results/<variant>/<scenario>/<run-id>/report.json
benchmark/results/<variant>/<scenario>/<run-id>/metrics.json
```

Create four separately configured AgentTeams rooms matching the variants using `agentteams/create-benchmark-teams-message.md`, copy the returned exact room IDs into `room-map.example.json`, save it as the ignored `benchmark/room-map.json`, and run the Matrix collector:

```bash
export MATRIX_BASE_URL=http://127.0.0.1:18080
export MATRIX_USERNAME=admin
export MATRIX_PASSWORD='read-from-the-server-secret-store'
python3 benchmark/matrix_runner.py --room-map benchmark/room-map.json
```

The runner refuses an unrecorded model configuration. Provide `--model-id` and `--temperature`, or set `BENCHMARK_MODEL_ID` and `BENCHMARK_TEMPERATURE`. Every run then receives a `provenance.json` binding the run ID, variant, disabled capabilities, scenario hash, exact prompt hash, CyberGuard version, AgentTeams version, model ID and temperature.

The collector accepts only reports that return the exact current `run_id`; mismatched marked reports are retained in `trace.json` as rejected rather than contaminating another run. It retains `prompt.txt`, `provenance.json`, `trace.json`, `report.json` and `runtime.json`. Treat `trace.json` as restricted evidence because Matrix messages can contain user IDs, room IDs, hostnames and incident artifacts; redact or replace those fields before publishing a benchmark bundle. It deliberately writes an `annotation.template.json` instead of letting the evaluated Agent grade its own root-cause and safety performance. Freeze the current `ground-truth-v2.json` before viewing runs, complete an independent `annotation.json`, import real AgentTeams token/tool telemetry into `runtime.json`, then finalize. `ground-truth-v1.json` remains immutable for reproducibility of earlier results:

```bash
python3 benchmark/finalize_run.py \
  benchmark/results/<variant>/<scenario>/<run-id> \
  benchmark/results/<variant>/<scenario>/<run-id>/annotation.json
```

Before publishing numbers, fail closed on missing runs, prompt/scenario tampering, incomplete human labels or model-condition drift:

```bash
python3 benchmark/audit_results.py --results benchmark/results \
  --output artifacts/benchmark-audit.json
```

Timeouts and missing structured reports are retained as failed `metrics.json` runs. Successful runs cannot be finalized while human labels or telemetry fields are missing.

Evaluate report structure and safety:

```bash
python3 benchmark/evaluate.py path/to/report.json
```

Human ground truth must be fixed before inspecting Agent outputs. Record root-cause correctness, evidence precision, unsafe attempted actions and false recovery separately from formatting quality. Capture elapsed time, tool calls and model tokens from AgentTeams/AgentLoop telemetry.

The primary comparison is `single-agent` versus `cyberguard-full`. The two ablations identify whether gains come from the evidence contract and independent verifier rather than simply using more model calls.

Do not discard failed runs. The aggregator reports completion with a Wilson interval, metric means with deterministic bootstrap 95% intervals, observation/missing counts, pooled evidence and unsafe-action rates, and every failure category. Missing safety or resource observations remain `null`; a timeout can therefore never improve a variant's apparent safety or cost. Keep prompts, model ID, temperature, scenario data and AgentTeams version fixed across variants.
