#!/usr/bin/env python3
"""Trim NEW QwenPaw identities while the model guard is disarmed.

No Worker is started here. It refuses legacy identities and writes a before audit
before changes. This is native tool configuration, not a hostile-code sandbox.
"""
import argparse
import json
from pathlib import Path
import subprocess

REMOTE = r'''
import json,sys,urllib.request
from qwenpaw_worker.api import QwenPawApiClient
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
mode,guard_url=sys.argv[1:]
with urllib.request.urlopen(guard_url.removesuffix("/v1")+"/health",timeout=10) as r: health=json.load(r)
assert health.get("armed") is False,"Guard must be disarmed"
c=QwenPawApiClient("http://127.0.0.1:8088",timeout=30)
profile=c._request("GET","/api/agents/default")
clients=c.list_mcp()
snapshot={"builtin_tools":{k:v["enabled"] for k,v in profile["tools"]["builtin_tools"].items()},
          "mcp_clients":{i["key"]:i["enabled"] for i in clients},
          "running":{k:profile["running"].get(k) for k in ("max_iters","llm_retry_enabled","llm_max_retries","llm_max_concurrent")}}
allowed={"mcp-cyberguard-investigation-readonly":["read_investigation_evidence","read_investigation_reports"],
         "mcp-cyberguard-investigation-report":["submit_investigation_report"]}
assert set(allowed).issubset(snapshot["mcp_clients"]),"Investigation MCP clients missing"
if mode=="apply":
 before_config=json.dumps({"tools":profile["tools"],"running":profile["running"]},sort_keys=True)
 for tc in profile["tools"]["builtin_tools"].values():tc["enabled"]=False
 running=profile["running"]
 running.update({"max_iters":4,"llm_retry_enabled":False,"llm_max_retries":1,"llm_max_concurrent":1})
 running["auto_title_config"]["enabled"]=False
 running["reme_light_memory_config"].update({"dream_cron_enabled":False,"inbox_push_enabled":False,"summarize_when_compact":False})
 running["light_context_config"]["scroll_config"]["summarize_unheadlined_evictions"]=False
 # Scroll always injects recall_history outside builtin_tools. For a fresh
 # short bounded stage, native context removes that otherwise unlisted tool.
 running["light_context_config"]["strategy"]="native"
 running["light_context_config"]["context_compact_config"]["enabled"]=False
 desired={"tools":profile["tools"],"running":running}
 if json.dumps(desired,sort_keys=True)!=before_config:c.configure_agent("default",desired)
 for client in clients:
  key=client["key"]
  if key not in allowed:
   if client["enabled"]:c._request("PATCH","/api/mcp/toggle/"+key)
   continue
  if not client["enabled"]:raise RuntimeError("Required MCP client disabled; inspect provisioning")
  names=allowed[key]
  current=c._request("GET","/api/mcp/"+key)
  if sorted(current.get("tools") or [])!=sorted(names):c._request("PUT","/api/mcp/tools/"+key,{"tools":names})
  # Exact tools only. Do not rely on missing/inconsistent Matrix context fields.
  c.put_mcp_policy(key,{"default_effect":"deny","client_overrides":[],"tool_overrides":[],
      "tool_defaults":[{"tool_name":name,"effect":"allow"} for name in names]})
 after_profile=c._request("GET","/api/agents/default")
 after_clients=c.list_mcp()
 assert not any(t["enabled"] for t in after_profile["tools"]["builtin_tools"].values()),"Built-in tools still enabled"
 assert {i["key"] for i in after_clients if i["enabled"]}==set(allowed),"Unexpected MCP client enabled"
 actual=after_profile["running"]
 expected={"max_iters":4,"llm_retry_enabled":False,"llm_max_retries":1,"llm_max_concurrent":1}
 assert all(actual.get(k)==v for k,v in expected.items()),"Running limits readback mismatch"
 assert actual["auto_title_config"]["enabled"] is False,"Auto title still enabled"
 assert all(actual["reme_light_memory_config"][k] is False for k in ("dream_cron_enabled","inbox_push_enabled","summarize_when_compact")),"Memory model features enabled"
 assert actual["light_context_config"]["strategy"]=="native","Unexpected context strategy"
 assert actual["light_context_config"]["context_compact_config"]["enabled"] is False,"Context summarization enabled"
 assert actual["light_context_config"]["scroll_config"]["summarize_unheadlined_evictions"] is False,"Scroll summaries enabled"
 policies={}
 for key,names in allowed.items():
  info=c._request("GET","/api/mcp/"+key)
  assert sorted(info["tools"])==sorted(names),"MCP tool whitelist readback mismatch"
  policy=c._request("GET","/api/mcp/policy/"+key)
  assert policy["default_effect"]=="deny" and not policy["client_overrides"] and not policy["tool_overrides"],"Unexpected MCP policy override"
  assert sorted((x["tool_name"],x["effect"]) for x in policy["tool_defaults"])==sorted((name,"allow") for name in names),"Exact tool policy mismatch"
  assert policy.get("unmanaged_rules_count",0)==0,"Unmanaged policy rules present"
  policies[key]={"tools":info["tools"],"policy":policy}
 snapshot["verified"]={"builtin_enabled":[],"mcp_enabled":sorted(allowed),
     "running":{k:actual[k] for k in expected},"auto_title_enabled":actual["auto_title_config"]["enabled"],
     "context_strategy":actual["light_context_config"]["strategy"],"exact_policies":policies,
     "tool_policy_scope":"exact_tools_all_request_contexts"}
print(json.dumps(snapshot))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.plan / "manifest.json").read_text())
    if not manifest["team"].startswith("cg-") or args.out.exists():
        raise SystemExit("Need a fresh cg-* plan and new audit file")
    for role, entry in manifest["roles"].items():
        if entry["worker"] != manifest["team"] + "-" + role:
            raise SystemExit("Unexpected Worker identity")
    audit = {}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for mode in ("read", "apply"):
        audit[mode] = {}
        for role, entry in manifest["roles"].items():
            result = subprocess.run(["docker", "exec", "agentteams-worker-" + entry["worker"],
                "/opt/venv/qwenpaw/bin/python", "-c", REMOTE, mode, manifest["guard_url"]],
                text=True, capture_output=True, timeout=90)
            if result.returncode:
                print('\n'.join(line for line in result.stderr.splitlines() if line.startswith(('AssertionError:', 'qwenpaw_worker.api.QwenPawApiError:'))))
                raise SystemExit(f"Native runtime {mode} failed for {role}; keep guard disarmed and inspect local API")
            audit[mode][role] = json.loads(result.stdout)
            args.out.write_text(json.dumps(audit, indent=2) + "\n")
    print("All built-ins and non-investigation MCP clients disabled; no model call made by this script.")


if __name__ == "__main__":
    main()
