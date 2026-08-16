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
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


auditor = load_module("audit_results", ROOT / "benchmark" / "audit_results.py")
runner = load_module("matrix_runner_audit", ROOT / "benchmark" / "matrix_runner.py")


class BenchmarkAuditTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        variants = root / "variants.json"
        scenarios = root / "scenarios"
        results = root / "results"
        scenarios.mkdir()
        variant = {"id": "full", "disabled_capabilities": []}
        scenario = {"scenario_id": "case", "title": "Case"}
        variants.write_text(json.dumps({"variants": [variant], "scenarios": ["case"], "repetitions": 1}), encoding="utf-8")
        (scenarios / "case.json").write_text(json.dumps(scenario), encoding="utf-8")
        run = results / "full" / "case" / "run-01"
        run.mkdir(parents=True)
        prompt = runner.build_prompt(variant, scenario, "run-01")
        (run / "prompt.txt").write_text(prompt, encoding="utf-8")
        provenance = runner.build_provenance(variant, scenario, "run-01", prompt, "model-x", 0.0, "v1.2.2")
        (run / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        for name in ("report.json", "runtime.json", "annotation.json"):
            (run / name).write_text("{}", encoding="utf-8")
        (run / "metrics.json").write_text(json.dumps({
            "run_failed": False, "annotator": "judge-a", "ground_truth_version": "ground-truth-v1"
        }), encoding="utf-8")
        return results, variants, scenarios

    def test_accepts_complete_hash_bound_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = auditor.audit(*self._fixture(Path(tmp)))
            self.assertTrue(result["valid"], result["issues"])
            self.assertEqual(result["observed_runs"], 1)

    def test_rejects_prompt_tampering_and_missing_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, variants, scenarios = self._fixture(Path(tmp))
            (results / "full" / "case" / "run-01" / "prompt.txt").write_text("tampered", encoding="utf-8")
            config = json.loads(variants.read_text(encoding="utf-8"))
            config["repetitions"] = 2
            variants.write_text(json.dumps(config), encoding="utf-8")
            result = auditor.audit(results, variants, scenarios)
            self.assertFalse(result["valid"])
            self.assertTrue(any("prompt_sha256" in issue for issue in result["issues"]))
            self.assertTrue(any("expected 2 runs" in issue for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
