# Operations console

The operations console (`services/operations-console`) is the multi-user operator surface for a CyberGuard deployment: authenticated humans and API keys view the incident queue, drive gateway workflow states, approve or deny executor response proposals with a mandatory closing classification, inspect the model-admission budget ledger and export the console's own authentication audit trail. It turns the single-token demo consoles into a deployable product surface while the underlying services stay untouched.

The console is a FastAPI service listening on internal port 8080; the Compose wiring maps it to `127.0.0.1:18120` on the host. It keeps all state in one SQLite database (`console.db`), holds no long-lived secrets other than password/key digests, and performs every cross-service call against the existing gateway/executor/guard HTTP APIs.

## Deployment

The console container needs a writable volume for its database plus the following environment (Compose service `operations-console`):

| Variable | Purpose | Default |
| --- | --- | --- |
| `CYBERGUARD_CONSOLE_DB` | SQLite path | `/data/console.db` |
| `CYBERGUARD_GATEWAY_URL` | security-tool-gateway origin (e.g. `http://security-gateway:8080`) | empty → incidents/decisions degrade |
| `CYBERGUARD_GATEWAY_TOKEN` | gateway bearer token (`CYBERGUARD_API_TOKEN`) | empty |
| `CYBERGUARD_EXECUTOR_URL` | response-executor origin | empty → approvals degrade |
| `CYBERGUARD_EXECUTOR_TOKEN` | executor bearer token (`CYBERGUARD_EXECUTOR_TOKEN`) | empty |
| `CYBERGUARD_EXECUTOR_APPROVAL_SECRET` | human-approval secret (`X-Approval-Secret` on `/actions/approve`) | empty |
| `CYBERGUARD_GUARD_URL` | model-guard origin (optional) | empty → ledger shows "unavailable" |
| `CYBERGUARD_GUARD_ADMIN_TOKEN` | guard admin token (optional) | empty |
| `CYBERGUARD_COOKIE_SECURE` | `Secure` cookie attribute; keep `true` behind HTTPS | `true` |
| `CYBERGUARD_CONSOLE_ORIGIN` | canonical external origin for CSRF checks when behind a proxy | empty |
| `CYBERGUARD_UPSTREAM_TIMEOUT` | outbound call timeout seconds | `5` |
| `CYBERGUARD_LOGIN_BACKOFF_BASE` | exponential-backoff base seconds (tests set `0`) | `1` |

Every missing optional dependency degrades in place: the overview shows zeros with an explicit banner, `/ledger` explains that the guard is unreachable, and proxied API calls return the standard error envelope with a 502/503 semantic code instead of crashing.

## First boot

With an empty database the console issues a one-time setup token, prints the full token to the container log (`CYBERGUARD SETUP TOKEN (first boot only): …`) and opens `/setup`. The setup page shows only a masked preview (`abcd••••wxyz`); the operator pastes the complete token from the log to prove control of the deployment, then creates the first admin. Creating the admin — via `/setup` or via the CLI — permanently closes `/setup` and wipes the token:

```
docker compose exec operations-console python -m app.bootstrap admin <username>
```

The CLI reads `CYBERGUARD_BOOTSTRAP_ADMIN_PASSWORD` from the environment or prompts interactively. Default credentials are never stored in plaintext: only `pbkdf2_sha256$600000$<salt>$<digest>` rows.

## Roles

Roles are cumulative (deny-by-default; every route declares its floor):

| Capability | viewer | analyst | approver | admin |
| --- | --- | --- | --- | --- |
| All read-only pages and GET APIs | ✓ | ✓ | ✓ | ✓ |
| Comments, non-approval workflow transitions | — | ✓ | ✓ | ✓ |
| Approve/deny proposals (classification + comment required) | — | — | ✓ | ✓ |
| Member management, role assignment, API keys, audit export | — | — | — | ✓ |

Unauthenticated requests receive `401` (pages: redirect to `/login`); insufficient role or scope receives `403`. Both outcomes are recorded in `auth_event`. Changing a member's role or disabling them invalidates all of their sessions immediately.

## API v1

All `/api/v1` endpoints accept either the session cookie (for same-origin JSON fetches, which must send `Origin`/`Referer` plus `X-Requested-With`) or an API key via `Authorization: Bearer cg_live_…` (CSRF-exempt). List responses share one envelope — `{"data": [...], "has_more": bool, "next_cursor": "<last id>" | null}` — with `limit` (default 20, max 100) and `cursor` (the id of the last consumed row). Errors share `{"error": {"type": ..., "code": ..., "message": ...}}` with `type` ∈ `invalid_request_error | authentication_error | permission_error | idempotency_error | api_error`.

| Endpoint | Scope | Notes |
| --- | --- | --- |
| `GET /api/v1/incidents` | `incidents:read` | Proxied gateway summaries; `status=` filter |
| `GET /api/v1/incidents/{id}` | `incidents:read` | Evidence/actions/workflow detail |
| `POST /api/v1/incidents/{id}/workflow` | `incidents:write` | Body `{state, message, session_id?}`; invalid transitions pass the gateway 409 through |
| `GET /api/v1/proposals` | `incidents:read` | Pending executor proposals derived from gateway action audits; `status=` filter |
| `POST /api/v1/proposals/{id}/decision` | `decisions:write` | Body `{action: approve\|deny, classification, comment}`; approve proxies executor `/actions/approve` with the approval secret; every decision is recorded locally |
| `GET /api/v1/audit-events` | `audit:read` | `auth_event` stream |
| `GET/POST /api/v1/keys`, `DELETE /api/v1/keys/{id}` | `keys:admin` | Create returns the plaintext once |
| `GET /api/v1/usage/summary` | `usage:read` | Guard ledger aggregation or `{"available": false}` |

Scopes: `incidents:read`, `incidents:write`, `decisions:write`, `audit:read`, `usage:read`, `keys:admin`, `admin` (implies all). Session users act with their role's scope grants; API keys act with exactly their granted scopes. Write endpoints accept an `Idempotency-Key` header (≤ 255 chars, retained 24 h): identical replays return the original response with `Idempotent-Replay: true`; a reused key with different parameters returns `idempotency_error` (409).

Closing classifications for decisions: `approved_true_positive`, `approved_with_caution`, `denied_false_positive_logic`, `denied_false_positive_data`, `undetermined`. A non-empty comment (≥ 4 characters) is mandatory; the API rejects a missing/unknown classification with 422.

Example — create a key through the UI, then drive an approval:

```bash
# 1. List pending proposals with an API key
curl -s -H "Authorization: Bearer cg_live_…" \
  http://127.0.0.1:18120/api/v1/proposals | jq .

# 2. Approve with a classification, idempotently
curl -s -X POST http://127.0.0.1:18120/api/v1/proposals/ACT-9c2f11d04a8e/decision \
  -H "Authorization: Bearer cg_live_…" \
  -H "Idempotency-Key: approve-act-9c2f-0001" \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","classification":"approved_true_positive",
       "comment":"Independent evidence confirms compromise"}' | jq .

# 3. Page through audit events
curl -s -H "Authorization: Bearer cg_live_…" \
  "http://127.0.0.1:18120/api/v1/audit-events?limit=20" | jq .
```

## Security design

- **Passwords**: PBKDF2-HMAC-SHA256, 600,000 iterations, 16-byte random salt, constant-time comparison (`hmac.compare_digest`). Unknown usernames still pay a full dummy derivation so response timing does not enumerate accounts (OWASP ASVS 2.4).
- **Sessions**: 32-byte url-safe IDs in a `__Host-cgsession` cookie (`HttpOnly; Secure; SameSite=Lax; Path=/`); only `sha256(id)` is persisted. Idle timeout 30 minutes, absolute lifetime 8 hours; IDs rotate on login/logout/privilege change and logout deletes the row. `CYBERGUARD_COOKIE_SECURE=false` (smoke runs only) switches to the unprefixed `cgsession` name because browsers reject `__Host-` without `Secure`.
- **Login protection**: per-account failure counting from the append-only `auth_event` trail, exponential backoff 1/2/4/8 s after consecutive failures, a 15-minute lock at the fifth, and a single unified error message (OWASP ASVS 2.5 / cheat-sheet guidance).
- **CSRF**: session forms carry a per-session synchronizer token; session JSON calls require same-origin `Origin`/`Referer` plus `X-Requested-With`; API-key calls are exempt. The pre-session `/login` and `/setup` forms use short-lived HMAC-signed tokens (OWASP CSRF cheat sheet).
- **Headers** on every response: `Content-Security-Policy default-src 'self' …; frame-ancestors 'none'; base-uri 'self'`, `X-Content-Type-Options`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cache-Control: no-store`. All templating is Jinja2 autoescape; no inline script/style exists.
- **API keys**: `cg_live_` + 32-byte tokens, `sha256` at rest, 14-character display prefix, optional expiry, revocation; plaintext is shown exactly once. `last_used_at` updates are throttled.
- **Audit**: `auth_event` is append-only (logins, lockouts, denials, decisions, key lifecycle, exports) and exportable as CSV by admins. Session rows record only hashes.
- **Outbound**: stdlib `urllib` with proxies disabled, redirects refused, 5 s timeout, 4 MiB response cap — mirroring `services/response-executor/app/lab.py`; blocking calls run in the request threadpool; tokens are never logged.

Threat-model notes: the console assumes a trusted internal network segment between containers (as the rest of the deployment does) and does not defend a compromised gateway/executor. Rate limiting exists only for login; consider a reverse proxy for generic rate limiting at scale. The audit trail is integrity-witnessed only by SQLite transactions — it is not an HMAC chain like the executor ledger; export it (`/audit/export.csv`) if tamper evidence is required. Cookie transport must be HTTPS in production (`CYBERGUARD_COOKIE_SECURE=true` is the default); the `__Host-` prefix additionally pins `Path=/` and no domain.

## Backup

`console.db` is the complete console state: users (password digests), sessions, API keys (digests), comments, decisions and the audit trail. Back up the file (and its `-wal`/`-shm` siblings while running) on the console's data volume; the upstream gateway/executor stores remain the system of record for evidence and actions. Losing the database loses console-local accounts, comments and decision records — recoverable only from backups.
