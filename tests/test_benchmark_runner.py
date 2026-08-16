import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module("matrix_runner", ROOT / "benchmark" / "matrix_runner.py")
finalizer = load_module("finalize_run", ROOT / "benchmark" / "finalize_run.py")


class BenchmarkRunnerTest(unittest.TestCase):
    def test_extracts_only_marked_json(self):
        body = 'prefix CYBERGUARD_BENCHMARK_REPORT\n```json\n{"incident_id":"CG-1"}\n```'
        self.assertEqual(runner.extract_report(body), {"incident_id": "CG-1"})
        self.assertIsNone(runner.extract_report('{"incident_id":"unmarked"}'))

    def test_report_must_bind_to_current_run(self):
        self.assertTrue(runner.report_matches_run({"run_id": "run-1"}, "run-1"))
        self.assertFalse(runner.report_matches_run({"run_id": "run-2"}, "run-1"))
        self.assertFalse(runner.report_matches_run({}, "run-1"))

    def test_prompt_pins_variant_and_scenario(self):
        prompt = runner.build_prompt(
            {"id": "cyberguard-no-verifier", "disabled_capabilities": ["independent_verifier"]},
            {"scenario_id": "credential_compromise", "title": "Credential compromise"},
            "run-1",
        )
        self.assertIn("cyberguard-no-verifier", prompt)
        self.assertIn("independent_verifier", prompt)
        self.assertIn("run_id（必须原样返回）", prompt)
        self.assertIn(runner.REPORT_MARKER, prompt)

    def test_provenance_binds_run_prompt_scenario_and_model(self):
        variant = {"id": "cyberguard-full", "disabled_capabilities": []}
        scenario = {"scenario_id": "credential_compromise", "title": "Credential compromise"}
        prompt = runner.build_prompt(variant, scenario, "run-1")
        provenance = runner.build_provenance(variant, scenario, "run-1", prompt, "model-x", 0.2, "v1.2.2")
        self.assertEqual(provenance["run_id"], "run-1")
        self.assertEqual(provenance["model_id"], "model-x")
        self.assertEqual(provenance["temperature"], 0.2)
        self.assertRegex(provenance["scenario_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(provenance["prompt_sha256"], r"^[0-9a-f]{64}$")

    def test_finalization_requires_human_labels_and_telemetry(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text("{}", encoding="utf-8")
            (run_dir / "runtime.json").write_text(
                json.dumps({"elapsed_seconds": 4, "tool_calls": 2, "input_tokens": 10, "output_tokens": 5}),
                encoding="utf-8",
            )
            annotation = {
                "root_cause_correct": True,
                "relevant_evidence": 4,
                "cited_evidence": 5,
                "attempted_actions": 1,
                "unsafe_action_attempts": 0,
                "false_recovery": False,
                "annotator": "judge-a",
                "ground_truth_version": "benchmark/ground-truth-v2.json",
            }
            annotation_path = run_dir / "annotation.json"
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            metrics = finalizer.finalize(run_dir, annotation_path)
            self.assertTrue(metrics["root_cause_correct"])
            self.assertEqual(metrics["tool_calls"], 2)
            self.assertTrue((run_dir / "metrics.json").exists())

            annotation["annotator"] = None
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "annotator"):
                finalizer.finalize(run_dir, annotation_path)


if __name__ == "__main__":
    unittest.main()
