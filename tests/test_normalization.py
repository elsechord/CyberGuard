import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "security-tool-gateway"))

from app.normalization import extract_entities, extract_observables, normalize  # noqa: E402


class NormalizationTests(unittest.TestCase):
    def test_entity_ids_correlate_vendor_specific_host_fields(self) -> None:
        host = extract_entities({"host": "FIN-LT-023"})[0]
        source_host = extract_entities({"src_host": "fin-lt-023"})[0]
        self.assertEqual(host["entity_id"], source_host["entity_id"])
        self.assertEqual(host["type"], "device")

    def test_observables_use_stix_object_types_and_deduplicate(self) -> None:
        items = extract_observables({
            "src_ip": "198.51.100.27", "dst_ips": ["198.51.100.27", "2001:db8::1"],
            "url": "https://updates.example.invalid/a", "dst_domain": "updates.example.invalid",
        })
        self.assertEqual(
            {item["stix_type"] for item in items},
            {"ipv4-addr", "ipv6-addr", "url", "domain-name"},
        )
        self.assertEqual(len([item for item in items if item["value"] == "198.51.100.27"]), 1)

    def test_quality_reports_invalid_timestamp_and_attack_mapping(self) -> None:
        result = normalize("alert.snapshot", {
            "source": "siem", "kind": "alert", "summary": "test", "confidence": 0.9,
            "observed_at": "not-a-time", "attack_techniques": ["TA0001", "T1078"],
            "data": {"account": "finance-ops"},
        }, "a" * 64)
        self.assertIn("invalid_observed_at", result["quality"]["issues"])
        self.assertIn("invalid_attack_technique_id", result["quality"]["issues"])
        self.assertEqual(result["attack_techniques"], ["T1078"])
        self.assertEqual(result["standard"]["raw_sha256"], "a" * 64)

    def test_sparse_record_is_marked_for_review(self) -> None:
        result = normalize("alert.snapshot", {
            "source": "siem", "kind": "alert", "summary": "test", "confidence": 0.7,
            "data": {"alerts": ["A-1"]},
        }, "b" * 64)
        self.assertEqual(result["quality"]["gate"], "review")
        self.assertLess(result["quality"]["score"], 0.7)


if __name__ == "__main__":
    unittest.main()
