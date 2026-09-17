#!/usr/bin/env python3
"""Register fresh role-bound Higress providers; never call a model or wake Workers."""
import argparse
import json
from pathlib import Path
import stat
import subprocess

REMOTE = r'''
import http.cookiejar,json,os,sys,urllib.request,urllib.error
p=json.load(sys.stdin)
o=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
with o.open(p["guard_url"].removesuffix("/v1")+"/health",timeout=10) as r: health=json.load(r)
assert health.get("armed") is False,"Guard must be disarmed"
def call(method,path,body=None,absent_ok=False):
 r=urllib.request.Request("http://127.0.0.1:8001"+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={"Content-Type":"application/json"})
 try:
  with o.open(r,timeout=20) as response: value=json.load(response)
 except urllib.error.HTTPError as e:
  if absent_ok and e.code==404:return None
  try:
   error=json.loads(e.read())
   detail=str(error.get("message") or error.get("code") or "operation rejected") if isinstance(error,dict) else "operation rejected"
  except (ValueError,TypeError):detail="operation rejected (non-JSON response)"
  for _,obj in p["objects"]:
   for token in obj.get("tokens",[]):detail=detail.replace(token,"[REDACTED]")
  for k,v in os.environ.items():
   if any(x in k.upper() for x in ("KEY","TOKEN","SECRET","PASSWORD")) and len(v)>=8:detail=detail.replace(v,"[REDACTED]")
  raise RuntimeError("Higress HTTP "+str(e.code)+" "+path+" "+detail[:700]) from None
 if isinstance(value,dict) and value.get("success") is False:raise RuntimeError("Higress operation rejected")
 return value.get("data",value) if isinstance(value,dict) else value
call("POST","/session/login",{"username":os.environ["AGENTTEAMS_ADMIN_USER"],"password":os.environ["AGENTTEAMS_ADMIN_PASSWORD"]})
# Unknown existing resources fail closed, including partially created providers.
# Inspect their non-secret fields separately; never auto-overwrite them.
pending=[]
for kind,body in p["objects"]:
 existing=call("GET","/v1/"+kind+"/"+body["name"],absent_ok=True)
 if existing is not None:
  if kind=="service-sources" and all(existing.get(k)==body[k] for k in ("domain","port","protocol")):continue
  raise RuntimeError("Resource already exists: "+kind+"/"+body["name"])
 pending.append((kind,body,"POST"))
for kind,body,method in pending:
 call(method,"/v1/"+kind+("/"+body["name"] if method=="PUT" else ""),body)
for entry in p["roles"].values():
 body=call("GET","/v1/ai/routes/"+entry["route"])
 assert body["authConfig"]["enabled"] and body["authConfig"]["allowedConsumers"]==["worker-"+entry["worker"]]
 assert body["upstreams"][0]["provider"]==entry["provider"]
print(json.dumps({"registered":list(p["roles"]),"model_calls":0,"workers_started":False}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--guard-env", type=Path, default=Path("/root/.config/cyberguard/model-guard.env"))
    args = parser.parse_args()
    if stat.S_IMODE(args.guard_env.stat().st_mode) & 0o077:
        raise SystemExit("Guard environment must have owner-only permissions")
    manifest = json.loads((args.plan / "manifest.json").read_text())
    env = dict(line.split("=", 1) for line in args.guard_env.read_text().splitlines() if line and not line.startswith("#") and "=" in line)
    guard = json.loads(env["CYBERGUARD_MODEL_GUARD_CONFIG"])
    if guard["run_id"] != manifest["run_id"] or guard["model"] != manifest["canonical_model"]:
        raise SystemExit("Plan and immutable guard run/model differ")
    objects = []
    for role, entry in manifest["roles"].items():
        cfg = guard["roles"][role]
        if cfg["model_alias"] != entry["model_alias"] or len(cfg["token"]) < 32:
            raise SystemExit("Guard role alias/key validation failed")
        body = json.loads((args.plan / (entry["worker"] + ".provider.template.json")).read_text())
        if body["rawConfigs"]["openaiCustomUrl"] != manifest["guard_url"].rstrip("/"):
            raise SystemExit("Provider destination differs from plan")
        body["tokens"] = [cfg["token"]]
        objects += [["service-sources", json.loads((args.plan / (entry["worker"] + ".service-source.json")).read_text())],
                    ["ai/providers", body], ["ai/routes", json.loads((args.plan / (entry["worker"] + ".route.json")).read_text())]]
    result = subprocess.run(["docker", "exec", "-i", "agentteams-controller", "python3", "-c", REMOTE],
                            input=json.dumps({"objects": objects, "roles": manifest["roles"], "guard_url":manifest["guard_url"]}), text=True, capture_output=True, timeout=120)
    if result.returncode:
        for line in result.stderr.splitlines():
            if line.startswith("RuntimeError:"):
                print(line)
        raise SystemExit("Registration failed; keep guard disarmed and inspect partial registrations")
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
