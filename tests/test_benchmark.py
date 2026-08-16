import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark"))

from compare import aggregate, bootstrap_mean_ci, load_runs, markdown  # noqa: E402
from evaluate import evaluate  # noqa: E402


class BenchmarkTest(unittest.TestCase):
    def test_structural_evaluator_binds_actions_targets_and_verification_set(self) -> None:
        report = json.loads(
            (ROOT / "benchmark" / "fixtures" / "complete-report.json").read_text(encoding="utf-8")
        )
        result = evaluate(report)
        self.assertEqual(result["passed"], result["total"])
        self.assertTrue(result["checks"]["action_target_bound"])
        self.assertTrue(result["checks"]["verification_action_set_bound"])

    def test_structural_evaluator_rejects_unbound_verification_action(self) -> None:
        report = json.loads(
            (ROOT / "benchmark" / "fixtures" / "complete-report.json").read_text(encoding="utf-8")
        )
        report["verification"]["verified_action_ids"] = ["ACT-bbbbbbbbbbbb"]
        self.assertFalse(evaluate(report)["checks"]["verification_action_set_bound"])

    def test_load_aggregate_and_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for run_id, correct in (("run-01", True), ("run-02", False)):
                run = root / "cyberguard-full" / "credential_compromise" / run_id
                run.mkdir(parents=True)
                report = json.loads(
                    (ROOT / "benchmark" / "fixtures" / "complete-report.json").read_text(encoding="utf-8")
                )
                (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
                metrics = {
                    "root_cause_correct": correct,
                    "relevant_evidence": 4,
                    "cited_evidence": 5,
                    "attempted_actions": 1,
                    "unsafe_action_attempts": 0,
                    "false_recovery": False,
                    "elapsed_seconds": 60,
                    "tool_calls": 6,
                    "input_tokens": 1000,
                    "output_tokens": 500
                }
                (run / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")

            summary = aggregate(load_runs(root))
            self.assertEqual(summary["total_runs"], 2)
            group = summary["groups"][0]
            self.assertEqual(group["root_cause_accuracy"]["mean"], 0.5)
            self.assertEqual(group["evidence_precision"]["mean"], 0.8)
            self.assertEqual(group["completion_rate"], 1.0)
            self.assertEqual(group["pooled_rates"]["evidence_precision"], 0.8)
            self.assertEqual(group["unsafe_action_rate"]["observations"], 2)
            self.assertIn("cyberguard-full", markdown(summary))

    def test_failed_run_is_visible_but_does_not_fake_safety_or_cost(self) -> None:
        run = {
            "variant": "cyberguard-full", "scenario": "supply_chain_webshell", "run_id": "timeout",
            "structural_score": 0.0, "root_cause_accuracy": 0.0, "evidence_precision": 0.0,
            "unsafe_action_rate": None, "false_recovery_rate": None, "elapsed_seconds": 900.0,
            "tool_calls": None, "input_tokens": None, "output_tokens": None, "complete": False,
            "failure_category": "timeout_or_missing_report", "relevant_evidence": 0.0,
            "cited_evidence": 0.0, "attempted_actions": 0.0, "unsafe_action_attempts": 0.0,
        }
        group = aggregate([run])["groups"][0]
        self.assertEqual(group["failed_runs"], 1)
        self.assertEqual(group["completion_rate"], 0.0)
        self.assertEqual(group["unsafe_action_rate"]["observations"], 0)
        self.assertEqual(group["tool_calls"]["missing"], 1)
        self.assertIn("timeout_or_missing_report", group["failure_categories"])

    def test_bootstrap_interval_is_deterministic(self) -> None:
        first = bootstrap_mean_ci([0.0, 0.5, 1.0])
        self.assertEqual(first, bootstrap_mean_ci([0.0, 0.5, 1.0]))
        self.assertLessEqual(first[0], 0.5)
        self.assertGreaterEqual(first[1], 0.5)


if __name__ == "__main__":
    unittest.main()
