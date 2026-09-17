import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("generate_source_sbom", ROOT / "scripts" / "generate-source-sbom.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SourceSbomTests(unittest.TestCase):
    def test_document_is_deterministic_and_has_required_components(self):
        first = MODULE.build_document()
        second = MODULE.build_document()
        self.assertEqual(first, second)
        self.assertEqual(first["spdxVersion"], "SPDX-2.3")
        names = {package["name"] for package in first["packages"]}
        self.assertTrue({"CyberGuard", "fastapi", "uvicorn", "pydantic", "starlette", "anyio", "python:3.12.14-slim-bookworm", "agentscope-ai/AgentTeams"} <= names)
        project = next(package for package in first["packages"] if package["name"] == "CyberGuard")
        self.assertEqual(project["versionInfo"], (ROOT / "VERSION").read_text().strip())

    def test_output_is_valid_json_with_unique_spdx_ids(self):
        document = MODULE.build_document()
        encoded = json.dumps(document)
        decoded = json.loads(encoded)
        identifiers = [package["SPDXID"] for package in decoded["packages"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(len(decoded["relationships"]), len(decoded["packages"]))

    def test_container_purl_separates_repository_tag_and_digest(self):
        document = MODULE.build_document()
        image = next(package for package in document["packages"] if package["name"].startswith("python:"))
        purl = image["externalRefs"][0]["referenceLocator"]
        self.assertRegex(purl, r"^pkg:docker/python@sha256:[0-9a-f]{64}\?tag=3\.12\.13-slim-bookworm$")


if __name__ == "__main__":
    unittest.main()
