"""Operator-only bundle import/run preparation for the local gateway; no model execution."""
import argparse
import json
import os
import stat
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cyberguard_investigation.evidence import load_bundle


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("fixed_workflow", "single_agent", "multi_agent"), required=True)
    parser.add_argument("--gateway", default="http://127.0.0.1:18100")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-input-tokens", type=int, default=20000)
    parser.add_argument("--max-output-tokens", type=int, default=8000)
    parser.add_argument("--max-tool-calls", type=int, default=16)
    args = parser.parse_args()
    try:
        origin = urlsplit(args.gateway)
        if (origin.scheme != "http" or origin.hostname != "127.0.0.1" or not origin.port
                or origin.username or origin.password or origin.path not in {"", "/"} or origin.query or origin.fragment):
            raise ValueError("This local operator tool requires an explicit http://127.0.0.1:port gateway")
        if args.output.exists():
            raise ValueError("Output already exists; choose a new record path")
        token = os.getenv("CYBERGUARD_INVESTIGATION_INGEST_TOKEN", "")
        if args.env_file:
            if os.name != "posix" or stat.S_IMODE(args.env_file.stat().st_mode) & 0o077:
                raise ValueError("env-file requires POSIX private permissions; use WSL with a 0600 file")
            for line in args.env_file.read_text().splitlines():
                if line.startswith("CYBERGUARD_INVESTIGATION_INGEST_TOKEN="):
                    token = line.split("=", 1)[1]
        if len(token) < 32:
            raise ValueError("Intake credential is missing")
        bundle = load_bundle(args.bundle)
        request = {"run_id": args.run_id, "bundle_id": bundle["bundle_id"], "mode": args.mode,
                   "budget": {"max_input_tokens": args.max_input_tokens, "max_output_tokens": args.max_output_tokens,
                              "max_tool_calls": args.max_tool_calls}}
        def post(path, body):
            message = Request(args.gateway.rstrip("/") + path, json.dumps(body).encode(),
                              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with build_opener(ProxyHandler({}), NoRedirect()).open(message, timeout=20) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("Gateway response exceeds bound")
            return json.loads(raw)
        imported = post("/investigations/bundles", bundle)
        run = post("/investigations/runs", request)
        if run.get("bundle_sha256") != bundle["bundle_sha256"] or run.get("run_id") != args.run_id:
            raise ValueError("Gateway binding differs from requested evidence")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump({"import": imported, "run": run}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": "prepared", "run_id": args.run_id, "output": str(args.output)}))
        return 0
    except HTTPError as exc:
        print(json.dumps({"status": "failed", "http_status": exc.code, "reason": "gateway request rejected"}), file=sys.stderr)
    except (OSError, ValueError, URLError):
        print(json.dumps({"status": "failed", "reason": "invalid local configuration or gateway unavailable; credentials omitted"}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
