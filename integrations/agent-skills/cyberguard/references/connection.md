# Connect to an existing CyberGuard deployment

The API is the **operations console**, not the raw evidence gateway. The operator
creates a console API key limited to `incidents:read` and stores it in a private
file in the Agent's execution environment. Do not ask the user to paste the key
into chat, and do not print the file. The URL and the file path are configuration;
the key itself is not a command argument.

Set these environment variables through the host's secret/configuration mechanism:

| Name | Value |
|---|---|
| `CYBERGUARD_CONSOLE_URL` | The authorized console origin, e.g. `https://cyberguard.internal.example` |
| `CYBERGUARD_SKILL_KEY_FILE` | Absolute path to a file containing only the console `cg_live_...` key |

HTTPS is required except for an explicitly configured localhost/loopback service.
The script rejects credentials in URLs, redirects and oversized responses, and
does not inherit HTTP proxy environment variables. For an enterprise CA, configure
the Python/system trust store rather than disabling certificate verification.

`fetch CG-123 --out incident.json` calls exactly:

```text
GET /api/v1/incidents/CG-123
Authorization: Bearer <read from private key file>
```

Expected response: `{ "data": { "summary": { "incident_id": "CG-123" },
"evidence": [...], "actions": [...], "workflow": ... } }`.
The offline `inspect` command accepts this wrapper or the unwrapped gateway
incident response. It does not accept arbitrary PDF/CSV files or the separate
investigation-bundle format; those need their own ingestion/export path.

401 means the key was not accepted. 403 means access was denied. 404 means the
incident was not found. Connection/5xx errors require an operator to check the
deployment. Do not switch to a broader key, retry against unrelated hosts, or
generate a successful-looking result when a read failed.

No registration, model provider key, approval credential or Docker runtime is
needed on the Agent side. A live fetch does require an existing working console
and incident data. The console's keys currently cover the deployment's incidents;
do not represent this as per-incident or per-tenant isolation.

The helper has no external model calls and no telemetry. Reading results into a
hosted Agent exposes them to that Agent's processing environment; follow the
customer's existing data handling policy. Offline mode refers to the helper's
network behavior, not a guarantee that the caller's model runs locally.
