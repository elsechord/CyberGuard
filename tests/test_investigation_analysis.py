"""Behavioral and trust-boundary checks for offline investigation."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cyberguard_investigation.analysis import analyze_bundle
from cyberguard_investigation.evidence import load_bundle, make_artifact, make_bundle
from cyberguard_investigation.evaluation import evaluate_case, protocol_for, validate_run_record
from cyberguard_investigation.report import validate_report, render_markdown

CASES = ROOT / "benchmark" / "investigation"


class InvestigationAnalysisTests(unittest.TestCase):
    def case(self, index):
        name = f"case-{index:03d}.json"
        return load_bundle(CASES / "cases" / name), json.loads((CASES / "evaluator-only" / name).read_text(encoding="utf-8"))

    def build(self, path="/var/tmp/arbitrary-name", *, persistence=True, approved=False, status="collected"):
        artifacts = [make_artifact("processes", "test:/proc", {"processes": [{"pid": 311, "exe": path,
            "cpu_percent": 80, "cpu_observation_status": "collected"}]})]
        if persistence:
            artifacts.append(make_artifact("persistence", "test:config", {"entries": [{"command": path, "enabled": None}]}, status=status))
        if approved:
            artifacts.append(make_artifact("workload_inventory", "test:owner", {"entries": [{"exe": path, "authorization": "approved"}]}))
        return make_bundle(artifacts, provenance={"kind": "exercise"})

    def has(self, report, finding_type, status):
        return any(f.get("finding_type") == finding_type and f["status"] == status for f in report["findings"])

    def test_three_cases_and_no_fabricated_model_results(self):
        for index in (1, 2, 3):
            with self.subTest(case=index):
                bundle, rubric = self.case(index)
                result = evaluate_case(bundle, rubric)
                fixed, single, multi = result["runs"]
                self.assertEqual(fixed["score"]["passed"], fixed["score"]["total"])
                self.assertEqual(single["status"], "not_run")
                self.assertEqual(multi["status"], "not_run")
                self.assertIsNone(multi["score"])

    def test_path_rename_does_not_change_rule_and_is_not_mining_attribution(self):
        for path in ("/tmp/random-082", "/dev/shm/unrelated-program", "/var/tmp/product"):
            report = analyze_bundle(self.build(path))
            self.assertTrue(self.has(report, "suspicious_persistence", "supported"))
            self.assertTrue(self.has(report, "attribution", "inconclusive"))
            self.assertTrue(self.has(report, "entrypoint", "inconclusive"))

    def test_high_cpu_alone_never_proposes_termination(self):
        report = analyze_bundle(self.build(persistence=False))
        self.assertTrue(self.has(report, "unclassified_workload", "inconclusive"))
        self.assertEqual(report["proposed_actions"], [])

    def test_unavailable_persistence_not_positive_evidence(self):
        report = analyze_bundle(self.build(status="unavailable"))
        self.assertFalse(self.has(report, "suspicious_persistence", "supported"))
        self.assertTrue(any("Unavailable" in unknown for unknown in report["unknowns"]))

    def test_declared_authorization_does_not_prove_clean_host(self):
        report = analyze_bundle(self.build("/opt/application/render", approved=True))
        self.assertTrue(self.has(report, "authorized_workload", "supported"))
        self.assertFalse(report["proposed_actions"])
        finding = next(f for f in report["findings"] if f.get("finding_type") == "authorized_workload")
        self.assertTrue(any("not proof" in text for text in finding["limitations"]))

    def test_approved_temporary_persistence_preserves_counterevidence(self):
        bundle = self.build(approved=True)
        report = analyze_bundle(bundle)
        finding = next(f for f in report["findings"] if f.get("finding_type") == "suspicious_persistence")
        self.assertEqual(finding["contradicting_evidence_ids"], [bundle["artifacts"][-1]["evidence_id"]])

    def test_disabled_persistence_is_not_positive_signal(self):
        bundle = make_bundle([make_artifact("processes", "test", {"processes": [{"pid": 12, "exe": "/tmp/foo", "cpu_percent": 80, "cpu_observation_status": "collected"}]}),
                              make_artifact("persistence", "test", {"entries": [{"command": "/tmp/foo", "enabled": False}]})], provenance={"kind": "exercise"})
        self.assertFalse(self.has(analyze_bundle(bundle), "suspicious_persistence", "supported"))

    def test_malformed_optional_observations_degrade_to_uncertainty(self):
        bundle = make_bundle([make_artifact("processes", "test", {"processes": None}),
                              make_artifact("persistence", "test", {"entries": {}})], provenance={"kind": "exercise"})
        report = analyze_bundle(bundle)
        self.assertTrue(all(f["status"] == "inconclusive" for f in report["findings"]))

    def test_cross_bundle_or_mode_report_rejected(self):
        first, _ = self.case(1)
        second, _ = self.case(2)
        report = analyze_bundle(first)
        with self.assertRaises(ValueError):
            validate_report(report, second)
        with self.assertRaises(ValueError):
            validate_report(report, first, expected_mode="multi_agent")
        changed = copy.deepcopy(report)
        changed["bundle_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_report(changed, first)

    def test_unavailable_unknown_and_empty_support_rejected(self):
        bundle = self.build(status="unavailable")
        for refs in ([], ["nonexistent"], [bundle["artifacts"][-1]["evidence_id"]]):
            report = analyze_bundle(bundle)
            report["findings"][0]["status"] = "supported"
            report["findings"][0]["supporting_evidence_ids"] = refs
            with self.assertRaises(ValueError):
                validate_report(report, bundle)

    def test_actions_cannot_claim_authorization(self):
        bundle = self.build()
        report = analyze_bundle(bundle)
        report["proposed_actions"][0]["requires_approval"] = False
        with self.assertRaises(ValueError):
            validate_report(report, bundle)

    def test_markdown_report_does_not_render_untrusted_links_or_html(self):
        report = analyze_bundle(self.build())
        report["findings"][0]["claim"] = '<img src="https://example.invalid/tracker">\n# fake\n![remote](https://example.invalid/img)'
        report["unknowns"] = ["[click](https://example.invalid)\n## injected"]
        rendered = render_markdown(report)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("![remote]", rendered)
        self.assertNotIn("\n# fake", rendered)
        self.assertNotIn("[click]", rendered)
        self.assertIn("&lt;img", rendered)

    def test_import_requires_common_protocol_and_finite_usage(self):
        bundle, rubric = self.case(1)
        protocol = protocol_for(bundle)
        report = analyze_bundle(bundle)
        report["mode"] = "single_agent"
        # Contract fixture only, never represented as an actual model run.
        record = {"mode": "single_agent", "status": "completed", "report": report,
                  "bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["bundle_sha256"],
                  "protocol_sha256": protocol["protocol_sha256"],
                  "usage": {"input_tokens": None, "output_tokens": None, "tool_calls": None,
                            "elapsed_seconds": None, "cost_usd": None}}
        validate_run_record(record, bundle, protocol)
        result = evaluate_case(bundle, rubric, imported_runs=[record])["runs"][1]
        self.assertEqual(result["budget_status"], "unknown")
        self.assertEqual(result["runtime_attestation"], "caller_reported_not_independently_attested")
        invalid = copy.deepcopy(record)
        invalid["protocol_sha256"] = "wrong-permissions-or-evidence"
        with self.assertRaises(ValueError):
            evaluate_case(bundle, rubric, imported_runs=[invalid])
        invalid = copy.deepcopy(record)
        invalid["usage"]["input_tokens"] = float("nan")
        with self.assertRaises(ValueError):
            validate_run_record(invalid, bundle, protocol)

    def test_overbudget_import_not_claimed_fair(self):
        bundle, rubric = self.case(1)
        protocol = protocol_for(bundle)
        report = analyze_bundle(bundle)
        report["mode"] = "multi_agent"
        record = {"mode": "multi_agent", "status": "completed", "report": report,
                  **{k: protocol[k] for k in ("bundle_id", "bundle_sha256", "protocol_sha256")},
                  "usage": {"input_tokens": 33000, "output_tokens": 100, "tool_calls": 3, "elapsed_seconds": 1, "cost_usd": None}}
        evaluated = evaluate_case(bundle, rubric, imported_runs=[record])["runs"][2]
        self.assertEqual(evaluated["budget_status"], "exceeded")
        self.assertEqual(evaluated["budget_exceeded_fields"], ["input_tokens"])


if __name__ == "__main__":
    unittest.main()
