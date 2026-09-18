import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "security-tool-gateway"))
# Importing app.store instantiates a module-level store that mkdirs the
# CYBERGUARD_DATA_DIR default ("/data"); point it at a writable temp dir before
# any import happens (mirrors tests/test_security_gateway.py).
os.environ.setdefault("CYBERGUARD_DATA_DIR",
                      str(Path(tempfile.gettempdir()) / "cyberguard-ingest-test-data"))
os.environ.setdefault("CYBERGUARD_ACTION_AUDIT_FILE",
                      str(Path(tempfile.gettempdir()) / "cyberguard-ingest-test-actions.jsonl"))
os.environ.setdefault("CYBERGUARD_LIVE_CONNECTORS_FILE",
                      str(Path(tempfile.gettempdir()) / "cyberguard-ingest-test-connectors.json"))
SCRIPT = ROOT / "scripts" / "ingest-suricata.py"
SAMPLE = ROOT / "samples" / "suricata" / "eve-sample.jsonl"


def load_module():
    spec = importlib.util.spec_from_file_location("ingest_suricata", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_ingest(*arguments: str, expect_success: bool = True):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
    )
    if expect_success:
        assert result.returncode == 0, result.stderr
    return result


def read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class IngestSuricataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name)

    def run_sample(self, *extra: str) -> dict:
        result = run_ingest(
            "--input", str(SAMPLE), "--incident", "CG-SURICATA-TEST",
            "--data-dir", str(self.data_dir), "--environment", "fixture", *extra,
        )
        return json.loads(result.stdout)

    def test_ingests_alerts_as_contract_valid_evidence(self) -> None:
        summary = self.run_sample()
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["events_read"], 12)
        self.assertEqual(summary["converted"], 5)
        self.assertEqual(summary["skipped"]["non_alert"], 5)
        self.assertEqual(summary["skipped"]["stats"], 1)
        self.assertEqual(summary["skipped"]["flow_excluded"], 1)
        self.assertGreater(summary["quality"]["min"], 0.7)
        self.assertEqual(summary["quality"]["pass"], 5)

        records = read_records(self.data_dir / "evidence.jsonl")
        self.assertEqual(len(records), 5)
        for record in records:
            self.assertEqual(record["incident_id"], "CG-SURICATA-TEST")
            self.assertEqual(record["source"], "network-sensor/suricata")
            self.assertEqual(record["kind"], "network_alert")
            self.assertEqual(record["environment"], "fixture")
            self.assertEqual(record["standard"]["schema"], "cyberguard-security-observation")
            self.assertRegex(record["sha256"], r"^[a-f0-9]{64}$")
            self.assertRegex(record["evidence_id"], r"^EV-[a-f0-9]{12}$")
            self.assertRegex(record["envelope_sha256"], r"^[a-f0-9]{64}$")
            self.assertTrue(record["entities"])
            self.assertTrue(record["observables"])
            self.assertIn("ipv4-addr", {item["stix_type"] for item in record["observables"]})
            self.assertRegex(record["entities"][0]["entity_id"], r"^ENT-[a-f0-9]{16}$")
            self.assertGreaterEqual(record["quality"]["score"], 0.0)
            self.assertLessEqual(record["quality"]["score"], 1.0)
        # Severity 1 alert (official doc example) maps to 0.9 confidence.
        high = [r for r in records if r["confidence"] == 0.9]
        self.assertEqual(len(high), 2)

    def test_attack_mapping_is_inferred_only_where_defensible(self) -> None:
        records = self.run_sample_and_read()
        scan = [r for r in records if "SSH Scan" in r["data"]["signature"]]
        self.assertEqual(len(scan), 1)
        self.assertEqual(scan[0]["attack_techniques"], ["T1046"])
        # Official trojan-detection alert: no defensible technique -> empty list
        # plus a recorded quality issue, never an invented mapping.
        trojan = [r for r in records if "LeftHook" in r["data"]["signature"]]
        self.assertEqual(trojan[0]["attack_techniques"], [])
        self.assertIn("no_attack_mapping", trojan[0]["quality"]["issues"])

    def test_dry_run_validates_without_writing(self) -> None:
        summary = self.run_sample("--dry-run")
        self.assertEqual(summary["status"], "ok_dry_run")
        self.assertEqual(summary["converted"], 5)
        self.assertEqual(summary["appended"], 0)
        self.assertFalse((self.data_dir / "evidence.jsonl").exists())

    def test_repeat_run_is_idempotent_by_content_sha(self) -> None:
        self.run_sample()
        before = read_records(self.data_dir / "evidence.jsonl")
        summary = self.run_sample()
        self.assertEqual(summary["appended"], 0)
        self.assertEqual(summary["skipped"]["duplicate"], 5)
        after = read_records(self.data_dir / "evidence.jsonl")
        self.assertEqual(before, after)

    def test_include_flows_also_converts_flow_summaries(self) -> None:
        summary = self.run_sample("--include-flows")
        self.assertEqual(summary["converted"], 6)
        records = read_records(self.data_dir / "evidence.jsonl")
        flows = [r for r in records if r["kind"] == "network_flow"]
        self.assertEqual(len(flows), 1)
        self.assertEqual(flows[0]["data"]["bytes_toserver"], 3536402)

    def test_incident_visible_through_gateway_store(self) -> None:
        self.run_sample("--include-flows")
        from app.store import ScenarioStore

        with patch.dict(os.environ, {"CYBERGUARD_DATA_DIR": str(self.data_dir)}):
            store = ScenarioStore()
            incidents = {item["incident_id"]: item for item in store.list_incidents()}
        summary = incidents["CG-SURICATA-TEST"]
        self.assertEqual(summary["evidence_count"], 6)
        self.assertEqual(summary["sources"], ["network-sensor/suricata"])
        self.assertGreaterEqual(summary["entity_count"], 1)
        self.assertEqual(summary["attack_techniques"], ["T1046"])
        self.assertIsNotNone(summary["quality_mean"])
        flow_records = [item for item in store.list_evidence("CG-SURICATA-TEST")
                        if item["kind"] == "network_flow"]
        self.assertEqual(flow_records[0]["data"]["bytes_toserver"], 3536402)

    def test_workflow_flag_records_investigating_state(self) -> None:
        self.run_sample("--workflow")
        events = read_records(self.data_dir / "workflow.jsonl")
        self.assertEqual([event["state"] for event in events], ["received", "investigating"])
        self.assertEqual(events[-1]["session_id"], "ingest-suricata")
        rerun = self.run_sample("--workflow")
        self.assertEqual(rerun["workflow"], "already_present")
        self.assertEqual(len(read_records(self.data_dir / "workflow.jsonl")), 2)

    def test_malformed_lines_are_skipped_not_fatal(self) -> None:
        bad = self.data_dir / "eve-bad.jsonl"
        alert = json.loads(SAMPLE.read_text(encoding="utf-8").splitlines()[0])
        bad.write_text("not-json\n\n" + json.dumps(alert) + "\n", encoding="utf-8")
        result = run_ingest("--input", str(bad), "--incident", "CG-SURICATA-BAD",
                            "--data-dir", str(self.data_dir / "sub"), "--environment", "fixture")
        summary = json.loads(result.stdout)
        self.assertEqual(summary["converted"], 1)
        self.assertEqual(summary["skipped"]["invalid"], 1)

    def test_mapping_table_never_invents_techniques(self) -> None:
        module = load_module()
        self.assertEqual(module.map_attack_techniques("ET ATTACK_RESPONSE Win32/LeftHook", "A Network Trojan was detected"), [])
        self.assertEqual(module.map_attack_techniques("ET HUNTING GENERIC SUSPICIOUS POST", "Potentially Bad Traffic"), [])
        self.assertEqual(module.map_attack_techniques("", None), [])
        self.assertEqual(module.map_attack_techniques("ET SCAN Potential SSH Scan", None), ["T1046"])
        self.assertEqual(module.map_attack_techniques("ET COMPROMISED Possible SSH Brute Force", None), ["T1110"])
        self.assertEqual(module.map_attack_techniques("SQL Injection Attempt Against Web Server", None), ["T1190"])

    def run_sample_and_read(self) -> list[dict]:
        self.run_sample()
        return read_records(self.data_dir / "evidence.jsonl")


if __name__ == "__main__":
    unittest.main()
