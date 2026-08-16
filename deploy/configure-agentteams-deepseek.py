#!/usr/bin/env python3
"""Configure AgentTeams' embedded Higress gateway for DeepSeek.

The AgentTeams v1.2.2 console accepts OpenAI-compatible provider metadata, but
its generated route can point at api.openai.com or at a non-existent cluster.
This utility writes the four runtime objects as one coherent configuration:

  DeepSeek provider -> Higress DNS service -> HTTPS/SNI route -> AI route.

Run it on the AgentTeams host as root after the controller is available.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


ENV_UPDATES = {
    "AGENTTEAMS_LLM_PROVIDER": "deepseek-official",
    "AGENTTEAMS_OPENAI_BASE_URL": "https://api.deepseek.com/v1",
    "AGENTTEAMS_DEFAULT_MODEL": "deepseek-v4-flash",
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def update_env(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    seen: set[str] = set()
    output: list[str] = []
    for raw in original.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0]
            if key in ENV_UPDATES:
                output.append(f"{key}={ENV_UPDATES[key]}")
                seen.add(key)
                continue
        output.append(raw)
    for key, value in ENV_UPDATES.items():
        if key not in seen:
            output.append(f"{key}={value}")

    current = path.stat()
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(output).rstrip() + "\n")
        os.chmod(temporary, stat.S_IMODE(current.st_mode))
        os.chown(temporary, current.st_uid, current.st_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure_gateway(api_key: str) -> None:
    # The embedded API is reachable only inside the controller container. The
    # secret is delivered over stdin, never as a process argument or log line.
    inner = f'''import json, os, ssl, urllib.request
from pathlib import Path
BASE = "https://localhost:18443"
CTX = ssl._create_unverified_context()
API_KEY = {json.dumps(api_key)}

def get(path):
    return json.load(urllib.request.urlopen(BASE + path, context=CTX, timeout=20))

def put(path, obj):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(obj, separators=(",", ":")).encode(),
        method="PUT",
        headers={{"Content-Type": "application/json"}},
    )
    return json.load(urllib.request.urlopen(request, context=CTX, timeout=20))

def persist(path, obj):
    """Persist the API object because v1.2.2 does not delete stale YAML entries."""
    target = Path(path)
    temporary = target.with_name(target.name + ".deepseek.tmp")
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\\n")
    if target.exists():
        current = target.stat()
        os.chmod(temporary, current.st_mode)
        os.chown(temporary, current.st_uid, current.st_gid)
    os.replace(temporary, target)

mcp_path = "/apis/networking.higress.io/v1/namespaces/higress-system/mcpbridges/default"
wasm_path = "/apis/extensions.higress.io/v1alpha1/namespaces/higress-system/wasmplugins/ai-proxy.internal"
ingress_path = "/apis/networking.k8s.io/v1/namespaces/higress-system/ingresses/ai-route-default-ai-route.internal"
route_path = "/api/v1/namespaces/higress-system/configmaps/ai-route-default-ai-route"
service_name = "deepseek-official"
cluster_name = service_name + ".dns"

mcp = get(mcp_path)
registries = []
for item in mcp["spec"].get("registries", []):
    name = item.get("name", "")
    domain = item.get("domain", "")
    stale = (
        name in {{"openai-compat", "llm-gitee-ai.internal", "llm-deepseek-direct.internal", "llm-deepseek-verified.internal", "llm-deepseek-official.internal"}}
        or domain == "api.stepfun.com"
    )
    if not stale and name != service_name:
        registries.append(item)
registries.append({{
    "domain": "api.deepseek.com",
    "name": service_name,
    "port": 443,
    "protocol": "https",
    "type": "dns",
}})
mcp["spec"]["registries"] = registries
put(mcp_path, mcp)

wasm = get(wasm_path)
wasm["spec"].setdefault("defaultConfig", {{}})["providers"] = [{{
    "agentteamsMode": True,
    "apiTokens": [API_KEY],
    "id": "deepseek-official",
    "openaiCustomServiceName": cluster_name,
    "openaiCustomServicePort": 443,
    "openaiCustomUrl": "https://api.deepseek.com/v1",
    "protocol": "openai",
    "type": "openai",
}}]
wasm["spec"]["matchRules"] = [{{
    "config": {{"activeProviderId": "deepseek-official"}},
    "configDisable": False,
    "service": [cluster_name],
}}]
put(wasm_path, wasm)

ingress = get(ingress_path)
annotations = ingress["metadata"].setdefault("annotations", {{}})
annotations.update({{
    "higress.io/destination": cluster_name + ":443",
    "higress.io/backend-protocol": "HTTPS",
    "higress.io/proxy-ssl-name": "api.deepseek.com",
    "higress.io/proxy-ssl-server-name": "on",
}})
put(ingress_path, ingress)

route = get(route_path)
route_data = json.loads(route["data"]["data"])
route_data["upstreams"] = [{{
    "provider": "deepseek-official",
    "weight": 100,
    "modelMapping": {{}},
}}]
route["data"]["data"] = json.dumps(route_data, ensure_ascii=False, separators=(",", ":"))
put(route_path, route)

# Read back the non-secret invariants so a partial update cannot look healthy.
check_mcp = get(mcp_path)
check_wasm = get(wasm_path)
check_ingress = get(ingress_path)
check_route = get(route_path)
matching = [x for x in check_mcp["spec"]["registries"] if x.get("name") == service_name]
providers = check_wasm["spec"]["defaultConfig"].get("providers", [])
rules = check_wasm["spec"].get("matchRules", [])
assert matching == [{{"domain":"api.deepseek.com","name":service_name,"port":443,"protocol":"https","type":"dns"}}]
assert len(providers) == 1 and providers[0].get("id") == "deepseek-official" and providers[0].get("type") == "openai"
assert providers[0].get("openaiCustomServiceName") == cluster_name
assert providers[0].get("openaiCustomUrl") == "https://api.deepseek.com/v1"
assert providers[0].get("apiTokens") == [API_KEY]
assert len(rules) == 1 and rules[0].get("service") == [cluster_name]
assert check_ingress["metadata"]["annotations"].get("higress.io/destination") == cluster_name + ":443"
assert all(x.get("domain") != "api.stepfun.com" for x in check_mcp["spec"]["registries"])

# The embedded API server restores these files on every container start. Its
# update path merges list entries instead of deleting stale providers, so write
# the verified objects back atomically as JSON (which is valid YAML).
persist("/data/mcpbridges/default.yaml", check_mcp)
persist("/data/wasmplugins/ai-proxy.internal.yaml", check_wasm)
persist("/data/ingresses/ai-route-default-ai-route.internal.yaml", check_ingress)
persist("/data/configmaps/ai-route-default-ai-route.yaml", check_route)
assert "api.stepfun.com" not in Path("/data/mcpbridges/default.yaml").read_text()
assert "api.stepfun.com" not in Path("/data/wasmplugins/ai-proxy.internal.yaml").read_text()
print("DeepSeek gateway configuration passed")
print("provider=deepseek-official type=openai-compatible")
print("upstream=api.deepseek.com:443 tls-sni=api.deepseek.com")
print("legacy-providers=absent")
'''
    subprocess.run(
        ["docker", "exec", "-i", "agentteams-controller", "python3", "-"],
        input=inner,
        text=True,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=Path("/srv/cyberguard/agentteams.env"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run this utility as root (sudo).")
    if not args.env.is_file():
        raise SystemExit(f"Missing environment file: {args.env}")
    values = read_env(args.env)
    api_key = values.get("AGENTTEAMS_LLM_API_KEY", "")
    if len(api_key) < 8 or api_key == "replace-me":
        raise SystemExit("AGENTTEAMS_LLM_API_KEY is missing or still a placeholder")
    configure_gateway(api_key)
    update_env(args.env)
    print("AgentTeams environment normalized for deepseek-v4-flash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
