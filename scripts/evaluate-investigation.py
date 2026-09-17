#!/usr/bin/env python3
"""Run fixed workflow and compare optional externally executed model records."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation.evidence import load_bundle
from cyberguard_investigation.evaluation import evaluate_case, protocol_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--import-run", action="append", type=Path, default=[])
    parser.add_argument("--protocol-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = load_bundle(args.bundle)
    if args.protocol_only:
        result = protocol_for(bundle)
    else:
        if args.rubric is None:
            parser.error("--rubric required unless --protocol-only")
        result = evaluate_case(bundle, json.loads(args.rubric.read_text(encoding="utf-8")),
                               imported_runs=[json.loads(path.read_text(encoding="utf-8")) for path in args.import_run])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "bundle_id": bundle["bundle_id"]}))


if __name__ == "__main__":
    main()
