"""Read-only bounded Linux collection, without shell commands or environment capture."""
import hashlib
import ipaddress
import os
import re
import shlex
import stat
import sys
import time
from pathlib import Path

from .evidence import make_artifact, make_bundle, utc_now


def _read(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    return raw[:limit], len(raw) > limit


def _reason(exc):
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, FileNotFoundError):
        return "source_missing_or_process_exited"
    return "source_unreadable_or_malformed"


def _unavailable(kind, source, reason):
    return make_artifact(kind, str(source), {"reason": reason, "coverage": {"complete": False}}, status="unavailable")


def _process(path):
    raw, truncated = _read(path / "stat", 16384)
    if truncated:
        raise ValueError("stat too large")
    value = raw.decode("utf-8", errors="replace")
    end = value.rfind(")")
    start = value.find("(")
    fields = value[end + 2:].split()
    if start < 0 or end < start or len(fields) < 20:
        raise ValueError("malformed process stat")
    row = {"pid": int(value[:start].strip()), "comm": value[start + 1:end],
           "ppid": int(fields[1]), "starttime_ticks": int(fields[19]),
           "cpu_ticks": int(fields[11]) + int(fields[12]), "uid": None, "exe": None,
           "uid_status": "unavailable", "exe_status": "unavailable"}
    try:
        status, _ = _read(path / "status", 32768)
        match = re.search(rb"^Uid:\s*(\d+)", status, re.MULTILINE)
        row["uid"] = int(match[1]) if match else None
        row["uid_status"] = "collected" if match else "malformed_status"
    except OSError as exc:
        row["uid_status"] = _reason(exc)
    try:
        row["exe"] = os.readlink(path / "exe")
        row["exe_status"] = "collected"
    except OSError as exc:
        row["exe_status"] = _reason(exc)
    return row


def _processes(proc_root, sample_seconds, maximum):
    try:
        # Bound traversal as well as retained output. Ordering is not a coverage guarantee.
        paths, total_seen = [], 0
        with os.scandir(proc_root) as items:
            for item in items:
                total_seen += 1
                if total_seen > maximum * 4 + 512:
                    break
                if item.name.isdigit() and item.is_dir(follow_symlinks=False):
                    paths.append(Path(item.path))
                    if len(paths) > maximum:
                        break
    except OSError as exc:
        return _unavailable("processes", proc_root, _reason(exc)), []
    limited = len(paths) > maximum or total_seen > maximum * 4 + 512
    paths = sorted(paths[:maximum], key=lambda p: int(p.name))
    initial, failures = {}, 0
    started = time.monotonic()
    for path in paths:
        try:
            initial[path.name] = _process(path)
        except (OSError, ValueError):
            failures += 1
    time.sleep(sample_seconds)
    elapsed = max(time.monotonic() - started, 1e-9)
    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    rows, matched_paths = [], []
    for path in paths:
        if path.name not in initial:
            continue
        first = initial[path.name]
        try:
            current = _process(path)
            if current["starttime_ticks"] != first["starttime_ticks"]:
                failures += 1
                continue
            current["cpu_percent"] = round(max(0, current.pop("cpu_ticks") - first["cpu_ticks"]) / hz / elapsed * 100, 3)
            current["cpu_observation_status"] = "collected"
            rows.append(current)
            matched_paths.append(path)
        except (OSError, ValueError):
            failures += 1
    metadata_missing = sum(row["uid_status"] != "collected" or row["exe_status"] != "collected" for row in rows)
    try:
        boot_raw, boot_truncated = _read(proc_root / "sys/kernel/random/boot_id", 128)
        boot_id = boot_raw.decode("ascii").strip()
        if boot_truncated or not re.fullmatch(r"[0-9a-f-]{36}", boot_id):
            boot_id = None
    except (OSError, UnicodeError):
        boot_id = None
    data = {"processes": rows, "sample_seconds": elapsed, "clock_ticks_per_second": hz, "boot_id": boot_id,
            "coverage": {"complete": bool(rows) and not limited and failures == 0 and metadata_missing == 0,
                         "process_limit": maximum, "metadata_unavailable_processes": metadata_missing,
                         "truncated": limited, "unreadable_or_changed_processes": failures,
                         "cmdline_collected": False, "environ_collected": False,
                         "scope": "visible_process_namespace; not an atomic snapshot"}}
    if not rows:
        data["reason"] = "no_observable_processes"
    return make_artifact("processes", str(proc_root), data,
                         status="collected" if rows else "unavailable"), matched_paths


def _address(value, ipv6):
    address, port = value.split(":")
    raw = bytes.fromhex(address)
    # Linux procfs encodes address words in native byte order.
    if sys.byteorder == "little":
        raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    return str(ipaddress.ip_address(raw)), int(port, 16)


def _network(proc_root, paths):
    owners, denied, fd_limited = {}, 0, False
    for path in paths:
        try:
            with os.scandir(path / "fd") as entries:
                for count, entry in enumerate(entries):
                    if count >= 256:
                        fd_limited = True
                        break
                    try:
                        target = os.readlink(entry.path)
                        if target.startswith("socket:[") and target.endswith("]"):
                            owners.setdefault(target[8:-1], set()).add(int(path.name))
                    except OSError:
                        denied += 1
        except OSError:
            denied += 1
    artifacts = []
    for protocol in ("tcp", "tcp6", "udp", "udp6"):
        source = proc_root / "net" / protocol
        try:
            raw, limited = _read(source, 65536)
            rows, malformed = [], 0
            for line in raw.decode("ascii", errors="replace").splitlines()[1:]:
                if len(rows) >= 512:
                    limited = True
                    break
                try:
                    fields = line.split()
                    local, local_port = _address(fields[1], protocol.endswith("6"))
                    remote, remote_port = _address(fields[2], protocol.endswith("6"))
                    rows.append({"protocol": protocol, "local_address": local, "local_port": local_port,
                                 "remote_address": remote, "remote_port": remote_port,
                                 "state": fields[3], "inode": fields[9],
                                 "owner_pids": sorted(owners.get(fields[9], set()))})
                except (ValueError, IndexError):
                    malformed += 1
            artifacts.append(make_artifact("network", str(source), {"connections": rows,
                "coverage": {"complete": not limited and malformed == 0, "truncated": limited,
                             "malformed_rows": malformed, "ownership_complete": False,
                             "ownership_failures": denied, "fd_limit_reached": fd_limited,
                             "scope": "collector network namespace; ownership is best effort and may race"}}))
        except OSError as exc:
            artifacts.append(_unavailable("network", source, _reason(exc)))
    return artifacts


def _executable(command):
    try:
        tokens = shlex.split(command, posix=True)
        return tokens[0][:4096] if tokens else None
    except ValueError:
        return None


def _persistence(text, path):
    entries, omitted = [], 0
    if path.suffix in (".service", ".timer", ".conf"):
        section = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif line.startswith(("ExecStart=", "ExecStartPre=", "ExecStartPost=")):
                directive, value = line.split("=", 1)
                entries.append({"mechanism": "systemd", "path": str(path), "unit": path.name,
                                "section": section, "directive": directive,
                                "command": _executable(value.lstrip("-+!:@")), "enabled": None,
                                "arguments_omitted": True})
            elif line and not line.startswith(("#", ";")):
                omitted += 1
    else:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if re.match(r"[A-Za-z_][A-Za-z0-9_]*\s*=", stripped):
                omitted += 1
                continue
            parts = stripped.split(None, 1 if stripped.startswith("@") else 5)
            if len(parts) not in (2, 6):
                omitted += 1
                continue
            command = parts[-1]
            if path.name == "crontab" or path.parent.name == "cron.d":
                command = command.split(None, 1)[1] if len(command.split(None, 1)) == 2 else ""
            entries.append({"mechanism": "cron", "path": str(path), "schedule": " ".join(parts[:-1]),
                            "command": _executable(command), "enabled": None, "arguments_omitted": True})
    return entries, omitted


def _redact(text):
    # Best-effort only: arbitrary application secrets cannot be reliably recognized.
    if "PRIVATE KEY-----" in text:
        return "[OMITTED: private-key material]"
    text = re.sub(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=_\-.]+", "[REDACTED AUTH]", text)
    text = re.sub(r"(?i)(\b(?:password|passwd|secret|token|api[_-]?key|authorization)\b\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|\S+)", r"\1[REDACTED]", text)
    return re.sub(r"(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", text)


def _file_artifact(path, kind, limit):
    path = Path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            return _unavailable(kind, path, "not_a_regular_file_or_symlink")
        # O_NOFOLLOW closes the lstat/open symlink race on Linux.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                return _unavailable(kind, path, "not_a_regular_file")
            raw = stream.read(limit + 1)
        limited = len(raw) > limit
        raw = raw[:limit]
        # Drop a partial trailing line rather than interpreting an incomplete command.
        if limited:
            raw = raw[:raw.rfind(b"\n") + 1] if b"\n" in raw else b""
        text = raw.decode("utf-8", errors="replace")
        data = {"coverage": {"complete": not limited, "truncated": limited, "bytes_observed": len(raw),
                            "byte_limit": limit, "scope": "explicitly_selected_file"},
                "sample_sha256": hashlib.sha256(raw).hexdigest(), "file_size": opened.st_size,
                "file_mtime_ns": opened.st_mtime_ns}
        if kind == "persistence":
            data["entries"], data["omitted_directives"] = _persistence(text, path)
            data["coverage"]["parser_scope"] = "executable tokens only; enablement and shell semantics not inferred"
        else:
            if "PRIVATE KEY-----" in text:
                text = "[OMITTED: file contains private-key material]"
            lines = text.splitlines()
            data["events"] = [{"line": i + 1, "text": _redact(line)} for i, line in enumerate(lines[:1024])]
            if len(lines) > 1024:
                data["coverage"].update(complete=False, truncated=True, line_limit=1024)
            data["coverage"]["redaction"] = "best_effort; review before sharing"
        return make_artifact(kind, str(path), data)
    except (OSError, ValueError) as exc:
        return _unavailable(kind, path, _reason(exc))


def collect_linux(*, proc_root="/proc", config_paths=(), log_paths=(), observation_seconds=0.1,
                  max_processes=512, max_file_bytes=65536):
    """Return a bundle; alternate proc roots are explicitly exercise data, not live proof."""
    if not 0.01 <= observation_seconds <= 2 or not 1 <= max_processes <= 512 or not 256 <= max_file_bytes <= 65536:
        raise ValueError("Collection limits outside supported range")
    config_paths, log_paths = list(config_paths), list(log_paths)
    if len(config_paths) + len(log_paths) > 32:
        raise ValueError("At most 32 explicitly selected files")
    proc_root = Path(proc_root)
    alternate = str(proc_root.resolve()) != "/proc" or not sys.platform.startswith("linux")
    process_artifact, process_paths = _processes(proc_root, observation_seconds, max_processes)
    artifacts = [process_artifact, *_network(proc_root, process_paths)]
    if not config_paths:
        artifacts.append(_unavailable("persistence", "explicit_config_scope", "not_requested"))
    artifacts.extend(_file_artifact(p, "persistence", max_file_bytes) for p in config_paths)
    if not log_paths:
        artifacts.append(_unavailable("auth_logs", "explicit_log_scope", "not_requested"))
    artifacts.extend(_file_artifact(p, "auth_logs", max_file_bytes) for p in log_paths)
    return make_bundle(artifacts, provenance={"kind": "exercise" if alternate else "live_collection",
        "collector": "cyberguard-linux-readonly/v1", "proc_root": str(proc_root),
        "collection_finished_at": utc_now(), "source_authentication": "not_attested",
        "collection_scope": {"config_paths": [str(p) for p in config_paths], "log_paths": [str(p) for p in log_paths]},
        "limitations": ["hashes do not authenticate the host or collector", "no command-line or environment capture",
                        "collection is non-atomic and limited to current permissions/namespaces",
                        "missing or empty evidence is not a clean-host finding"]})
