#!/usr/bin/env python3
"""Ensure only this task's Docker bridge defaults published ports to localhost."""
import argparse
import json
import subprocess

NETWORK = "agentteams-net"
ALLOWED = {"agentteams-controller", "agentteams-manager", "agentteams-worker-endpoint-forensics",
           "agentteams-worker-response-planner", "agentteams-worker-recovery-verifier",
           "cyberguard-investigation-local-security-tool-gateway-1",
           "cyberguard-investigation-local-response-executor-1"}


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate-task-network", action="store_true")
    args = parser.parse_args()
    result = docker("network", "inspect", NETWORK, check=False)
    if result.returncode:
        docker("network", "create", "--opt", "com.docker.network.bridge.host_binding_ipv4=127.0.0.1", NETWORK)
        print("Created task-only bridge with localhost default publishing")
        return
    network = json.loads(result.stdout)[0]
    if network.get("Options", {}).get("com.docker.network.bridge.host_binding_ipv4") == "127.0.0.1":
        print("Task bridge already defaults published ports to localhost")
        return
    if not args.migrate_task_network:
        raise SystemExit("Existing bridge lacks localhost default; explicit task-only migration required")
    containers = []
    for cid in docker("ps", "-aq").stdout.split():
        data = json.loads(docker("inspect", cid).stdout)[0]
        connection = data["NetworkSettings"]["Networks"].get(NETWORK)
        if connection is None:
            continue
        name = data["Name"].lstrip("/")
        if name not in ALLOWED:
            raise SystemExit("Unrelated container attached; refusing network migration")
        if data["State"].get("Paused"):
            raise SystemExit("Paused container present; refusing migration")
        containers.append({"name": name, "running": data["State"]["Running"],
                           "aliases": connection.get("Aliases") or []})
    # All targets checked before the first mutation. No volumes/images are removed.
    for item in containers:
        if item["running"]:
            docker("stop", item["name"])
    for item in containers:
        docker("network", "disconnect", "--force", NETWORK, item["name"])
    docker("network", "rm", NETWORK)
    docker("network", "create", "--opt", "com.docker.network.bridge.host_binding_ipv4=127.0.0.1", NETWORK)
    for item in containers:
        command = ["network", "connect"]
        for alias in item["aliases"]:
            command.extend(["--alias", alias])
        docker(*command, NETWORK, item["name"])
    for item in containers:
        if item["running"]:
            docker("start", item["name"])
    print(json.dumps({"network": NETWORK, "default_bind": "127.0.0.1", "migrated_task_containers": len(containers)}))


if __name__ == "__main__":
    main()
