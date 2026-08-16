import importlib.util
import io
import urllib.error
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("llm_preflight", ROOT / "deploy" / "llm_preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(preflight)


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class LLMPreflightTests(unittest.TestCase):
    def test_success_sends_secret_only_in_authorization_header(self):
        seen = {}

        def opener(request, timeout):
            seen["authorization"] = request.headers["Authorization"]
            seen["body"] = request.data
            seen["timeout"] = timeout
            return FakeResponse()

        preflight.probe_provider(
            "https://provider.example/v1", "sk-secret", "model-a", opener=opener
        )
        self.assertEqual(seen["authorization"], "Bearer sk-secret")
        self.assertNotIn(b"sk-secret", seen["body"])

    def test_unauthorized_fails_without_retry_and_redacts_secret(self):
        calls = 0

        def opener(_request, timeout):
            del timeout
            nonlocal calls
            calls += 1
            raise urllib.error.HTTPError(
                "https://provider.example", 401, "Unauthorized", {}, io.BytesIO(b"bad sk-secret")
            )

        with self.assertRaises(preflight.LLMPreflightError) as caught:
            preflight.probe_provider(
                "https://provider.example/v1", "sk-secret", "model-a", retries=3, opener=opener
            )
        self.assertEqual(calls, 1)
        self.assertEqual(caught.exception.category, "authentication")
        self.assertNotIn("sk-secret", str(caught.exception))

    def test_transient_failure_is_retried(self):
        calls = 0

        def opener(_request, timeout):
            del timeout
            nonlocal calls
            calls += 1
            if calls == 1:
                raise urllib.error.HTTPError(
                    "https://provider.example", 503, "Unavailable", {}, io.BytesIO(b"busy")
                )
            return FakeResponse()

        preflight.probe_provider(
            "https://provider.example/v1",
            "sk-secret",
            "model-a",
            retries=1,
            opener=opener,
            sleep=lambda _delay: None,
        )
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
