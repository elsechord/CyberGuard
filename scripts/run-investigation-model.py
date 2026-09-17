#!/usr/bin/env python3
"""Run an actual model against exercise-only evidence with two allowlisted tools."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation.evidence import load_bundle
from cyberguard_investigation.model_runner import read_secret_file, run_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--gateway-url")
    args = parser.parse_args()
    try:
        values = {**os.environ, **read_secret_file(args.env_file)}
        key = next((values[name] for name in ("CYBERGUARD_MODEL_API_KEY", "AGENTTEAMS_LLM_API_KEY", "OPENAI_API_KEY") if values.get(name)), "")
        result = run_model(load_bundle(args.bundle), endpoint=args.endpoint, model=args.model, api_key=key,
                           output=args.output, run_id=args.run_id, gateway_url=args.gateway_url,
                           reader_token=values.get("CYBERGUARD_API_TOKEN"), report_token=values.get("CYBERGUARD_REPORT_TOKEN"))
        print(json.dumps({"status": result["status"], "failure": result.get("failure"), "usage": result["usage"], "output": str(args.output.resolve())}))
        return 0 if result["status"] == "completed" else 1
    except Exception:
        print(json.dumps({"status": "failed", "failure": "invalid_configuration_or_input_details_withheld"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
