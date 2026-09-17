#!/usr/bin/env python3
"""Generate a deterministic, evidence-bound investigation; no model calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation.evidence import load_bundle
from cyberguard_investigation.analysis import analyze_bundle
from cyberguard_investigation.report import render_markdown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    report = analyze_bundle(load_bundle(args.bundle), run_id=args.run_id)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"mode": report["mode"], "bundle_id": report["bundle_id"], "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
