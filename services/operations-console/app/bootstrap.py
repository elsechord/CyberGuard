"""First-boot admin bootstrap CLI.

Usage:
    python -m app.bootstrap admin <username>

The password comes from CYBERGUARD_BOOTSTRAP_ADMIN_PASSWORD when set,
otherwise the CLI prompts interactively. Creating the first admin closes
/setup permanently; a later invocation adds another admin user.
"""
import getpass
import os
import sys

from . import audit, auth, db


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "admin":
        print(__doc__)
        return 2
    username = argv[2].strip()
    password = os.getenv("CYBERGUARD_BOOTSTRAP_ADMIN_PASSWORD") or getpass.getpass(
        f"Password for {username} (min 12 chars): ")
    if len(password) < 12:
        print("password must contain at least 12 characters", file=sys.stderr)
        return 1
    db.init_db()
    first_user = auth.user_count() == 0
    try:
        auth.create_user(username, password, "admin")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if first_user:
        auth.finish_setup()
        print(f"admin '{username}' created; /setup is now permanently closed")
    else:
        print(f"admin '{username}' created")
    audit.record("bootstrap_admin", actor=username, result="success",
                 reason="cli" + (":first_admin" if first_user else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
