"""Collect bounded read-only evidence; stdout is the evidence bundle, not a verdict."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation.collector import collect_linux


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proc-root", default="/proc", help="Alternate roots are marked as exercise data")
    parser.add_argument("--config", action="append", default=[], help="Explicit systemd unit/drop-in or cron file; no recursive scan")
    parser.add_argument("--log", action="append", default=[], help="Explicit log file; best-effort redaction, review before sharing")
    parser.add_argument("--sample-seconds", type=float, default=0.1)
    parser.add_argument("--max-processes", type=int, default=512)
    parser.add_argument("--output", type=Path, help="New output file (will not overwrite)")
    args = parser.parse_args()
    bundle = collect_linux(proc_root=args.proc_root, config_paths=args.config, log_paths=args.log,
                           observation_seconds=args.sample_seconds, max_processes=args.max_processes)
    value = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
    else:
        print(value, end="")


if __name__ == "__main__":
    main()
