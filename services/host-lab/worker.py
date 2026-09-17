"""Benign workload: bounded hashing and a functional heartbeat, never mining."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heartbeat", type=Path, required=True)
    parser.add_argument("--role", choices=("compute", "control"), required=True)
    args = parser.parse_args()
    sequence = 0
    while True:
        # Deliberately small, identical work for both roles. CPU use alone cannot
        # distinguish the target from the legitimate control workload.
        value = hashlib.sha256(str(sequence).encode()).hexdigest()
        pending = args.heartbeat.with_suffix(".pending")
        pending.write_text(json.dumps({"pid": os.getpid(), "sequence": sequence,
                                      "value": value}), encoding="utf-8")
        pending.replace(args.heartbeat)
        sequence += 1
        time.sleep(0.1)
