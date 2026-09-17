"""Reproduce real lab account containment without an LLM or production credentials."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from lab_support import LabStack, http


def source_snapshot():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()
    if (ROOT / ".git").exists():
        paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
        metadata = {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
                    "source_kind": "git_worktree"}
    else:
        paths = [p.relative_to(ROOT).as_posix() for name in ("services", "cyberguard_investigation", "scripts", "tests", "scenarios", "knowledge")
                 for p in (ROOT / name).rglob("*") if p.is_file()
                 and "__pycache__" not in p.parts and p.suffix != ".pyc"]
        metadata = {"git_commit": os.getenv("CYBERGUARD_SOURCE_COMMIT") or None, "git_dirty": None,
                    "source_kind": "exported_source", "commit_source": "build_argument_not_attested"}
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in sorted(set(paths)) if name and (ROOT / name).is_file()}
    return {**metadata, "files": hashes}


def run(output):
    run_id = "LAB-" + uuid4().hex
    directory = output / run_id
    directory.mkdir(parents=True, exist_ok=False)
    trace = []
    manifest = {"run_id": run_id, "started_at": datetime.now(UTC).isoformat(),
                "environment": "lab", "execution": "real", "model_mode": "deterministic",
                "agentteams_task": False, "approval_mode": "automated_lab_harness",
                "verification_scope": "point_in_time_lab_access", "status": "failed", "checks": []}

    def check(name, condition, payload=None):
        trace.append({"step": name, "payload": payload})
        manifest["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise RuntimeError("lab check failed: " + name)

    def observe(stack, credential):
        return http(stack.urls["identity"] + "/access?nonce=" + uuid4().hex, stack.tokens[credential])

    try:
        snapshot = source_snapshot()
        (directory / "source-tree.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        manifest.update(git_commit=snapshot["git_commit"], git_dirty=snapshot["git_dirty"])
        with LabStack() as stack:
            status, access = observe(stack, "target")
            check("target_initially_allowed", status == 200 and access["allowed"], access)
            status, action = stack.propose(run_id)
            check("proposal_bound_to_lab_and_run", status == 200 and action.get("run_id") == run_id
                  and action.get("environment_id") == access["environment_id"], action)
            manifest.update(action_id=action["action_id"], environment_id=action["environment_id"])
            path = "/actions/" + action["action_id"]
            status, payload = stack.call(path + "/execute", {})
            check("unapproved_execution_rejected", status == 409, payload)
            status, payload = stack.verify(action)
            check("unexecuted_action_not_verified", status == 200
                  and payload["evidence"]["data"]["verdict"] == "inconclusive", payload)
            status, payload = stack.approve(action)
            check("proposal_bound_approval", status == 200
                  and payload.get("proposal_record_sha256") == action["record_sha256"], payload)
            status, executed = stack.call(path + "/execute", {})
            check("real_disable_applied", status == 200 and executed.get("result") == "applied"
                  and executed.get("verification_status") == "pending", executed)
            status, payload = stack.verify(action)
            check("independent_access_probes_verified", status == 200
                  and payload["evidence"]["data"]["verdict"] == "verified", payload)
            status, payload = stack.verify(action, "unrelated-run")
            check("other_run_not_verified", status == 200
                  and payload["evidence"]["data"]["verdict"] == "inconclusive", payload)
            status, payload = stack.call(path + "/execute", {})
            check("duplicate_execute_returns_original_receipt", status == 200 and payload == executed, payload)
            status, payload = stack.call(path + "/rollback", {})
            check("rollback_requires_approval_credential", status == 403, payload)
            status, payload = stack.call(path + "/rollback", {}, True)
            check("approved_rollback_applied", status == 200 and payload.get("status") == "rolled_back", payload)
            status, payload = observe(stack, "target")
            check("target_access_restored", status == 200 and payload.get("allowed") is True, payload)
            status, payload = observe(stack, "control")
            check("control_access_preserved", status == 200 and payload.get("allowed") is True, payload)
            status, payload = stack.verify(action)
            check("rolled_back_action_not_verified", status == 200
                  and payload["evidence"]["data"]["verdict"] == "inconclusive", payload)
            status, payload = stack.call("/audit/verify")
            check("audit_chain_valid", status == 200 and payload.get("valid") is True, payload)
            status, payload = stack.call(path)
            check("audit_history_available", status == 200, payload)
            (directory / "action-history.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            status, payload = http(stack.urls["gateway"] + "/incidents/CG-LAB-001/runs/" + run_id, stack.tokens["gateway"])
            check("run_export_bound_and_audit_validated", status == 200 and payload.get("run_id") == run_id
                  and payload.get("audit_status") == "valid" and payload.get("evidence_integrity") == "valid"
                  and payload["action_states"][0]["status"] == "rolled_back", payload)
            (directory / "run-export.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        manifest["status"] = "passed"
    except Exception as exc:
        manifest["error"] = str(exc)
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        (directory / "trace.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        files = sorted(directory.glob("*.json"))
        (directory / "SHA256SUMS").write_text("".join(
            hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in files), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "checks": len(manifest["checks"]),
                      "manifest": str(directory / "manifest.json")}, indent=2))
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/lab")
    sys.exit(run(parser.parse_args().output.resolve()))
