"""Passwords, sessions, login lockout and role-based access control.

Security contract implemented here:
- PBKDF2-HMAC-SHA256, 600k iterations, 16-byte random salt per user.
- Constant-time comparisons everywhere; unknown users still pay the full
  key-derivation cost so login timing does not reveal valid usernames.
- Session IDs are 32-byte url-safe tokens; only sha256(id) is persisted.
- Per-account exponential backoff (1/2/4/8 s) and a 15-minute lock after the
  fifth consecutive failure, derived from the append-only auth_event trail.
"""
import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request

from . import audit, config, db

PBKDF2_ITERATIONS = 600_000
LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW_SECONDS = 15 * 60

ROLE_RANK = {"viewer": 0, "analyst": 1, "approver": 2, "admin": 3}
ROLE_SCOPE_GRANTS = {
    "viewer": {"incidents:read", "usage:read"},
    "analyst": {"incidents:read", "incidents:write", "usage:read"},
    "approver": {"incidents:read", "incidents:write", "decisions:write", "usage:read"},
    "admin": {"incidents:read", "incidents:write", "decisions:write",
              "audit:read", "usage:read", "keys:admin", "admin"},
}
ALL_SCOPES = ["incidents:read", "incidents:write", "decisions:write", "audit:read",
              "usage:read", "keys:admin", "admin"]

# A fixed dummy hash so failed lookups cost the same as failed verifications.
_DUMMY_SALT = base64.b64encode(b"\x00" * 16).decode()
_DUMMY_HASH = hashlib.pbkdf2_hmac(
    "sha256", b"cyberguard-timing-equalizer", b"\x00" * 16, PBKDF2_ITERATIONS
)
DUMMY_PASSWORD_HASH = (
    f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_DUMMY_SALT}$"
    f"{base64.b64encode(_DUMMY_HASH).decode()}"
)


def hash_password(password: str) -> str:
    salt = os_urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return (f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
            f"{base64.b64encode(salt).decode()}$"
            f"{base64.b64encode(derived).decode()}")


def os_urandom(size: int) -> bytes:
    return secrets.token_bytes(size)


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations)
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
    except (ValueError, TypeError):
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(derived, expected)


# ---------------------------------------------------------------- users

def user_count() -> int:
    return db.connection().execute("SELECT COUNT(*) AS n FROM user").fetchone()["n"]


def get_user(username: str):
    return db.connection().execute(
        'SELECT * FROM "user" WHERE org_id = ? AND username = ?',
        ("default", username),
    ).fetchone()


def get_user_by_id(user_id: int):
    return db.connection().execute(
        'SELECT * FROM "user" WHERE id = ?', (user_id,)
    ).fetchone()


def list_users() -> list[dict]:
    rows = db.connection().execute(
        'SELECT id, username, role, created_at, disabled FROM "user" ORDER BY id'
    ).fetchall()
    return [dict(row) for row in rows]


def create_user(username: str, password: str, role: str) -> int:
    if role not in ROLE_RANK:
        raise ValueError("unknown role")
    if not 3 <= len(username) <= 64 or username != username.strip():
        raise ValueError("username must be 3-64 characters without surrounding spaces")
    with db.tx() as conn:
        cursor = conn.execute(
            'INSERT INTO "user" (org_id, username, pw_hash, role, created_at) '
            "VALUES ('default', ?, ?, ?, ?)",
            (username, hash_password(password), role, audit.now_iso()),
        )
        return cursor.lastrowid


def set_user_role(user_id: int, role: str) -> None:
    if role not in ROLE_RANK:
        raise ValueError("unknown role")
    with db.tx() as conn:
        conn.execute('UPDATE "user" SET role = ? WHERE id = ?', (role, user_id))
        conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))


def set_user_disabled(user_id: int, disabled: bool) -> None:
    with db.tx() as conn:
        conn.execute('UPDATE "user" SET disabled = ? WHERE id = ?',
                     (1 if disabled else 0, user_id))
        if disabled:
            conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))


def change_password(user_id: int, password: str) -> None:
    with db.tx() as conn:
        conn.execute('UPDATE "user" SET pw_hash = ? WHERE id = ?',
                     (hash_password(password), user_id))


# ---------------------------------------------------------------- sessions

def _sid_hash(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


def create_session(user_id: int) -> tuple[str, str]:
    """Returns (session_id, csrf_token); only the hash of the id is stored."""
    sid = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=config.SESSION_ABSOLUTE_SECONDS)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO session (sid_hash, user_id, csrf_token, created_at, last_seen, "
            "expires_at) VALUES (?,?,?,?,?,?)",
            (_sid_hash(sid), user_id, csrf, now.isoformat(), now.isoformat(),
             expires.isoformat()),
        )
    return sid, csrf


def load_session(sid: str):
    """Valid session row or None; enforces idle and absolute expiry."""
    if not sid:
        return None
    row = db.connection().execute(
        "SELECT * FROM session WHERE sid_hash = ?", (_sid_hash(sid),)
    ).fetchone()
    if row is None:
        return None
    now = datetime.now(UTC)
    expires = datetime.fromisoformat(row["expires_at"])
    last_seen = datetime.fromisoformat(row["last_seen"])
    if expires <= now or (now - last_seen) > timedelta(seconds=config.SESSION_IDLE_SECONDS):
        drop_session(sid)
        return None
    if (now - last_seen) > timedelta(seconds=60):
        with db.tx() as conn:
            conn.execute("UPDATE session SET last_seen = ? WHERE sid_hash = ?",
                         (now.isoformat(), _sid_hash(sid)))
    return row


def drop_session(sid: str) -> None:
    with db.tx() as conn:
        conn.execute("DELETE FROM session WHERE sid_hash = ?", (_sid_hash(sid),))


def rotate_session(old_sid: str, user_id: int) -> tuple[str, str]:
    drop_session(old_sid)
    return create_session(user_id)


def revoke_user_sessions(user_id: int) -> None:
    with db.tx() as conn:
        conn.execute("DELETE FROM session WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------- setup

def ensure_setup_token() -> str | None:
    """Generate the one-time first-boot token when no user exists yet."""
    if user_count() > 0:
        return None
    row = db.connection().execute(
        "SELECT setup_token, setup_used FROM organization WHERE id = 'default'"
    ).fetchone()
    if row and row["setup_token"] and not row["setup_used"]:
        return row["setup_token"]
    token = secrets.token_urlsafe(24)
    with db.tx() as conn:
        conn.execute(
            "UPDATE organization SET setup_token = ?, setup_used = 0 "
            "WHERE id = 'default' AND setup_used = 0", (token,)
        )
    return token


def setup_state() -> dict:
    row = db.connection().execute(
        "SELECT setup_token, setup_used FROM organization WHERE id = 'default'"
    ).fetchone()
    return {
        "open": user_count() == 0 and bool(row) and not row["setup_used"],
        "token": row["setup_token"] if row else None,
    }


def finish_setup() -> None:
    with db.tx() as conn:
        conn.execute(
            "UPDATE organization SET setup_token = NULL, setup_used = 1 "
            "WHERE id = 'default'"
        )


# ---------------------------------------------------------------- login

@dataclass
class LoginOutcome:
    ok: bool
    sid: str | None = None
    csrf: str | None = None
    role: str | None = None
    username: str | None = None
    reason: str | None = None


def attempt_login(username: str, password: str, *, ip: str | None = None,
                  user_agent: str | None = None) -> LoginOutcome:
    username = (username or "").strip()
    if not username:
        return LoginOutcome(ok=False, reason="invalid_credentials")
    failures, last_failure = audit.recent_login_failures(username, LOCKOUT_WINDOW_SECONDS)
    if failures >= LOCKOUT_THRESHOLD and last_failure:
        lock_until = (datetime.fromisoformat(last_failure)
                      + timedelta(seconds=LOCKOUT_WINDOW_SECONDS))
        if datetime.now(UTC) < lock_until:
            audit.record("login", actor=username, result="locked", ip=ip,
                         user_agent=user_agent, reason="account_locked")
            return LoginOutcome(ok=False, reason="account_locked")
    row = get_user(username)
    if row is None:
        # Equalize timing with a real PBKDF2 verification.
        verify_password(password or "", DUMMY_PASSWORD_HASH)
        _sleep_backoff(failures)
        audit.record("login", actor=username, result="failure", ip=ip,
                     user_agent=user_agent, reason="invalid_credentials")
        return LoginOutcome(ok=False, reason="invalid_credentials")
    if row["disabled"]:
        audit.record("login", actor=username, result="failure", ip=ip,
                     user_agent=user_agent, reason="account_disabled")
        return LoginOutcome(ok=False, reason="invalid_credentials")
    if not verify_password(password or "", row["pw_hash"]):
        _sleep_backoff(failures)
        audit.record("login", actor=username, result="failure", ip=ip,
                     user_agent=user_agent, reason="invalid_credentials")
        return LoginOutcome(ok=False, reason="invalid_credentials")
    sid, csrf = create_session(row["id"])
    audit.record("login", actor=username, result="success", ip=ip,
                 user_agent=user_agent, session_id=sid)
    return LoginOutcome(ok=True, sid=sid, csrf=csrf, role=row["role"],
                        username=row["username"])


def _sleep_backoff(prior_failures: int) -> None:
    if prior_failures < 1:
        return
    base = config.login_backoff_base()
    if base <= 0:
        return
    delay = base * min(2 ** (prior_failures - 1), 8)
    time.sleep(delay)


UNIFIED_LOGIN_MESSAGE = "用户名或密码不正确"


# ---------------------------------------------------------------- principals

@dataclass
class Principal:
    kind: str                 # "session" | "api_key"
    user_id: int | None
    username: str             # console user or "api-key:<prefix>"
    role: str                 # viewer/analyst/approver/admin; api keys act as their scopes allow
    scopes: set
    sid: str | None = None    # raw session id (never persisted)
    csrf: str | None = None
    key_id: int | None = None

    def has_scope(self, scope: str) -> bool:
        if "admin" in self.scopes:
            return True
        return scope in self.scopes

    def has_role(self, role: str) -> bool:
        if self.kind == "session":
            return ROLE_RANK.get(self.role, -1) >= ROLE_RANK.get(role, 99)
        return False


def session_principal(sid: str) -> Principal | None:
    row = load_session(sid)
    if row is None:
        return None
    user = get_user_by_id(row["user_id"])
    if user is None or user["disabled"]:
        drop_session(sid)
        return None
    return Principal(kind="session", user_id=user["id"], username=user["username"],
                     role=user["role"], scopes=set(ROLE_SCOPE_GRANTS[user["role"]]),
                     sid=sid, csrf=row["csrf_token"])


def require_session(request: Request) -> Principal:
    principal = session_principal(request.cookies.get(config.cookie_name(), ""))
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required",
                            headers={"WWW-Authenticate": "Cookie"})
    return principal


def require(*roles):
    """Deny-by-default dependency: session must exist and reach the role rank."""
    def dependency(request: Request) -> Principal:
        principal = require_session(request)
        if not any(principal.has_role(role) for role in roles):
            audit.record("permission_denied", actor=principal.username,
                         ip=request.client.host if request.client else None,
                         reason="role_rank", target=",".join(roles))
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal
    return dependency
