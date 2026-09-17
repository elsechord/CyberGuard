#!/usr/bin/env python3
"""Configure only the authorized investigation MCP tools through native API.

Workers must already be awake. This does not approve shell, response tools,
or arbitrary MCP drivers. Existing native policy is exported before changes.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROLES = ("response-planner", "endpoint-forensics", "recovery-verifier")
REMOTE = r'''
import json, urllib.request, sys
from qwenpaw_worker.api import QwenPawApiClient
from qwenpaw.app.mcp.config_service import driver_policy_from_mcp_access_update
from qwenpaw.app.mcp.schemas import MCPAccessPolicy
from qwenpaw.drivers.policy import DriverInvocationContext, evaluate_policy
from qwenpaw.drivers.policy_types import DriverPolicy, PolicyTarget
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
c=QwenPawApiClient("http://127.0.0.1:8088")
mode=sys.argv[1]
result={}
for key,names in {
 "mcp-cyberguard-investigation-readonly":["read_investigation_evidence","read_investigation_reports"],
 "mcp-cyberguard-investigation-report":["submit_investigation_report"],
}.items():
 before=c.get_mcp_policy(key)
 actual_names={t["name"] for t in c.list_mcp_tools(key)}
 if not set(names).issubset(actual_names):
  raise RuntimeError("Expected investigation tools are unavailable")
 desired={"default_effect":"deny", "client_overrides":[], "tool_defaults":[],
   "tool_overrides":[{"tool_name":name,"source_type":"channel","source_value":"matrix",
                      "subject_type":"all","subject_value":"","effect":"allow"} for name in names]}
 after=c.put_mcp_policy(key,desired) if mode == "apply" else None
 checks={}
 if after is not None:
  policy=driver_policy_from_mcp_access_update(DriverPolicy(),MCPAccessPolicy(**after))
  for channel,tool,expected in [("matrix",name,"allow") for name in names]+[("console",names[0],"deny"),("matrix","execute_shell_command","deny")]:
   context=DriverInvocationContext(subject="user:admin",driver_name=key,protocol="mcp",
       target=PolicyTarget(kind="tool",name=tool),request_context={"channel":channel,"user_id":"admin"})
   effect=evaluate_policy(policy,context)
   assert effect==expected, (channel,tool,effect,expected)
   checks[channel+":"+tool]=effect
 result[key]={"before":before,"after":after,"discovered_tools":sorted(actual_names),"native_policy_checks":checks}
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    results = {}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        raise SystemExit("Refusing to overwrite policy audit")
    for mode in ("read", "apply"):
        results[mode] = {}
        for role in ROLES:
            call = subprocess.run(["docker", "exec", "agentteams-worker-" + role,
                                   "/opt/venv/qwenpaw/bin/python", "-c", REMOTE, mode],
                                  text=True, capture_output=True, timeout=60)
            if call.returncode:
                raise SystemExit("Native policy " + mode + " failed for " + role + "; inspect local API availability")
            results[mode][role] = json.loads(call.stdout)
            args.out.write_text(json.dumps(results, indent=2) + "\n")
    print("Verified narrow Matrix investigation policies for all three Workers.")


if __name__ == "__main__":
    main()
