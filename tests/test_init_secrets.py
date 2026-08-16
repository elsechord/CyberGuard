import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("init_secrets", ROOT / "deploy" / "init_secrets.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class InitSecretsTests(unittest.TestCase):
    def test_render_replaces_all_secrets_with_distinct_long_values(self):
        template = (ROOT / ".env.example").read_text(encoding="utf-8")
        rendered = MODULE.render(template)
        values = {}
        for line in rendered.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        secrets = [values[key] for key in MODULE.SECRET_KEYS]
        self.assertEqual(len(set(secrets)), 5)
        self.assertTrue(all(len(value) >= 48 for value in secrets))
        self.assertNotIn("replace-with-", rendered)

    def test_create_is_atomic_locked_down_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / ".env"
            MODULE.create(ROOT / ".env.example", output)
            if os.name != "nt":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                MODULE.create(ROOT / ".env.example", output)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
