"""Offline HTTP investigation acceptance: exercise bundles and optional real Linux collection."""
import argparse
import hashlib
import importlib.util
import json
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from lab_support import LabStack, http
from cyberguard_investigation.evidence import load_bundle, validate_bundle
from cyberguard_investigation.collector import collect_linux
from cyberguard_investigation.analysis import analyze_bundle
from cyberguard_investigation.report import render_markdown


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(output, include_live):
    session_id = "INV-" + uuid4().hex
    directory = output / session_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"session_id": session_id, "started_at": datetime.now(UTC).isoformat(), "status": "failed",
        "mode": "fixed_workflow", "model_runs": {"single_agent": "not_run", "multi_agent": "not_run"},
        "agentteams_execution": "not_run", "mutating_actions": False, "checks": [], "runs": []}
    trace = []

    def check(name, condition, payload=None):
        manifest["checks"].append({"name": name, "passed": bool(condition)})
        trace.append({"step": name, "payload": payload})
        if not condition:
            raise RuntimeError("investigation acceptance failed: " + name)
        print(name, flush=True)

    try:
        spec = importlib.util.spec_from_file_location("lab_snapshot", ROOT / "scripts/lab-demo.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        write(directory / "source-tree.json", module.source_snapshot())
        cases = [(path.stem, load_bundle(path)) for path in sorted((ROOT / "benchmark/investigation/cases").glob("*.json"))]
        check("three_exercise_inputs_present", len(cases) == 3)
        if include_live:
            if sys.platform != "linux":
                raise RuntimeError("--include-live requires Linux; use compose.investigation.yaml")
            live = collect_linux()
            validate_bundle(live)
            check("real_container_collection_labeled", live["provenance"]["kind"] == "live_collection")
            cases.append(("container-observation", live))
    except Exception as exc:
        manifest["error"] = str(exc)
    else:
        try:
            stack = LabStack()
            # Use only the gateway. URLs for other services remain configured but
            # those services are never started or called by this workflow.
            stack.ports = {"gateway": stack.ports["gateway"]}
            ingest_token, report_token = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
            stack.overrides["gateway"] = {"CYBERGUARD_INVESTIGATION_INGEST_TOKEN": ingest_token,
                                          "CYBERGUARD_REPORT_TOKEN": report_token}
            with stack:
                base = stack.urls["gateway"]
                for name, bundle in cases:
                    started = time.monotonic()
                    case_dir = directory / name
                    case_dir.mkdir()
                    write(case_dir / "evidence.json", bundle)
                    status, response = http(base + "/investigations/bundles", ingest_token, bundle)
                    check(name + "_import_integrity", status == 200 and response.get("integrity") == "valid", response)
                    run_id = session_id + "-" + name
                    specification = {"run_id": run_id, "bundle_id": bundle["bundle_id"], "mode": "fixed_workflow",
                                     "budget": {"max_input_tokens": 20000, "max_output_tokens": 8000, "max_tool_calls": 16}}
                    status, prepared = http(base + "/investigations/runs", ingest_token, specification)
                    check(name + "_run_bound", status == 200 and prepared.get("bundle_sha256") == bundle["bundle_sha256"], prepared)
                    status, response = http(base + "/investigations/runs/" + run_id + "/evidence", stack.tokens["gateway"])
                    check(name + "_readonly_evidence", status == 200 and response.get("bundle") == bundle, response.get("tool_receipt"))
                    report = analyze_bundle(response["bundle"], run_id=run_id)
                    status, submitted = http(base + "/investigations/runs/" + run_id + "/reports", report_token, report)
                    check(name + "_bound_report_accepted", status == 200 and submitted.get("validation", {}).get("schema_and_citations") == "valid", submitted.get("validation"))
                    status, exported = http(base + "/investigations/runs/" + run_id + "/reports", stack.tokens["gateway"])
                    receipts = exported.get("tool_receipts", [])
                    check(name + "_run_receipts_retained", status == 200 and exported.get("tool_calls_used") == 2
                          and len(exported.get("reports", [])) == 1 and len(receipts) == 2
                          and all(r["run_id"] == run_id and r["bundle_sha256"] == bundle["bundle_sha256"]
                                  and r["sequence"] == index for index, r in enumerate(receipts, 1)), receipts)
                    write(case_dir / "run-export.json", exported)
                    write(case_dir / "report.json", report)
                    (case_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
                    manifest["runs"].append({"case": name, "run_id": run_id, "bundle_sha256": bundle["bundle_sha256"],
                        "provenance": bundle["provenance"]["kind"], "duration_seconds": round(time.monotonic() - started, 3),
                        "execution": "fixed_workflow", "model_input_tokens": 0, "model_output_tokens": 0,
                        "tool_calls": 2, "semantic_evaluation": "separate_evaluator_required"})
            manifest["status"] = "passed"
        except Exception as exc:
            manifest["error"] = str(exc)
    finally:
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        write(directory / "manifest.json", manifest)
        write(directory / "trace.json", trace)
        (directory / "SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.relative_to(directory).as_posix() + "\n"
             for p in sorted(directory.rglob("*")) if p.is_file() and p.name != "SHA256SUMS"), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "manifest": str(directory / "manifest.json")}, indent=2))
    return 0 if manifest["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/investigation")
    parser.add_argument("--include-live", action="store_true", help="Read-only collection of this Linux container; not a real incident")
    args = parser.parse_args()
    sys.exit(run(args.output.resolve(), args.include_live))
