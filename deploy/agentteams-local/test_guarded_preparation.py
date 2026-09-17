import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("prepare_guarded_team", Path(__file__).with_name("prepare-guarded-team.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreparationTests(unittest.TestCase):
    def test_isolated_sleeping_identities_and_role_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan"
            m = module.prepare(out, "TEST-RUN-004", "cg-test004", "test-model", "http://model-guard.agentteams.local:8080/v1")
            self.assertEqual(len(m["roles"]), 3)
            self.assertEqual(len({r["service_source"] for r in m["roles"].values()}), 3)
            for role, entry in m["roles"].items():
                worker = json.loads((out / (entry["worker"] + ".worker.json")).read_text())
                self.assertEqual(worker["spec"]["state"], "Sleeping")
                self.assertEqual(worker["spec"]["modelProvider"], entry["provider"])
                route = json.loads((out / (entry["worker"] + ".route.json")).read_text())
                self.assertEqual(route["authConfig"]["allowedConsumers"], ["worker-" + entry["worker"]])
                with zipfile.ZipFile(out / (entry["worker"] + ".zip")) as archive:
                    self.assertEqual(json.loads(archive.read("manifest.json"))["worker"]["model"], entry["model_alias"])
                    self.assertTrue(all(n == "manifest.json" or n.startswith("skills/") for n in archive.namelist()))
            with self.assertRaises(FileExistsError):
                module.prepare(out, "TEST-RUN-004", "cg-test004", "test-model", "http://model-guard.agentteams.local:8080/v1")

    def test_rejects_legacy_unsafe_identity_and_nonlocal_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan"
            for prefix, url in [("response-planner", "http://model-guard.agentteams.local:8080/v1"),
                                ("cg-../old", "http://model-guard.agentteams.local:8080/v1"),
                                ("cg-test004", "https://provider.example/v1"),
                                ("cg-test004", "http://secret@model-guard.agentteams.local/v1")]:
                with self.assertRaises(ValueError):
                    module.prepare(out, "TEST-RUN-004", prefix, "test-model", url)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
