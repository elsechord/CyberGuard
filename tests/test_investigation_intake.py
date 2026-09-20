"""Intake trust boundaries and deterministic source preservation."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "services/operations-console/app/intake.py"
SPEC = importlib.util.spec_from_file_location("investigation_intake", PATH)
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)


def submission():
    return {"title": "Review", "objective": "Compare source statements", "domain": "general",
            "materials": [{"source_type": "agent", "name": "source", "content": "  原始材料\n",
                           "media_type": "text/plain", "interpretation": "Claim from producer",
                           "source_uri": "https://example.invalid/private"}]}


class IntakeTests(unittest.TestCase):
    def test_source_preserved_and_claims_separate_without_mutation(self):
        raw = submission()
        original = copy.deepcopy(raw)
        value = intake.validate_submission(raw)
        self.assertEqual(raw, original)
        material = value["materials"][0]
        self.assertEqual(material["content"], raw["materials"][0]["content"])
        self.assertEqual(material["interpretation"], "Claim from producer")
        self.assertEqual(material["sha256"], hashlib.sha256(material["content"].encode()).hexdigest())
        self.assertEqual(material["source_authenticity"], "unverified")
        self.assertEqual(material["submitted_as"], "original_input")
        self.assertNotIn("submitted_by", material)

    def test_determinism_and_interpretation_not_source_identity(self):
        raw = submission()
        first = intake.validate_submission(raw)
        self.assertEqual(first, intake.validate_submission(dict(reversed(list(raw.items())))))
        raw["materials"][0]["interpretation"] = "Changed opinion"
        second = intake.validate_submission(raw)
        self.assertEqual(first["materials"][0]["material_id"], second["materials"][0]["material_id"])
        self.assertNotEqual(first["request_fingerprint"], second["request_fingerprint"])
        raw["materials"][0]["content"] += "!"
        self.assertNotEqual(second["materials"][0]["material_id"],
                            intake.validate_submission(raw)["materials"][0]["material_id"])

    def test_duplicates_rejected_even_when_commentary_differs(self):
        raw = submission()
        raw["materials"].append(dict(raw["materials"][0], interpretation="Another claim"))
        with self.assertRaisesRegex(ValueError, "Duplicate material"):
            intake.validate_submission(raw)

    def test_byte_limits_control_data_and_aggregate(self):
        for content in ("中" * 45000, "abc\x00def", b"binary", "\ud800"):
            raw = submission()
            raw["materials"][0]["content"] = content
            with self.assertRaises(ValueError):
                intake.validate_submission(raw)
        raw = submission()
        raw["materials"] = [dict(raw["materials"][0], name=str(i), content="a" * 120000)
                            for i in range(9)]
        with self.assertRaisesRegex(ValueError, "aggregate"):
            intake.validate_submission(raw)

    def test_forged_trust_unsupported_formats_and_malformed_input(self):
        for key, value in (("source_authenticity", "verified"), ("submitted_by", "admin"),
                           ("media_type", "application/pdf"), ("source_type", "trusted_agent")):
            raw = submission()
            raw["materials"][0][key] = value
            with self.assertRaises(ValueError):
                intake.validate_submission(raw)
        for key, value in (("domain", []), ("objective", " "), ("materials", []),
                           ("title", "x" * 201)):
            raw = submission()
            raw[key] = value
            with self.assertRaises(ValueError):
                intake.validate_submission(raw)

    def test_all_domains_and_source_types_remain_unverified(self):
        for domain in intake.DOMAINS:
            for source_type in intake.SOURCE_TYPES:
                raw = submission()
                raw["domain"] = domain
                raw["materials"][0]["source_type"] = source_type
                value = intake.validate_submission(raw)
                self.assertEqual(value["materials"][0]["source_authenticity"], "unverified")


if __name__ == "__main__":
    unittest.main()
