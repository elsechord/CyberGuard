"""Offline run-correlation export: timeline merge, run scoping, envelope integrity, rendering."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location(
    "export_run_correlation", ROOT / "scripts" / "export-run-correlation.py")
correlation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(correlation)


def make_evidence(evidence_id, incident_id="CG-TEST-1", run_id=None, source="siem",
                  collected_at="2026-09-18T09:00:01+00:00", score=0.9, tamper=None):
    record = {
        "evidence_id": evidence_id, "incident_id": incident_id, "run_id": run_id,
        "source": source, "kind": "alert_bundle", "collected_at": collected_at,
        "summary": "exercise summary", "attack_techniques": ["T1059.004"],
        "entities": [{"entity_id": "ENT-1", "type": "workload", "value": "pod-a"}],
        "quality": {"score": score, "gate": "pass", "issues": []},
    }
    record["envelope_sha256"] = correlation.digest(record)
    if tamper:
        record[tamper] = "edited after signing"
    return record


def make_workflow(state, recorded_at, session_id="soc-demo", previous="received",
                  actor="team-leader", approval=False, incident_id="CG-TEST-1"):
    return {"event_id": "WF-" + state, "incident_id": incident_id, "session_id": session_id,
            "previous_state": previous, "state": state, "actor": actor, "message": "step",
            "recorded_at": recorded_at, "requires_human_approval": approval, "terminal": False}


def write_data(directory, evidence, workflow):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "evidence.jsonl").open("w", encoding="utf-8") as stream:
        for record in evidence:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (directory / "workflow.jsonl").open("w", encoding="utf-8") as stream:
        for event in workflow:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return directory


class RunCorrelationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = write_data(
            self.tmp.name,
            [make_evidence("EV-a", collected_at="2026-09-18T09:00:05+00:00"),
             make_evidence("EV-b", source="threat-intel", score=0.7,
                           collected_at="2026-09-18T09:00:06+00:00")],
            [make_workflow("received", "2026-09-18T09:00:01+00:00", previous=None, actor="manager"),
             make_workflow("investigating", "2026-09-18T09:00:10+00:00"),
             make_workflow("awaiting_approval", "2026-09-18T09:00:20+00:00", actor="response-planner",
                           approval=True, previous="investigating")])

    def test_merges_workflow_and_evidence_timeline(self):
        doc = correlation.build("CG-TEST-1", None, Path(self.data_dir))
        kinds = [entry["type"] for entry in doc["timeline"]]
        self.assertEqual(kinds, ["workflow", "evidence", "evidence", "workflow", "workflow"])
        first_approval = [e for e in doc["timeline"] if "需人工审批" in e["detail"]]
        self.assertEqual(len(first_approval), 1)
        self.assertEqual(doc["metrics"]["unresolved_approval_waits"], ["soc-demo"])
        self.assertEqual(doc["metrics"]["evidence_count"], 2)
        self.assertEqual(doc["metrics"]["sources"], ["siem", "threat-intel"])
        self.assertEqual(doc["metrics"]["attack_techniques"], ["T1059.004"])
        self.assertEqual(doc["metrics"]["entity_count"], 1)
        self.assertEqual(doc["metrics"]["cross_source_entity_count"], 1)
        self.assertEqual(doc["integrity"]["status"], "valid")

    def test_run_filter_scopes_evidence_only(self):
        other = make_evidence("EV-c", run_id="RUN-2", collected_at="2026-09-18T09:00:07+00:00")
        with (Path(self.data_dir) / "evidence.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(other) + "\n")
        doc = correlation.build("CG-TEST-1", "RUN-2", Path(self.data_dir))
        self.assertEqual(doc["run_scope"]["evidence_in_scope"], 1)
        self.assertEqual(doc["run_scope"]["evidence_out_of_scope"], 2)
        self.assertEqual(doc["run_scope"]["run_bindings_in_incident"], ["RUN-2"])
        self.assertEqual([e["id"] for e in doc["timeline"] if e["type"] == "evidence"], ["EV-c"])
        # Workflow events stay incident/session scoped even under a run filter.
        self.assertEqual(sum(e["type"] == "workflow" for e in doc["timeline"]), 3)
        self.assertIn("runs/RUN-2", doc["pointers"][0]["ref"])

    def test_tampered_envelope_is_flagged(self):
        tampered = make_evidence("EV-x", tamper="summary")
        write_data(Path(self.tmp.name) / "tampered", [tampered], [])
        doc = correlation.build("CG-TEST-1", None, Path(self.tmp.name) / "tampered")
        self.assertEqual(doc["integrity"]["status"], "invalid")
        self.assertEqual(doc["integrity"]["envelopes_invalid"], ["EV-x"])

    def test_export_digest_covers_document(self):
        doc = correlation.build("CG-TEST-1", None, Path(self.data_dir))
        payload = {k: v for k, v in doc.items() if k != "export_sha256"}
        self.assertEqual(correlation.digest(payload), doc["export_sha256"])

    def test_markdown_contains_sections_and_honest_boundary(self):
        markdown = correlation.render_markdown(correlation.build("CG-TEST-1", None, Path(self.data_dir)))
        for heading in ("## 时间线", "## 指标汇总", "## 证据完整性", "## 链接位", "## 边界"):
            self.assertIn(heading, markdown)
        self.assertIn("`EV-a`", markdown)
        self.assertIn("T1059.004", markdown)
        self.assertIn("docs/LIVE_TASK_EVIDENCE.md", markdown)
        self.assertIn("不在覆盖范围", markdown)
        self.assertIn("未决人工审批等待", markdown)

    def test_main_writes_markdown_and_json(self):
        output = Path(self.tmp.name) / "out" / "correlation.md"
        json_output = Path(self.tmp.name) / "out" / "correlation.json"
        with patch.object(sys, "argv", ["export-run-correlation.py", "CG-TEST-1",
                                        "--data-dir", str(self.data_dir),
                                        "--output", str(output),
                                        "--json-output", str(json_output)]):
            correlation.main()
        self.assertTrue(output.is_file())
        document = json.loads(json_output.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "cyberguard-run-correlation")
        self.assertEqual(document["schema_version"], "1.0")
        self.assertIn(document["incident_id"], output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
