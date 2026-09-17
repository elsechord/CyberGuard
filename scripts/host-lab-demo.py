"""Deterministic Linux response workflow: observe, approve, act, detect recurrence, repair, verify."""
import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from host_lab_support import HostLabStack, http


def run(output, interactive):
    run_id = "HOST-RUN-" + uuid4().hex
    directory = output / run_id
    directory.mkdir(parents=True, exist_ok=False)
    trace = []
    manifest = {"run_id": run_id, "incident_id": "CG-HOST-001", "started_at": datetime.now(UTC).isoformat(),
        "status": "failed", "environment": "lab", "execution": "real", "model_mode": "deterministic",
        "decision_source": "scripted_workflow", "agentteams_task": False,
        "approval_mode": "interactive_operator" if interactive else "automated_lab_harness",
        "scenario_nature": "benign_process_emulation", "checks": [],
        "limitations": ["No real miner or initial intrusion; no attacker organization attribution.",
                        "No evidence of model reasoning quality or multi-agent superiority.",
                        "Bounded observation only; not production incident closure."]}

    def check(name, condition, payload=None):
        trace.append({"step": name, "observed_at": datetime.now(UTC).isoformat(), "payload": payload})
        manifest["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise RuntimeError("host lab check failed: " + name)
        print(name, flush=True)

    def approved_execute(stack, kind, target):
        status, proposal = stack.propose_host(run_id, kind, target)
        check(kind + "_proposal", status == 200, proposal)
        path = "/actions/" + proposal["action_id"] + "/execute"
        status, result = stack.call(path, {})
        check(kind + "_approval_gate", status == 409, result)
        if interactive:
            print(json.dumps({"action_id": proposal["action_id"], "action": kind, "target": target,
                              "reversible": proposal["reversible"], "environment_id": proposal["environment_id"]}, indent=2))
            if input("Type 'approve " + proposal["action_id"] + "' to apply this laboratory action: ").strip() != "approve " + proposal["action_id"]:
                raise RuntimeError("operator did not approve; no action dispatched")
        status, approval = stack.approve(proposal, "local-interactive-operator" if interactive else "automated-lab-harness")
        check(kind + "_approval_bound", status == 200 and approval.get("proposal_record_sha256") == proposal["record_sha256"], approval)
        status, result = stack.call(path, {})
        check(kind + "_applied", status == 200 and result.get("status") == "executed", result)
        return proposal

    try:
        spec = importlib.util.spec_from_file_location("identity_lab_demo", ROOT / "scripts/lab-demo.py")
        source_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(source_module)
        snapshot = source_module.source_snapshot()
        (directory / "source-tree.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        manifest.update(git_commit=snapshot["git_commit"], git_dirty=snapshot["git_dirty"])
        with HostLabStack() as stack:
            status, observation = stack.collect(run_id)
            check("initial_process_and_file_evidence", status == 200, observation)
            before = observation["evidence"]["data"]
            manifest["environment_id"] = before["environment_id"]
            target = next(p for p in before["processes"] if p["role"] == "compute")
            first = approved_execute(stack, "terminate_process", target["target_ref"])
            status, verification = stack.verify(first)
            check("partial_cleanup_is_not_recovery", status == 200 and verification["evidence"]["data"]["verdict"] == "failed", verification)
            status, recollection = stack.collect(run_id)
            check("fresh_evidence_after_failure", status == 200, recollection)
            after = recollection["evidence"]["data"]
            restarted = next(p for p in after["processes"] if p["role"] == "compute")
            check("actual_process_restarted", restarted["target_ref"] != target["target_ref"], restarted)
            repair = approved_execute(stack, "disable_persistence", after["persistence"]["target_ref"])
            status, verification = stack.verify(repair)
            check("bounded_recovery_and_control_progress", status == 200 and verification["evidence"]["data"]["verdict"] == "verified", verification)
            status, exported = http(stack.urls["gateway"] + "/incidents/CG-HOST-001/runs/" + run_id, stack.tokens["gateway"])
            check("same_run_export", status == 200 and exported.get("audit_status") == "valid"
                  and exported.get("evidence_integrity") == "valid"
                  and [a["verification"] for a in exported["action_states"]] == ["failed", "verified"], exported)
            (directory / "run-export.json").write_text(json.dumps(exported, indent=2) + "\n", encoding="utf-8")
        manifest["status"] = "passed"
    except Exception as exc:
        manifest["error"] = str(exc)
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        for name, value in (("manifest.json", manifest), ("trace.json", trace)):
            (directory / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        (directory / "SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
            for p in sorted(directory.glob("*.json"))), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "checks": len(manifest["checks"]),
                      "manifest": str(directory / "manifest.json")}, indent=2))
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/host-lab")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--interactive", action="store_true")
    group.add_argument("--auto-approve", action="store_true", help="Automated test approval; never claim human review")
    args = parser.parse_args()
    sys.exit(run(args.output.resolve(), args.interactive))
