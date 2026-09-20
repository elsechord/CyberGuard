"""Disable runtime tools/model background work on only the fresh console Workers."""
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT.parent / "output/console-agentteams-validation-001"
PRIVATE = Path("/root/.config/cyberguard/console-validation-001")
REMOTE = r'''
import json,os,urllib.request,sys
from qwenpaw_worker.api import QwenPawApiClient
p=json.load(sys.stdin)
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
with urllib.request.urlopen(p['guard_url'].removesuffix('/v1')+'/health') as r:
 assert json.load(r)['armed'] is False
c=QwenPawApiClient('http://127.0.0.1:8088',timeout=45)
profile=c._request('GET','/api/agents/default')
for tc in profile['tools']['builtin_tools'].values():tc['enabled']=False
running=profile['running']
running.update(max_iters=3,llm_retry_enabled=False,llm_max_retries=1,llm_max_concurrent=1)
running['auto_title_config']['enabled']=False
running['reme_light_memory_config'].update(dream_cron_enabled=False,inbox_push_enabled=False,summarize_when_compact=False)
running['light_context_config']['scroll_config']['summarize_unheadlined_evictions']=False
running['light_context_config']['strategy']='native'
running['light_context_config']['context_compact_config']['enabled']=False
c.configure_agent('default',{'tools':profile['tools'],'running':running})
for client in c.list_mcp():
 if client['enabled']:c._request('PATCH','/api/mcp/toggle/'+client['key'])
before=next(x for x in c._request('GET','/api/models') if x['id']=='agentteams-gateway')
expected='http://aigw-local.agentteams.io:8080'+p['route_prefix']+'/v1'
c._request('PUT','/api/models/agentteams-gateway/config',{'base_url':expected,'api_key':os.environ['AGENTTEAMS_WORKER_GATEWAY_KEY'],'generate_kwargs':{'max_tokens':2000}})
after=c._request('GET','/api/agents/default')
assert not any(t['enabled'] for t in after['tools']['builtin_tools'].values())
assert not any(t['enabled'] for t in c.list_mcp())
assert after['running']['llm_retry_enabled'] is False
print(json.dumps({'builtin_tools_enabled':0,'mcp_enabled':0,'background_model_work':False,'provider':expected}))
'''


def main():
    plan = json.loads((PLAN / "manifest.json").read_text())
    result = {}
    for role, entry in plan["roles"].items():
        proc = subprocess.run(["docker", "exec", "-i", "agentteams-worker-" + entry["worker"],
                               "/opt/venv/qwenpaw/bin/python", "-c", REMOTE],
                              input=json.dumps({**entry, "guard_url": plan["guard_url"]}), text=True, capture_output=True, timeout=180)
        if proc.returncode:
            safe_error = next((line.split(":", 1)[0] for line in reversed(proc.stderr.splitlines()) if "Error:" in line), "runtime_not_ready")
            raise SystemExit("Native configuration not ready for " + role + "; guard stays disarmed; " + safe_error)
        result[role] = json.loads(proc.stdout)
        (PLAN / "runtime-policy.json").write_text(json.dumps(result, indent=2))
    rows = json.loads(subprocess.check_output(["docker", "exec", "agentteams-controller", "agt", "get", "workers", "-o", "json"]))["workers"]
    roles = {role: {"room_id": next(w for w in rows if w["name"] == item["worker"])["roomID"],
                    "sender_id": next(w for w in rows if w["name"] == item["worker"])["matrixUserID"]}
             for role, item in plan["roles"].items()}
    local = dict(line.split("=", 1) for line in Path("/root/.config/cyberguard/agentteams-local.env").read_text().splitlines()
                 if line and not line.startswith("#") and "=" in line)
    config = {"CYBERGUARD_AGENTTEAMS_MATRIX_URL": "http://agentteams-controller:8080",
              "CYBERGUARD_AGENTTEAMS_MATRIX_HOST": "matrix-local.agentteams.io:18080",
              "CYBERGUARD_AGENTTEAMS_MATRIX_USER": local["AGENTTEAMS_ADMIN_USER"],
              "CYBERGUARD_AGENTTEAMS_MATRIX_PASSWORD": local["AGENTTEAMS_ADMIN_PASSWORD"],
              "CYBERGUARD_AGENTTEAMS_ROLES_JSON": json.dumps(roles, separators=(",", ":")),
              "CYBERGUARD_AGENTTEAMS_STAGE_TIMEOUT_SECONDS": "180"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request("http://127.0.0.1:18080/_matrix/client/v3/login",
        data=json.dumps({"type": "m.login.password", "identifier": {"type": "m.id.user", "user": local["AGENTTEAMS_ADMIN_USER"]},
                         "password": local["AGENTTEAMS_ADMIN_PASSWORD"]}).encode(),
        headers={"Content-Type": "application/json", "Host": config["CYBERGUARD_AGENTTEAMS_MATRIX_HOST"]})
    with opener.open(request, timeout=15) as response:
        config["CYBERGUARD_AGENTTEAMS_MATRIX_TOKEN"] = json.load(response)["access_token"]
    config.pop("CYBERGUARD_AGENTTEAMS_MATRIX_USER")
    config.pop("CYBERGUARD_AGENTTEAMS_MATRIX_PASSWORD")
    target = PRIVATE / "console-backend.env"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(k + "=" + v for k, v in config.items()) + "\n")
    (PLAN / "roles.json").write_text(json.dumps(roles, indent=2))
    print(json.dumps({"status": "configured_disarmed", "backend_env": str(target), "roles": list(roles)}))


if __name__ == "__main__":
    main()
