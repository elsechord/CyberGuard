# Real account laboratory

This lab exercises one real side effect: disabling and restoring `compromised-lab` in a dedicated SQLite-backed identity service. `control-lab` must stay accessible. It is a service integration proof, not a production identity connector, an attack-detection benchmark, or a new live AgentTeams task.

## Install and reproduce

Use Python 3.12 or newer and a disposable virtual environment. Run from the repository root. The demo requires the complete source checkout, including `tests/lab_support.py`.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r services/security-tool-gateway/requirements.txt
.\.venv\Scripts\python -m pip install --require-hashes --no-deps -r tests/requirements.lock
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python scripts/lab-demo.py
```

The Windows service installation pins direct dependencies; transitive dependencies are resolved by pip. It is not identical to the Linux hash-locked environment. The HTTP test dependency file adds `httpx`, `httpcore` and `certifi`; its other dependencies are supplied by the service installation and checked with `pip check`.

Linux x86_64 / CPython 3.12 (the platform targeted by the existing service lock):

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r services/requirements.lock -r tests/requirements.lock
.venv/bin/python -m pip check
.venv/bin/python scripts/lab-demo.py
```

To run all local tests, activate the environment and run `powershell -ExecutionPolicy Bypass -File scripts/test-local.ps1` on Windows or `bash scripts/test-local.sh` on Linux. To run only the new fault-injection tests: `python tests/test_lab_execution.py`.

The demo starts the identity service, executor and gateway on three free loopback ports. It creates fresh random credentials per role and uses a temporary database and audit directory. It never accepts production URLs or credentials. Processes and private temporary state are removed at exit; output contains evidence rather than secrets. A failed check exits nonzero and retains a failure manifest. There are 17 checks, including the run-scoped export.

## Run in Docker

With a running Linux Docker engine:

```bash
docker compose -f compose.lab.yaml up --build --abort-on-container-exit --exit-code-from lab
mkdir -p artifacts/docker-lab
docker compose -f compose.lab.yaml cp lab:/artifacts/. artifacts/docker-lab/
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=128m cyberguard/lab:local python tests/test_lab_execution.py
```

The lab image contains the three services and the test harness in one non-root container; they communicate over its own loopback interface. Runtime networking is disabled, no host ports are exposed, and writable state lives in a temporary filesystem. Evidence persists in the dedicated `cyberguard-lab_lab-artifacts` volume. The build downloads pinned dependencies and therefore needs network access. The runtime needs no LLM key, `.env`, production credential, or AgentTeams installation.

For source attribution, optionally set `CYBERGUARD_SOURCE_COMMIT` to `git rev-parse HEAD` before building. This is a declared build argument, not an attestation of a clean checkout. Container exports hash the included source files and label their origin `exported_source`, with `git_dirty=null`; native Git runs keep their actual dirty flag. The container source snapshot includes the service, script, test, scenario and knowledge directories, not a complete Git checkout.

The existing two-service production Compose file remains separate and defaults to simulation. This standalone lab does not connect to AgentTeams' container network and is not a production deployment recipe. CI also builds and runs it, retains the exported evidence, and runs its fault-injection suite.

## What the artifact proves

`artifacts/lab/LAB-<uuid>/` contains:

- `manifest.json`: run, action and environment IDs, model/execution modes, timestamps and each check's result.
- `trace.json`: proposal, rejection before approval, approval, execution, separate access observations, rollback and audit verification responses.
- `action-history.json`: the executor's HMAC-chained records; the signing key is not exported.
- `run-export.json`: only evidence and authenticated action events belonging to this incident/run, with per-action status and the latest applicable observation.
- `source-tree.json`: Git commit, dirty-worktree flag and hashes of current tracked/unignored source files. A dirty run is explicitly labeled.
- `SHA256SUMS`: integrity checksums for these JSON files. Checksums alone do not authenticate who produced them; offline HMAC verification requires the separately held key.

The harness checks real access before execution and after rollback. In between, the gateway sends fresh, nonce-bound HTTP requests as each account. A successful executor receipt alone never sets the lab verdict to `verified`.

## Run-scoped API and console

All tool calls accept an optional top-level `run_id`. In lab verification it is mandatory, with backwards compatibility for `arguments.run_id`; contradictory values are rejected before collection. New evidence includes server-created `tool_call_id`, `scenario_id`, environment/execution labels and `envelope_sha256`. The envelope digest covers the run association and serialized evidence, while the existing `sha256` remains the source-record digest. Hashes detect accidental or uncoordinated edits; they are not signatures against an attacker who can rewrite both data and hashes.

`GET /incidents/<incident>/runs/<run>` on the gateway returns a downloadable JSON view. It obtains the action chain through the executor's authenticated read-only `/audit/incidents/<incident>/events?run_id=<run>` snapshot, rather than trusting a mounted JSONL file. The executor validates its entire audit under one lock, then selects the requested run's proposals and associated action events, including approvals. An unavailable/invalid audit yields no trusted action states. Evidence integrity failure prevents a prior green observation from being reused.

The export has an `export_sha256` digest over every field except `export_sha256` itself, using sorted keys, UTF-8, unescaped Unicode and compact JSON separators. `audit_assurance=executor_validated_snapshot` is a server assertion at the reported snapshot time: this filtered export alone does not independently authenticate the complete global chain or prove external anchoring.

In `/console`, select a run to show only its evidence and authenticated actions, mode, probe results and export button. Incident-wide graphs and workflow panels are hidden in this scoped view to avoid mixing runs. Refresh downloads records; it does not rerun probes. A rolled-back action is no longer verified even if its historical successful observation is still present in the evidence ledger. Legacy events without a run ID remain visible in the incident summary.

The export button also reveals a read-only JSON preview for browsers that do not start a file download. It preserves the server's original JSON text: parsing and reserializing in JavaScript can turn `1.0` into `1` and change a Python-serialized digest. Validate with Python's `json.loads` followed by `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`; do not normalize number tokens through another serializer before validation. These are version-1 Python serialization digests, not an implementation of RFC 8785/JCS.

The export explicitly records `agentteams_task=not_attested`, `worker_skill_binding=not_attested` and `model_mode_source=caller_reported`. Enforcing run separation for service evidence is not yet an authenticated mapping to native AgentTeams tasks, Workers, Skills or human identities.

`approval_mode=automated_lab_harness` means the script itself uses a separate approval credential. This proves the API gate and proposal binding, **not a real human's decision or an autonomous model's reasoning**. `model_mode=deterministic` and `agentteams_task=false` are explicit. The response-loss/restart proof is in the integration tests, rather than the normal demo trace.

## Execution and verification contract

| Mode / source | Behavior | What success means |
| --- | --- | --- |
| `CYBERGUARD_EXECUTION_MODE=simulation` (default) | Existing fixture actions; no identity mutation | `simulated_success`; fixture recovery has `execution=simulated` and `verification_scope=simulated_response_contract` |
| `CYBERGUARD_EXECUTION_MODE=lab` | Only `disable_account` on `compromised-lab`; real database mutation | `result=applied` records a bound backend receipt; `verification_status=pending` until independent probing |
| `scenario_id=lab_identity`, `recovery.metrics` | Read authenticated action state, then target and control access | `verified` only for a matching active run/action/environment, disabled target, accessible control and valid fresh responses |
| Generic `scenario_id=live`, `recovery.metrics` | Preserve incoming verdict as `reported_verdict` | `inconclusive` until a specific independent verifier contract exists |

`lab_identity` currently supports only `recovery.metrics`. It is not a complete new investigation fixture. Call the existing endpoint:

```json
{
  "incident_id": "CG-LAB-001",
  "scenario_id": "lab_identity",
  "arguments": {"run_id": "LAB-example", "action_id": "ACT-example"}
}
```

Send this to `POST /tools/recovery/metrics` with the gateway credential. Unknown/mismatched run, unavailable audit, missing probe, invalid account credential, wrong nonce or changed environment produces `inconclusive`. Observed target access still enabled or control access disabled produces `failed`. Both are distinct from `verified`. The scope is `point_in_time_lab_access`: two sequential observations do not prove sustained recovery, eradication of persistence, production uptime or a time-window SLO.

Every lab proposal requires `run_id`; the executor binds the target, environment ID, backend origin and request to the proposal record. `model_mode` is caller-reported metadata, not independently attested model provenance. This tranche does not yet bind every investigation, skill and AgentTeams event to one global run manifest.

## Failure, restart and concurrency

Before a mutation, the executor validates its audit chain and durably appends `execution_dispatched`. The identity service atomically commits the account change and operation receipt in one SQLite transaction. A missing/invalid HTTP receipt appends `execution_unknown`.

After dispatch, another `execute` call only reconciles. `POST /actions/<id>/reconcile` reads the saved external receipt and can transition to `executed`; it never issues another write. This works after restarting both services with the same database, audit directory and credentials. A missing receipt remains unresolved because it does not prove that the operation never arrived. There is intentionally no automatic resend or cancellation recovery for this case yet.

Rollback requires the approval credential, records `rollback_dispatched`, and uses its own durable operation ID. Response loss becomes `rollback_unknown`; reconciliation may close it as `rolled_back`. Dispatching rollback immediately removes the action from the active verification set. Closed actions cannot execute again. The identity service prevents rollback by a different action/run and duplicate operations cannot change state again.

Run **one executor process / one Uvicorn worker**. Its JSONL audit uses a process-local lock, not a distributed transaction coordinator. It detects edited records but does not provide an external append-only anchor against an administrator deleting or replacing the whole audit. Do not claim distributed exactly-once execution, multi-tenant isolation, a tamper-proof host or guaranteed recovery across disk loss. The lab operation database supplies durable idempotency for this adapter only.

## Manual service configuration

The harness in `tests/lab_support.py` is the executable reference. Each role receives only its required credentials:

| Service | Configuration / credentials |
| --- | --- |
| Identity | `CYBERGUARD_LAB_ADMIN_TOKEN`, `CYBERGUARD_LAB_TARGET_TOKEN`, `CYBERGUARD_LAB_CONTROL_TOKEN`; three distinct random values of at least 32 characters; CLI `--db <path> --port <port>` |
| Executor | Existing executor, approval, audit-HMAC and audit-reader secrets; lab admin token; `CYBERGUARD_EXECUTION_MODE=lab`; `CYBERGUARD_LAB_URL=http://127.0.0.1:<port>`; own `CYBERGUARD_DATA_DIR` |
| Gateway | Existing gateway and audit-reader tokens; target and control account tokens; `CYBERGUARD_LAB_URL`; `CYBERGUARD_AUDIT_VERIFY_URL=http://127.0.0.1:<executor-port>`; own data directory and source scenario/knowledge directories |

The gateway has no lab administrator token or audit signing key. The model/worker must never receive the approval secret. In a manually operated run, the human supplies it through `X-Approval-Secret` for approval and rollback. The harness deliberately automates that role for repeatable testing.

All three services bind to `127.0.0.1`. Lab clients reject non-loopback origins and HTTP redirects and bypass system proxy settings. The setup works as native processes or within the standalone Docker lab; existing production Compose and AgentTeams registration are not switched to it automatically. Binding it publicly or connecting a real IdP is outside this implementation.

`deploy/init_secrets.py` is for POSIX deployments: it creates mode-0600 secrets before publishing without overwriting an existing file. On native Windows it fails before writing because POSIX mode bits do not establish equivalent Windows ACL protection. Use WSL/Linux for that deployment flow; the native lab harness does not write a `.env` file.
