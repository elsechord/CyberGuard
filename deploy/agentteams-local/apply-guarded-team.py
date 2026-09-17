#!/usr/bin/env python3
"""Create only fresh Sleeping identities from a reviewed guarded plan.

Run register-guarded-routes.py first. This does not wake Workers, arm the guard,
send tasks, change old identities, or call a model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def execute(*arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError("Deployment operation failed: " + " ".join(arguments[:6]))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    m = json.loads((args.plan / "manifest.json").read_text())
    if not re.fullmatch(r"cg-[a-z0-9][a-z0-9-]{2,34}", m["team"]) or args.out.exists():
        raise SystemExit("Use a fresh plan and new audit file")
    for line in (args.plan / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if Path(name).name != name or hashlib.sha256((args.plan / name).read_bytes()).hexdigest() != digest:
            raise SystemExit("Plan integrity failure")
    old_workers = json.loads(execute("docker", "exec", "agentteams-controller", "agt", "get", "workers", "-o", "json"))["workers"]
    old_teams = json.loads(execute("docker", "exec", "agentteams-controller", "agt", "get", "teams", "-o", "json"))["teams"]
    names = {v["worker"] for v in m["roles"].values()}
    if names.intersection(w["name"] for w in old_workers) or m["team"] in {t["name"] for t in old_teams}:
        raise SystemExit("Identity already exists; refusing to reuse persistent queues")
    health_code = "import json,urllib.request,sys; o=urllib.request.build_opener(urllib.request.ProxyHandler({})); d=json.load(o.open(sys.argv[1],timeout=10)); assert d.get('armed') is False; print('disarmed')"
    execute("docker", "exec", "agentteams-controller", "python3", "-c", health_code, m["guard_url"].removesuffix("/v1") + "/health")
    target = "/tmp/" + m["team"] + "-guarded-plan"
    execute("docker", "cp", str(args.plan), "agentteams-controller:" + target)
    audit = {"run_id": m["run_id"], "team": m["team"], "workers": [], "model_calls_by_script": 0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for role, entry in m["roles"].items():
        name = entry["worker"]
        worker = json.loads((args.plan / (name + ".worker.json")).read_text())
        assert worker["spec"]["state"] == "Sleeping" and worker["spec"]["modelProvider"] == entry["provider"]
        execute("docker", "exec", "agentteams-controller", "agt", "apply", "-f", target + "/" + name + ".worker.json")
        # Existing-worker ZIP update preserves state/modelProvider; package's own
        # manifest model must match this role alias to avoid default-model fallback.
        execute("docker", "exec", "agentteams-controller", "agt", "apply", "worker", "--name", name,
                "--zip", target + "/" + name + ".zip", "--runtime", "qwenpaw")
        current = json.loads(execute("docker", "exec", "agentteams-controller", "agt", "get", "workers", "-o", "json"))["workers"]
        row = next(x for x in current if x["name"] == name)
        if row.get("state") != "Sleeping" or row.get("model") != entry["model_alias"]:
            raise SystemExit("Worker state/model readback mismatch; keep guard disarmed")
        audit["workers"].append({k: row.get(k) for k in ("name", "state", "phase", "model", "runtime")})
        args.out.write_text(json.dumps(audit, indent=2) + "\n")
    execute("docker", "exec", "agentteams-controller", "agt", "apply", "-f", target + "/team.json")
    audit["status"] = "created_sleeping_not_run"
    args.out.write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit))


if __name__ == "__main__":
    main()
