# Operations console deployment runbook

For a fresh host running native investigations, use [the complete AgentTeams installation sequence](NATIVE_INSTALL.md). Starting this Console alone does not provision its model or AgentTeams Workers. Keep the generated private `console.override.json` on every Compose upgrade so the backend binding survives recreation.

One-page guide for bringing up, upgrading, backing up and migrating the
multi-user operations console (`services/operations-console`). The console is
part of the main `compose.yaml` project: loopback port `127.0.0.1:18120`,
health endpoint `/healthz`, all state in the `cyberguard-console-data` volume
(`/data/console.db`). Application usage (accounts, roles, screens) is covered
by [docs/OPERATIONS_CONSOLE.md](OPERATIONS_CONSOLE.md).

## Prerequisites

- Baseline host from the README: Ubuntu 22.04/24.04 x86_64, 8 CPU cores,
  16 GB RAM, 100 GB SSD, Docker Engine with the compose plugin. The hash-locked
  Python wheel set targets Linux x86_64.
- Size the console database for retained source materials, reports and task events.
  The console reaches the gateway/executor internally and, when configured,
  AgentTeams Matrix/Workers on the authorized private network. Worker model
  processing has its own resource and data-handling requirements.
- Access is host-loopback only. Use an SSH tunnel or private VPN, exactly like
  ports 18100/18105; never expose 18120 to the Internet.

## Three-step bring-up

1. **Secrets** — `python3 deploy/init_secrets.py` creates `.env` with mode
   0600 and refuses to overwrite an existing file. It generates the five role
   secrets; the console consumes `CYBERGUARD_API_TOKEN` (gateway bearer token)
   and `CYBERGUARD_APPROVAL_SECRET` (executor approvals) **by reference** and
   maintains its own user/session/API-key database. AgentTeams bridge credentials
   are separate server-side secrets. Fill `CYBERGUARD_GATEWAY_TOKEN` only when the
   gateway issued the console a dedicated token; leave `CYBERGUARD_GUARD_*`
   empty unless the optional model-guard integration is enabled.
2. **Start** — `docker compose up -d --build` (the console image builds from
   `services/operations-console/Dockerfile`, same pinned base image, non-root
   uid 10003, read-only root filesystem). Confirm health:
   `docker compose ps operations-console` reports `healthy` and
   `curl -fsS http://127.0.0.1:18120/healthz` returns 200.
3. **First administrator** — on first start the console initializes its
   database, prints a one-time setup token to the container log
   (`docker compose logs operations-console`) and serves `/setup`; use that
   token to create the administrator account as described in
   [docs/OPERATIONS_CONSOLE.md](OPERATIONS_CONSOLE.md). Complete this step
   before granting operator accounts; cookies are `Secure` by default
   (`CYBERGUARD_COOKIE_SECURE=true`, only disable on an isolated HTTP lab).

## Connect an external Agent

After login, open **连接 Agent** (`/connect`). For a remote deployment, set
`CYBERGUARD_CONSOLE_ORIGIN=https://your-console.example` in `.env` and recreate
the console. Use the canonical origin reachable from the Agent, without a path,
query or credentials. The Compose service passes this setting through. It also
participates in the existing CSRF origin checks, so it must match the public
browser origin. Keep the published port private behind your controlled HTTPS
ingress / VPN; this setting does not publish a service.

Loopback origins may be inferred for local use. Arbitrary Host or forwarded-host
headers are not used to generate remote connection instructions. A localhost
URL points to the Agent's machine, not necessarily the user's browser machine.

The page generates client-specific, secret-free instructions for Skill v0.2.0.
Its default investigation purpose can issue a fixed 30-day
`investigations:read` + `investigations:write` key to an administrator; the separate
legacy read purpose issues only `incidents:read`. Members use appropriately
scoped credentials supplied through an authorized channel. Save secrets in a
private file on the Agent host (Unix: parent 0700, file 0600; Windows: restrict
ACLs). The client reads this file during API requests; it is not a sandbox
boundary against the host Agent.

The default client check is `check --investigations`. Setup verifies access and
does not submit materials automatically. The legacy read flow uses `check` and
`fetch`; an empty list is successful access with no records, not an auth failure.
The browser does not detect local installation or connection completion.
Investigation tasks are creator user/key scoped, with all-task access for an
administrator session within this deployment. This is not multi-tenant hosting;
legacy incident read scope still covers deployment-wide incidents.

Configure the Controller, team Leader and Matrix connection using
[AgentTeams task-service deployment](AGENTTEAMS_TASK_SERVICE.md). Starting base
Compose without that configuration does not validate a reasoning backend.
`/investigations` accepts simple text or multi-source JSON; source/interpretation,
limits and API authorization are documented in [Investigation tasks](INVESTIGATION_TASKS.md).
The SQLite task queue and stage checkpoints persist beyond caller disconnects.
Keep the console volume durable; cancellation stops future stages, not necessarily
an already-running remote inference. Native mode pauses the AgentTeams Project.
The Leader plans, delegates and accepts native Tasks; the Console reads their
status and final artifact. Investigation does not create response actions.

## Upgrade path

```bash
git pull --rebase
python3 deploy/validate_config.py --cyberguard-env .env   # optional sanity gate
docker compose build operations-console
docker compose up -d operations-console    # schema changes are idempotent at startup
curl -fsS http://127.0.0.1:18120/healthz
```

Database schema migrations run automatically at startup and are idempotent
against an existing `console.db`. Take a volume backup (below) before every
upgrade; rollback means redeploying the previous image with the volume intact.

## Backup and recovery

Complete console state = the `cyberguard-console-data` volume **plus** `.env`.
This includes investigation submissions, stage checkpoints and reports.
AgentTeams Worker/controller state and model/Matrix credentials require their
own protected backup; they are not recreated from the console database alone. Backup while the service
runs (no downtime; the export uses SQLite `VACUUM INTO`, never a live copy):

```bash
docker run --rm -v cyberguard_console-data:/data:ro -v "$PWD":/out \
  python:3.12-slim \
  python /out/scripts/console-export.py --db /data/console.db \
  --out /out/console-export.tar.gz --env /out/.env --organization cyberguard
```

(The image tag above is illustrative; any CPython 3.12 image with sqlite3 works.
`scripts/console-export.py` is standard-library only.)

Recovery drill — rehearse these six steps on a lab host before relying on them:

1. Prepare the target host: repository checkout at the same or newer commit;
   restore `.env` from secret storage (or re-run `deploy/init_secrets.py` and
   re-provision the deployer-filled keys).
2. Stop the writer: `docker compose stop operations-console`.
3. Verify the archive: `python scripts/console-export.py --verify
   console-export.tar.gz` (checks every sha256 in `manifest.json`).
4. Restore the database into a fresh volume, owned by container uid 10003:
   ```bash
   docker volume create cyberguard-console-data
   docker run --rm -v cyberguard-console-data:/data -v "$PWD":/out \
     python:3.12-slim python - <<'PY'
   import sqlite3, tarfile
   with tarfile.open("/out/console-export.tar.gz") as tar:
       member = tar.getmember("console.db")
       tar.extract(member, "/tmp")
   src = sqlite3.connect("/tmp/console.db"); src.backup(sqlite3.connect("/data/console.db"))
   PY
   docker run --rm -v cyberguard-console-data:/data alpine chown 10003:10003 /data/console.db
   ```
5. Start and wait for health: `docker compose up -d operations-console`, then
   `docker compose ps` shows `healthy` and `/healthz` returns 200.
6. Verify functionally: log in, review users/audit screens, and confirm live
   wiring to the gateway and executor with one read-only probe action. Inspect
   retained task ownership, materials and checkpoints before resuming dispatcher
   work; verify Worker room mappings and receipt correlation separately.

## Migrating to another machine

1. On the source host, run the backup export above (or `python
   scripts/console-export.py --db <console.db> --out <tar.gz> --env <.env>`).
2. Copy the archive out-of-band and confirm its integrity on the target:
   `python scripts/console-export.py --verify <tar.gz>`.
3. Import by running recovery drill steps 1, 4, 5 and 6 on the target host.
   The archive intentionally contains key *names* only (`env.keys.txt`) —
   secret values must be provisioned on the target from your secret storage;
   the console reuses that host's `CYBERGUARD_API_TOKEN` and
   `CYBERGUARD_APPROVAL_SECRET` references automatically.

## Optional model-guard integration

Set `CYBERGUARD_GUARD_URL=http://model-guard.agentteams.local:8080` (the
compose.model-guard.yaml service alias; the console already shares that
network) and `CYBERGUARD_GUARD_ADMIN_TOKEN` in `.env` — the token must match
the admin token inside the model-guard's private env file, see
[docs/MODEL_GUARD.md](MODEL_GUARD.md). Leave both empty to keep the
integration disabled.

## Hardening summary (as deployed in compose.yaml)

`read_only` root filesystem, `cap_drop: ALL`, `no-new-privileges`, tmpfs
`/tmp` (`noexec,nosuid`, 64 MB), `init: true` for PID-1 signal handling,
non-root uid 10003, loopback-only published port, healthcheck on `/healthz`,
`depends_on` healthy gateway and executor, internal networks
(`cyberguard-readonly`, `cyberguard-execution`) plus the shared
`agentteams-net` attachment required for the loopback port mapping.
