"""Evidence integrity, bounded untrusted imports and read-only collection boundaries."""
import copy
import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation import evidence
from cyberguard_investigation import collector


def bundle():
    return evidence.make_bundle([evidence.make_artifact("processes", "/proc", {"processes": []})],
                                provenance={"kind": "exercise"})


def proc_stat(pid=41, ticks=20, start=100):
    fields = ["S", "1"] + ["0"] * 22
    fields[11], fields[12], fields[19] = str(ticks), "0", str(start)
    return f"{pid} (worker (safe)) " + " ".join(fields)


class EvidenceTests(unittest.TestCase):
    def test_roundtrip_canonical_unicode_and_integrity(self):
        value = bundle()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(value, indent=2), encoding="utf-8")
            self.assertEqual(evidence.load_bundle(path), value)
        artifact = evidence.make_artifact("日志", "test", {"z": 1, "a": "你好"})
        expected = {k: v for k, v in artifact.items() if k != "sha256"}
        self.assertEqual(artifact["sha256"], hashlib.sha256(json.dumps(expected, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_artifact_tamper_even_if_outer_hash_recomputed(self):
        value = bundle()
        value["artifacts"][0]["data"]["processes"] = [{"pid": 99}]
        value["bundle_sha256"] = evidence._digest(value, "bundle_sha256")
        with self.assertRaisesRegex(ValueError, "Artifact SHA256 mismatch"):
            evidence.validate_bundle(value)

    def test_provenance_tamper_and_duplicate_ids_rejected(self):
        value = bundle()
        value["provenance"]["kind"] = "live_collection"
        with self.assertRaisesRegex(ValueError, "Bundle SHA256 mismatch"):
            evidence.validate_bundle(value)
        value = bundle()
        value["artifacts"].append(copy.deepcopy(value["artifacts"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate evidence_id"):
            evidence.validate_bundle(value)

    def test_oversize_duplicate_json_nonfinite_depth_and_fields_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_bytes(b" " * (evidence.MAX_BUNDLE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "byte limit"):
                evidence.load_bundle(path)
            path.write_text('{"schema":1,"schema":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                evidence.load_bundle(path)
        with self.assertRaises(ValueError):
            evidence.make_artifact("test", "test", {"n": math.nan})
        deep = {}
        for _ in range(35):
            deep = {"nested": deep}
        with self.assertRaisesRegex(ValueError, "structure"):
            evidence.make_artifact("test", "test", deep)
        value = bundle()
        value["extra"] = True
        with self.assertRaisesRegex(ValueError, "envelope"):
            evidence.validate_bundle(value)

    def test_unavailable_is_explicit_and_not_a_clean_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            value = collector.collect_linux(proc_root=Path(directory) / "missing", observation_seconds=0.01)
        self.assertEqual(value["provenance"]["kind"], "exercise")
        self.assertTrue(all(a["status"] == "unavailable" for a in value["artifacts"]))
        self.assertTrue(all(a["data"]["coverage"]["complete"] is False for a in value["artifacts"]))
        self.assertNotIn("verdict", value)

    def test_process_parent_uid_cpu_and_secret_files_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "41"
            proc.mkdir()
            (proc / "stat").write_text(proc_stat(), encoding="utf-8")
            (proc / "status").write_text("Uid:\t1000\t1000\t1000\t1000\n", encoding="utf-8")
            (proc / "cmdline").write_text("SUPER_SECRET_PASSWORD", encoding="utf-8")
            (proc / "environ").write_text("SUPER_SECRET_API_KEY", encoding="utf-8")
            def tick(_):
                (proc / "stat").write_text(proc_stat(ticks=25), encoding="utf-8")
            with patch.object(collector.time, "sleep", side_effect=tick), patch.object(collector.os, "readlink", return_value="/tmp/task"):
                artifact, paths = collector._processes(root, 0.01, 10)
            row = artifact["data"]["processes"][0]
            self.assertEqual((row["pid"], row["ppid"], row["uid"], row["exe"]), (41, 1, 1000, "/tmp/task"))
            self.assertGreater(row["cpu_percent"], 0)
            self.assertEqual(row["comm"], "worker (safe)")
            self.assertNotIn("SUPER_SECRET", json.dumps(artifact))

    def test_pid_reuse_does_not_join_two_process_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory) / "41"
            proc.mkdir()
            (proc / "stat").write_text(proc_stat(), encoding="utf-8")
            def replace(_):
                (proc / "stat").write_text(proc_stat(start=101), encoding="utf-8")
            with patch.object(collector.time, "sleep", side_effect=replace):
                artifact, _ = collector._processes(Path(directory), 0.01, 10)
            self.assertEqual(artifact["status"], "unavailable")
            self.assertEqual(artifact["data"]["coverage"]["unreadable_or_changed_processes"], 1)

    def test_network_endpoints_and_explicit_missing_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "net").mkdir()
            (root / "net" / "tcp").write_text("sl local_address rem_address st tx rx tr tm retr uid timeout inode\n"
                "0: 0100007F:1F90 08080808:01BB 01 0:0 0:0 0 1000 0 555\n", encoding="ascii")
            artifacts = collector._network(root, [])
            row = artifacts[0]["data"]["connections"][0]
            self.assertEqual((row["local_address"], row["local_port"], row["remote_port"]), ("127.0.0.1", 8080, 443))
            self.assertEqual(row["owner_pids"], [])
            self.assertFalse(artifacts[0]["data"]["coverage"]["ownership_complete"])
            self.assertTrue(all(a["status"] == "unavailable" for a in artifacts[1:]))

    def test_explicit_configs_drop_arguments_and_never_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "task.service"
            path.write_text("[Service]\nExecStart=/tmp/task --token MY_SECRET\nEnvironment=API_KEY=MY_SECRET\n", encoding="utf-8")
            artifact = collector._file_artifact(path, "persistence", 65536)
            entry = artifact["data"]["entries"][0]
            self.assertEqual(entry["command"], "/tmp/task")
            self.assertIsNone(entry["enabled"])
            self.assertNotIn("MY_SECRET", json.dumps(artifact))

    def test_log_redaction_truncation_and_nonregular_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.log"
            path.write_text("token=abc123 Authorization: Bearer ABCDEF\n" + "\n" * 2000, encoding="utf-8")
            artifact = collector._file_artifact(path, "auth_logs", 65536)
            self.assertLessEqual(len(artifact["data"]["events"]), 1024)
            self.assertTrue(artifact["data"]["coverage"]["truncated"])
            self.assertNotIn("abc123", json.dumps(artifact))
            self.assertNotIn("ABCDEF", json.dumps(artifact))
            self.assertEqual(collector._file_artifact(Path(directory), "auth_logs", 65536)["status"], "unavailable")

    def test_limits_and_unrequested_sources(self):
        with self.assertRaises(ValueError):
            collector.collect_linux(max_processes=10000)
        with self.assertRaises(ValueError):
            collector.collect_linux(config_paths=["x"] * 33)
        with self.assertRaises(ValueError):
            evidence.make_artifact("test", "test", {"large": "x" * evidence.MAX_ARTIFACT_BYTES})


if __name__ == "__main__":
    unittest.main()
