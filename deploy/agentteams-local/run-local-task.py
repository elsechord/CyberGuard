#!/usr/bin/env python3
"""Bound a real Matrix/AgentTeams integration run by time and observed usage.

This is an external monitor, not strict provider token enforcement. In-flight
calls may exceed thresholds; record their final counters after all Workers stop.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
ROLES = ["response-planner", "endpoint-forensics", "recovery-verifier"]


def usage(out, label):
    result = {}
    for role in ROLES:
        path = out / f"{label}-{role}-usage.json"
        command = ["docker", "cp", f"agentteams-worker-{role}:/root/agentteams-fs/agents/{role}/.qwenpaw/token_usage.json", str(path)]
        proc = subprocess.run(command, capture_output=True, timeout=20)
        if proc.returncode:
            if b"Could not find the file" in proc.stderr:
                result[role] = {"prompt_tokens": 0, "completion_tokens": 0, "call_count": 0,
                                "source_status": "usage_file_not_yet_created_assumed_zero"}
            else:
                result[role] = {"unavailable": True}
            continue
        try:
            data = json.loads(path.read_text())
            result[role] = {key: sum(model.get(key, 0) for day in data.values() for model in day.values())
                            for key in ("prompt_tokens", "completion_tokens", "call_count")}
            result[role]["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            if not data:
                result[role]["source_status"] = "native_empty_usage_assumed_zero_not_complete_attestation"
        except (ValueError, TypeError, AttributeError):
            result[role] = {"unavailable": True}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--max-input", type=int, default=150000)
    parser.add_argument("--max-output", type=int, default=16000)
    args = parser.parse_args()
    if args.seconds < 1 or args.seconds > 600:
        raise SystemExit("Observation window must be 1..600 seconds")
    args.out.mkdir(parents=True, exist_ok=False)
    baseline = usage(args.out, "baseline")
    if any(v.get("unavailable") for v in baseline.values()):
        raise SystemExit("Missing native baseline usage; refusing unmonitored run")
    started = time.monotonic()
    capture = None
    reason = "error"
    ticks = []
    try:
        for role in ROLES:
            subprocess.run(["docker", "exec", "agentteams-controller", "agt", "worker", "wake", "--name", role], check=True, capture_output=True, timeout=45)
        log = (args.out / "capture.log").open("w")
        capture = subprocess.Popen([sys.executable, "-u", str(ROOT / "deploy/agentteams-local/capture-local-task.py"),
                                    "--env-file", "/root/.config/cyberguard/agentteams-local.env",
                                    "--cyberguard-env", "/root/.config/cyberguard/services.env",
                                    "--task-file", str(args.task), "--out", str(args.out / "matrix"),
                                    "--room-name", "cyberguard-investigation", "--incident-id", args.run_id,
                                    "--timeout", str(args.seconds)], stdout=log, stderr=log)
        print("Native capture started; monitoring actual Worker usage.", flush=True)
        while time.monotonic() - started < args.seconds:
            current = usage(args.out, "latest")
            if any(v.get("unavailable") for v in current.values()):
                reason = "usage_unavailable"
                break
            delta = {key: sum(current[r][key] - baseline[r][key] for r in ROLES)
                     for key in ("prompt_tokens", "completion_tokens", "call_count")}
            tick = {"elapsed_seconds": round(time.monotonic() - started, 1), **delta}
            ticks.append(tick)
            (args.out / "usage-monitor.json").write_text(json.dumps(ticks, indent=2))
            print(json.dumps(tick), flush=True)
            if delta["prompt_tokens"] >= args.max_input or delta["completion_tokens"] >= args.max_output:
                reason = "observed_token_limit"
                break
            if capture.poll() is not None:
                reason = "capture_ended"
                break
            time.sleep(min(15, max(0, args.seconds - (time.monotonic() - started))))
        else:
            reason = "time_limit"
    finally:
        # Sleep the leader first to prevent further delegation while stopping peers.
        stop_results = {}
        for role in ROLES:
            try:
                stopped = subprocess.run(["docker", "exec", "agentteams-controller", "agt", "worker", "sleep", "--name", role], capture_output=True, timeout=45)
                stop_results[role] = stopped.returncode == 0
            except subprocess.TimeoutExpired:
                stop_results[role] = False
        if capture is not None and capture.poll() is None:
            capture.terminate()
            capture.wait(timeout=10)
        final = usage(args.out, "final")
        summary = {"run_id": args.run_id, "finished_at": datetime.now(timezone.utc).isoformat(),
                   "stop_reason": reason, "baseline": baseline, "final": final, "worker_sleep_commands": stop_results,
                   "token_limit_enforcement": "external_monitor_not_hard_limit",
                   "in_flight_overshoot_possible": True, "comparison_scope": "integration_only",
                   "elapsed_seconds": round(time.monotonic() - started, 1)}
        if not any(v.get("unavailable") for v in final.values()):
            summary["observed_usage_delta"] = {key: sum(final[r][key] - baseline[r][key] for r in ROLES)
                                               for key in ("prompt_tokens", "completion_tokens", "call_count")}
        (args.out / "monitor-result.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
