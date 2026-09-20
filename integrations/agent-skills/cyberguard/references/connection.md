# Console connection

Use the configured operations console, not the raw evidence gateway. An operator
stores a scoped `cg_live_...` console API key in a private file. Never paste the
key into chat, print it, or pass it as a command argument.

| Environment variable | Purpose |
|---|---|
| `CYBERGUARD_CONSOLE_URL` | Authorized origin, e.g. `https://cyberguard.internal.example` |
| `CYBERGUARD_SKILL_KEY_FILE` | Private file containing only the console API key |

Version 0.2.0 adds asynchronous investigation submission. Check `--version`
before using new commands. Installation neither connects nor submits materials.

| Command | API | Scope |
|---|---|---|
| `check --investigations` | GET `/api/v1/investigations?limit=1` | `investigations:read` |
| `submit` | POST `/api/v1/investigations` | `investigations:write` |
| `status`, `result` | GET `/api/v1/investigations/{id}` | `investigations:read` |
| `cancel` | POST `/api/v1/investigations/{id}/cancel` | `investigations:write` |
| `check` | GET `/api/v1/incidents?limit=1` | `incidents:read` |
| `fetch` | GET `/api/v1/incidents/{id}` | `incidents:read` |

Read access does not prove write authorization. An empty list is a successful
connection check. A 401 means the key was rejected; 403 means access denied.
Network and 5xx failures do not establish invalid credentials or empty results.
A failed POST may already have been accepted; preserve its idempotency key.
Do not switch to a broader key or unrelated host to evade an access failure.

HTTPS is required except explicitly configured loopback services. The client
refuses redirects, ignores proxy environment variables, and caps payloads at
8 MiB. Configure enterprise CAs through the trust store, never disable TLS.
No client model key, Docker runtime or telemetry is needed. Backend investigation
requires a working deployment and its configured AgentTeams runtime; acceptance
does not establish that the runtime completed successfully. Reading material into
a hosted calling Agent also exposes it to that Agent's processing environment.
