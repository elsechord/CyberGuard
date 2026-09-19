# Quickstart — from clone to evidence in the audit console

Goal: a stranger with Git, Python 3.12 and (optionally) Docker reaches a live
read-only audit console with their first collected evidence.

**Measured on 2026-09-18** (Windows 11, Git Bash, Python 3.12.10, fresh clone
of `elsechord/CyberGuard`): venv creation to first evidence in the console in
**6 min 07 s**, including the full 23-file test suite (2 min 01 s). Clone over
a normal connection adds seconds. The 15-minute target therefore holds with
margin on the Python path; the Docker path additionally pays image build time
on first run (the same build runs in CI on every push).

Pick one path:

- [Path A — Docker Compose](#path-a--docker-compose-recommended)
- [Path B — Python venv, no Docker](#path-b--python-venv-no-docker)
- [Pitfalls recorded during the stranger test](#pitfalls-recorded-during-the-stranger-test)

## Path A — Docker Compose (recommended)

Requires Docker Engine or Docker Desktop. Both images build from the repository
(the identical build is exercised in CI on every push).

1. **Clone and enter the repository**

   ```bash
   git clone https://github.com/elsechord/CyberGuard.git
   cd CyberGuard
   ```

2. **Generate the role-separated secrets**

   ```bash
   python deploy/init_secrets.py
   ```

   This stdlib-only script reads `.env.example` and writes a mode-0600 `.env`
   with independent random values for the gateway token, executor token,
   approval secret, audit HMAC key and audit reader token. It never prints the
   generated values. Read the token you need later with, for example,
   `grep CYBERGUARD_API_TOKEN .env`.

3. **Build and start the stack**

   ```bash
   docker network inspect agentteams-net >/dev/null 2>&1 || docker network create agentteams-net
   docker compose up -d --build
   ```

   These commands use Bash. `agentteams-net` is an external Compose network;
   create it on a clean Docker host even when AgentTeams is not installed.

   The gateway binds to `127.0.0.1:18100` and the response executor to
   `127.0.0.1:18105` — loopback only, never on all interfaces. Containers run
   non-root, read-only, with all Linux capabilities dropped.

4. **Open the console and collect the first evidence**

   Open <http://127.0.0.1:18100/console>. The incident list starts empty by
   design: incidents appear once evidence is collected. Collect the first
   fixture evidence with the token from your `.env`:

   ```bash
   curl -X POST http://127.0.0.1:18100/tools/alert/snapshot \
     -H "Authorization: Bearer $(grep -m1 CYBERGUARD_API_TOKEN .env | cut -d= -f2)" \
     -H "Content-Type: application/json" \
     -d '{"incident_id":"CG-QUICKSTART","scenario_id":"credential_compromise"}'
   ```

   Reload the console: incident `CG-QUICKSTART` now shows its evidence count,
   sources, ATT&CK techniques and quality gate.

Stop with `docker compose down` (add `-v` to also drop the evidence volume).

## Path B — Python venv, no Docker

Verified on Windows Git Bash; on Linux use `.venv/bin/python` instead of
`.venv/Scripts/python`. Both services only need FastAPI/uvicorn/httpx.

1. **Clone and create a virtual environment**

   ```bash
   git clone https://github.com/elsechord/CyberGuard.git
   cd CyberGuard
   python -m venv .venv
   ```

2. **Install dependencies**

   On Linux x86_64 the hash-locked set installs directly:

   ```bash
   .venv/Scripts/python -m pip install -r services/requirements.lock -r tests/requirements.lock
   ```

   On Windows the hash lock does not resolve (it pins Linux-only wheels for
   binary packages such as `pydantic-core`); fall back to the service
   requirements plus the test HTTP client:

   ```bash
   .venv/Scripts/python -m pip install \
     -r services/security-tool-gateway/requirements.txt \
     -r services/response-executor/requirements.txt httpx
   ```

3. **Run the test suite (optional but recommended)**

   ```bash
   for f in tests/test_*.py; do .venv/Scripts/python "$f" || break; done
   ```

   23 files, one interpreter each, measured 2 min 01 s. Do **not** run
   `pytest tests/` in a single process: both services expose an `app` package,
   so whole-suite collection in one interpreter is not supported.

4. **Start the read-only gateway on loopback**

   ```bash
   export PYTHONPATH="$PWD" CYBERGUARD_API_TOKEN=dev-read-token
   export CYBERGUARD_SCENARIO_DIR="$PWD/scenarios" \
          CYBERGUARD_DATA_DIR="$PWD/tmp/data" \
          CYBERGUARD_KNOWLEDGE_DIR="$PWD/knowledge"
   mkdir -p tmp/data
   .venv/Scripts/python -m uvicorn app.main:app \
     --app-dir services/security-tool-gateway --host 127.0.0.1 --port 18100
   ```

   Open <http://127.0.0.1:18100/console> and collect the first evidence:

   ```bash
   curl -X POST http://127.0.0.1:18100/tools/alert/snapshot \
     -H "Authorization: Bearer dev-read-token" \
     -H "Content-Type: application/json" \
     -d '{"incident_id":"CG-QUICKSTART","scenario_id":"credential_compromise"}'
   ```

   Without the `Authorization` header every tool/API route answers `401`.

The response executor starts the same way with
`--app-dir services/response-executor` and its own executor/approval tokens —
see [the lab runbook](LAB_EXECUTION.md). Ports mirror the Compose files:
18100 gateway, 18105 response executor, 18110 model admission guard
(`compose.model-guard.yaml`).

## Prebuilt container images

CI publishes both services to GHCR on every published release and on manual
dispatch (workflow: [`.github/workflows/publish-images.yml`](../.github/workflows/publish-images.yml)):

```bash
docker pull ghcr.io/elsechord/cyberguard-gateway:sha-3b34e4c
docker pull ghcr.io/elsechord/cyberguard-executor:sha-3b34e4c
```

`sha-3b34e4c` is the tag pushed by the first verified dispatch run
(digests `sha256:46b4c0b6…` / `sha256:dd4715f6…`). Release tags (`vX.Y.Z`) and
`latest` are attached automatically when the next release is published.
Images are `linux/amd64` — the hash-locked wheel set targets Linux x86_64.

## Pitfalls recorded during the stranger test

Each row was hit while following only the README on a fresh clone
(2026-09-18) and is resolved in the steps above.

| Snag | Symptom | Resolution |
|---|---|---|
| Port 18100 already occupied on a shared dev machine | `uvicorn` exits with code 3, `[winerror 10048]` bind error | Pass `--port 18255` (or any free port). The console and API work the same. |
| Busy port serves *another* CyberGuard instance | `curl` on the busy port returns `200`/`401` and `{"detail":"invalid bearer token"}` **with a correct token** | That response comes from the foreign instance, not yours. After starting yours, verify identity via the console title (`CyberGuard · 证据审计台`) before debugging tokens. |
| pip fails behind a dead proxy | connection timeouts during `pip install` | Unset the proxy environment (`env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy …`) or point it at a working proxy. Environmental, not a repository issue. |
| Hash-locked install fails on Windows | `--require-hashes` cannot find a matching Windows wheel for binary packages | Expected: `services/requirements.lock` intentionally targets Linux x86_64. Use the fallback in step 2 of Path B. |
| Incident list empty after first launch | `/incidents` returns `{"incidents":[]}` | By design: incidents materialize from collected evidence. Send the `alert/snapshot` call above and reload. |
| Whole test suite in one pytest process | import errors / `app` package collisions | Run test files one per interpreter, as in step 3 of Path B. |

## Where to go next

- [What is runnable today](../README.md#what-is-runnable-today) — scope and honest boundaries.
- [Lab runbook](LAB_EXECUTION.md) — full response-executor lifecycle (proposal, approval, rollback).
- [Threat model](THREAT_MODEL.md) — trust boundaries before you expose anything.
