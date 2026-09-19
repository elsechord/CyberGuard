#!/usr/bin/env python3
"""Export the complete operations-console state into one portable tar.gz.

The archive contains:
  console.db      - a consistent snapshot taken with SQLite ``VACUUM INTO``
                    (never a byte copy of the live database or its WAL journal)
  env.keys.txt    - KEY NAMES ONLY from the deployment .env, when reachable;
                    values are deliberately never exported
  manifest.json   - schema version, timestamps, organization and a sha256 for
                    every payload file so the target host can verify integrity

Standard library only (tarfile, sqlite3, hashlib). Run ``--self-test`` for a
built-in end-to-end check that does not touch any real deployment state.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
DB_ENTRY = "console.db"
ENV_KEYS_ENTRY = "env.keys.txt"
MANIFEST_ENTRY = "manifest.json"
TOOL_NAME = "scripts/console-export.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_database(db_path: Path, destination: Path) -> dict[str, object]:
    """Create a consistent copy of ``db_path`` at ``destination`` via VACUUM INTO."""
    if not db_path.is_file():
        raise FileNotFoundError(f"console database not found: {db_path}")
    if destination.exists():
        raise FileExistsError(f"snapshot destination already exists: {destination}")
    # mode=ro guarantees the live database itself can never be modified; the
    # snapshot is produced entirely by SQLite into the new destination file.
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("VACUUM INTO ?", (destination.as_posix(),))
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    return {
        "user_version": int(user_version),
        "sqlite_version": sqlite3.sqlite_version,
        "vacuum_into": True,
    }


def env_key_names(env_path: Path) -> list[str] | None:
    """Return sorted KEY names from an env file; None when the file is absent."""
    if not env_path.is_file():
        return None
    names: set[str] = set()
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if key and key.replace("_", "a").isalnum():
            names.add(key)
    return sorted(names)


def build_manifest(db_snapshot: Path, database_info: dict[str, object],
                   env_keys: list[str] | None, organization: str) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {
        DB_ENTRY: {
            "sha256": sha256_file(db_snapshot),
            "size": db_snapshot.stat().st_size,
        }
    }
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "organization": organization,
        "files": files,
        "database": database_info,
        "env_keys": env_keys,
        "notes": "env.keys.txt lists variable names only; secret values never leave the host.",
    }
    return manifest


def add_entry(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    info = tar.gettarinfo(str(path), arcname=arcname)
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    info.mode = 0o600
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def export_archive(db_path: Path, out_path: Path, env_path: Path | None,
                   organization: str) -> dict[str, object]:
    if out_path.exists():
        raise FileExistsError(f"refusing to overwrite existing archive: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="console-export-") as temp:
        workspace = Path(temp)
        snapshot = workspace / DB_ENTRY
        database_info = snapshot_database(db_path, snapshot)
        env_keys: list[str] | None = None
        env_entry: Path | None = None
        if env_path is not None:
            env_keys = env_key_names(env_path)
            if env_keys is not None:
                env_entry = workspace / ENV_KEYS_ENTRY
                env_entry.write_text("\n".join(env_keys) + "\n", encoding="utf-8")
        manifest = build_manifest(snapshot, database_info, env_keys, organization)
        manifest_entry = workspace / MANIFEST_ENTRY
        manifest_entry.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
        with out_path.open("wb") as raw:
            # mtime=0 and zeroed ownership keep archives byte-comparable across runs.
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.GNU_FORMAT) as tar:
                    add_entry(tar, snapshot, DB_ENTRY)
                    if env_entry is not None:
                        add_entry(tar, env_entry, ENV_KEYS_ENTRY)
                    add_entry(tar, manifest_entry, MANIFEST_ENTRY)
    return manifest


def verify_archive(out_path: Path) -> dict[str, object]:
    """Check every payload file against the embedded manifest hashes."""
    with tarfile.open(out_path, "r:gz") as tar:
        members = {member.name: member for member in tar.getmembers()}
        if MANIFEST_ENTRY not in members:
            raise ValueError(f"archive is missing {MANIFEST_ENTRY}")
        extracted = tar.extractfile(MANIFEST_ENTRY)
        if extracted is None:
            raise ValueError(f"archive entry {MANIFEST_ENTRY} is not a regular file")
        manifest = json.loads(extracted.read().decode("utf-8"))
        if int(manifest.get("schema_version", -1)) != SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema_version: {manifest.get('schema_version')}")
        for name, expected in manifest["files"].items():
            if name not in members:
                raise ValueError(f"manifest lists missing entry: {name}")
            handle = tar.extractfile(name)
            if handle is None:
                raise ValueError(f"archive entry {name} is not a regular file")
            digest = hashlib.sha256(handle.read()).hexdigest()
            if digest != expected["sha256"]:
                raise ValueError(f"sha256 mismatch for {name}: {digest} != {expected['sha256']}")
    return manifest


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="console-export-test-") as temp:
        root = Path(temp)
        db = root / "console.db"
        connection = sqlite3.connect(db.as_posix())
        connection.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);"
            "INSERT INTO users (name) VALUES ('alpha'), ('beta');"
        )
        connection.commit()
        connection.close()
        env = root / ".env"
        env.write_text("# comment\nCYBERGUARD_API_TOKEN=super-secret-value\n"
                       "CYBERGUARD_GATEWAY_TOKEN=\nCYBERGUARD_COOKIE_SECURE=true\n",
                       encoding="utf-8")
        archive = root / "export.tar.gz"
        manifest = export_archive(db, archive, env, organization="self-test")
        assert archive.is_file(), "archive was not written"
        verified = verify_archive(archive)
        assert verified["files"][DB_ENTRY]["sha256"] == manifest["files"][DB_ENTRY]["sha256"]
        assert verified["env_keys"] == ["CYBERGUARD_API_TOKEN", "CYBERGUARD_COOKIE_SECURE",
                                        "CYBERGUARD_GATEWAY_TOKEN"], verified["env_keys"]
        with tarfile.open(archive, "r:gz") as tar:
            names = sorted(member.name for member in tar.getmembers())
            assert names == [DB_ENTRY, ENV_KEYS_ENTRY, MANIFEST_ENTRY], names
            keys_text = tar.extractfile(ENV_KEYS_ENTRY).read().decode("utf-8")
            assert "super-secret-value" not in keys_text, "secret value leaked into export"
            snapshot_bytes = tar.extractfile(DB_ENTRY).read()
        snapshot_path = root / "snapshot.db"
        snapshot_path.write_bytes(snapshot_bytes)
        check = sqlite3.connect(snapshot_path.as_posix())
        rows = check.execute("SELECT name FROM users ORDER BY id").fetchall()
        check.close()
        assert rows == [("alpha",), ("beta",)], rows
    print("console-export self-test passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, help="path to the live console.db to export")
    parser.add_argument("--out", type=Path, help="destination tar.gz (must not exist)")
    parser.add_argument("--env", type=Path, default=None,
                        help="optional .env to document key names from (values never exported)")
    parser.add_argument("--organization", default="cyberguard",
                        help="organization label recorded in manifest.json")
    parser.add_argument("--verify", type=Path, default=None, metavar="ARCHIVE",
                        help="verify an existing archive against its manifest and exit")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in end-to-end test with throwaway data")
    args = parser.parse_args()

    try:
        if args.self_test:
            return self_test()
        if args.verify is not None:
            manifest = verify_archive(args.verify)
            print(f"OK {args.verify} schema_version={manifest['schema_version']} "
                  f"organization={manifest['organization']} "
                  f"files={sorted(manifest['files'])}")
            return 0
        if args.db is None or args.out is None:
            parser.error("export requires --db and --out")
        manifest = export_archive(args.db, args.out, args.env, args.organization)
        print(f"Exported {args.out} ({manifest['files'][DB_ENTRY]['size']} bytes db, "
              f"{len(manifest['files'])} hashed files); "
              f"verify on the target host with --verify.")
        return 0
    except (OSError, ValueError, sqlite3.Error, tarfile.TarError, json.JSONDecodeError) as exc:
        print(f"console-export failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
