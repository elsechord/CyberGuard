#!/usr/bin/env python3
"""Create a locked-down CyberGuard .env without exposing generated secrets."""

from __future__ import annotations

import argparse
import os
import secrets
import tempfile
from pathlib import Path


SECRET_KEYS = {
    "CYBERGUARD_API_TOKEN",
    "CYBERGUARD_EXECUTOR_TOKEN",
    "CYBERGUARD_APPROVAL_SECRET",
    "CYBERGUARD_AUDIT_HMAC_KEY",
    "CYBERGUARD_AUDIT_READER_TOKEN",
}


def render(template: str) -> str:
    generated = {key: secrets.token_urlsafe(48) for key in SECRET_KEYS}
    output: list[str] = []
    replaced: set[str] = set()
    for raw in template.splitlines():
        key = raw.split("=", 1)[0].strip() if "=" in raw else ""
        if key in generated:
            output.append(f"{key}={generated[key]}")
            replaced.add(key)
        else:
            output.append(raw)
    missing = SECRET_KEYS - replaced
    if missing:
        raise ValueError("template is missing required secret variables: " + ", ".join(sorted(missing)))
    return "\n".join(output) + "\n"


def create(template: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing configuration: {output}")
    content = render(template.read_text(encoding="utf-8-sig"))
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        os.chmod(output, 0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=Path(".env.example"))
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    try:
        create(args.template, args.output)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"Secret initialization failed: {exc}\n")
    print(f"Created {args.output} with mode 0600; secret values were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
