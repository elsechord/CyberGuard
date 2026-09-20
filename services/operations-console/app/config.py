"""Environment-driven configuration for the operations console.

Every value is read lazily so tests can adjust the process environment before
importing the application. Secrets are never logged anywhere in this package.
"""
import os


def db_path() -> str:
    return os.getenv("CYBERGUARD_CONSOLE_DB", "/data/console.db")


def gateway_url() -> str:
    return os.getenv("CYBERGUARD_GATEWAY_URL", "").rstrip("/")


def gateway_token() -> str:
    return os.getenv("CYBERGUARD_GATEWAY_TOKEN", "")


def executor_url() -> str:
    return os.getenv("CYBERGUARD_EXECUTOR_URL", "").rstrip("/")


def executor_token() -> str:
    return os.getenv("CYBERGUARD_EXECUTOR_TOKEN", "")


def executor_approval_secret() -> str:
    return os.getenv("CYBERGUARD_EXECUTOR_APPROVAL_SECRET", "")


def guard_url() -> str:
    return os.getenv("CYBERGUARD_GUARD_URL", "").rstrip("/")


def guard_admin_token() -> str:
    return os.getenv("CYBERGUARD_GUARD_ADMIN_TOKEN", "")


def cookie_secure() -> bool:
    return os.getenv("CYBERGUARD_COOKIE_SECURE", "true").strip().lower() not in {
        "0", "false", "no", "off"
    }


def cookie_name() -> str:
    # The __Host- prefix requires the Secure attribute; plain HTTP smoke runs
    # fall back to an unprefixed name with identical semantics.
    return "__Host-cgsession" if cookie_secure() else "cgsession"


def cookie_samesite() -> str:
    # ModelScope embeds the Console on a different site. Cross-site cookies
    # require Secure and SameSite=None; standalone deployments retain Lax.
    if cookie_secure() and os.getenv("CYBERGUARD_MODELSCOPE_EMBED", "").strip() == "1":
        return "none"
    return "lax"


def upstream_timeout() -> float:
    try:
        return float(os.getenv("CYBERGUARD_UPSTREAM_TIMEOUT", "5"))
    except ValueError:
        return 5.0


def login_backoff_base() -> float:
    """Seconds base for exponential login backoff (tests set this to 0)."""
    try:
        return float(os.getenv("CYBERGUARD_LOGIN_BACKOFF_BASE", "1"))
    except ValueError:
        return 1.0


def external_origin() -> str:
    """Optional canonical external origin (scheme://host[:port]) for CSRF checks."""
    return os.getenv("CYBERGUARD_CONSOLE_ORIGIN", "").rstrip("/")


SESSION_IDLE_SECONDS = 30 * 60
SESSION_ABSOLUTE_SECONDS = 8 * 3600
IDEMPOTENCY_TTL_SECONDS = 24 * 3600
KEY_PREFIX = "cg_live_"
