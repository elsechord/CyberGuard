#!/usr/bin/env python3
"""Register narrow investigation MCP servers; credentials travel only on stdin."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REMOTE = r'''
import http.cookiejar,json,os,sys,urllib.request,urllib.error
payload=json.load(sys.stdin)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
base="http://127.0.0.1:8001"
def call(method,path,body):
 req=urllib.request.Request(base+path,data=json.dumps(body).encode(),method=method,headers={"Content-Type":"application/json"})
 try:
  with opener.open(req,timeout=30) as response:
   raw=response.read()
   value=json.loads(raw) if raw else {}
   if isinstance(value,dict) and value.get("success") is False: raise RuntimeError("Higress rejected operation")
   return value
 except urllib.error.HTTPError as exc:
  if path == "/v1/service-sources" and exc.code == 409:
   return {}
  if path == "/v1/service-sources":
   print("SERVICE_SOURCE_ERROR: "+exc.read().decode()[:800],file=sys.stderr)
  raise RuntimeError("Higress HTTP "+str(exc.code)+" "+path) from None
call("POST","/session/login",{"username":os.environ["AGENTTEAMS_ADMIN_USER"],"password":os.environ["AGENTTEAMS_ADMIN_PASSWORD"]})
for config in payload:
 name=config["name"]
 call("POST","/v1/service-sources",{"type":"dns","name":"cg-invest-"+("read" if name.endswith("readonly") else "report"),"domain":"security-tool-gateway.agentteams.local","port":8080,"protocol":"http","properties":{},"authN":{"enabled":False}})
 call("PUT","/v1/mcpServer",{"name":name,"description":"CyberGuard investigation only","type":"OPEN_API","rawConfigurations":config["yaml"],"mcpServerName":name,"domains":["aigw-local.agentteams.io"],"services":[{"name":("cg-invest-read" if name.endswith("readonly") else "cg-invest-report")+".dns","port":8080,"weight":100}],"consumerAuthInfo":{"type":"key-auth","enable":True,"allowedConsumers":["manager","worker-endpoint-forensics","worker-response-planner","worker-recovery-verifier"]}})
 call("PUT","/v1/mcpServer/consumers",{"mcpServerName":name,"consumers":["manager","worker-endpoint-forensics","worker-response-planner","worker-recovery-verifier"]})
 print(name+": registered")
'''


def main():
    path = Path("/root/.config/cyberguard/services.env")
    env = dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#") and "=" in line)
    payload = []
    for suffix, key in [("readonly", "CYBERGUARD_API_TOKEN"), ("report", "CYBERGUARD_REPORT_TOKEN")]:
        name = "cyberguard-investigation-" + suffix
        text = (ROOT / "agentteams/mcp" / (name + ".yaml")).read_text()
        if len(env[key]) < 32:
            raise SystemExit("Configured MCP role token is too short")
        text = text.replace("http://security-tool-gateway:8080", "http://security-tool-gateway.agentteams.local:8080")
        text = text.replace('accessToken: ""', 'accessToken: ' + json.dumps(env[key]))
        payload.append({"name": "mcp-" + name, "yaml": text})
    result = subprocess.run(["docker", "exec", "-i", "agentteams-controller", "python3", "-c", REMOTE],
                            input=json.dumps(payload), text=True, capture_output=True)
    # Error bodies may contain provider config. Never echo captured stderr.
    if result.returncode:
        for line in result.stderr.splitlines():
            if line.startswith(("RuntimeError: Higress HTTP ", "RuntimeError: Higress rejected operation", "ModuleNotFoundError:", "SERVICE_SOURCE_ERROR:")):
                print(line)
        raise SystemExit("MCP registration failed; inspect sanitized local logs before retrying")
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
