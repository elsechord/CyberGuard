"""Fake-client tests of the exact replacement method, without QwenPaw or Docker."""
import ast
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import textwrap
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("readiness_patch", Path(__file__).with_name("patch-qwenpaw-readiness.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self, late=0):
        self.late = late
        self.calls = []
        self.after_read = lambda: None

    def require_version(self, version):
        self.calls.append(("version", version))

    def list_mcp(self):
        self.calls.append(("list_mcp",))
        if self.late:
            self.late -= 1
            raise TimeoutError("Workspace still starting")
        self.after_read()
        return []


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        namespace = {"asyncio": asyncio}
        exec(compile(ast.parse(textwrap.dedent(module.REPLACEMENT)), "<exact-readiness-patch>", "exec"), namespace)
        self.wait_ready = namespace["_wait_for_qwenpaw_api"]
        self.client = FakeClient()
        self.worker = SimpleNamespace(api_client=self.client, _process=SimpleNamespace(returncode=None))

    async def test_version_ready_but_workspace_late_retries_reads_only(self):
        self.client.late = 2
        real_sleep = asyncio.sleep
        delays = []
        async def fast_sleep(delay):
            delays.append(delay)
            await real_sleep(0)
        with patch.object(asyncio, "sleep", fast_sleep):
            await self.wait_ready(self.worker)
        self.assertEqual(delays, [0.5, 0.5])
        self.assertEqual(self.client.calls, [("version", "2.0.1"), ("list_mcp",)] * 3)

    async def test_exited_process_never_probes_management(self):
        self.worker._process.returncode = 7
        with self.assertRaisesRegex(RuntimeError, "exited before API readiness: 7"):
            await self.wait_ready(self.worker)
        self.assertEqual(self.client.calls, [])

    async def test_exit_during_read_is_not_mistaken_for_ready(self):
        self.client.after_read = lambda: setattr(self.worker._process, "returncode", 3)
        with self.assertRaisesRegex(RuntimeError, "exited before API readiness: 3"):
            await self.wait_ready(self.worker)

    async def test_total_deadline_cancels_coroutine_with_read_thread_still_in_flight(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        deadline = None
        def delayed_read():
            entered.set()
            # Start the simulated deadline only after the thread actually starts;
            # otherwise slow Windows executor startup can expire before this probe.
            loop.call_soon_threadsafe(deadline.reschedule, loop.time() + 0.01)
            release.wait(1)
            finished.set()
            return []
        self.client.list_mcp = delayed_read
        real_timeout = asyncio.timeout
        def shortened_timeout(seconds):
            nonlocal deadline
            self.assertEqual(seconds, 120)
            deadline = real_timeout(None)
            return deadline
        try:
            with patch.object(asyncio, "timeout", shortened_timeout):
                with self.assertRaisesRegex(RuntimeError, "readiness exceeded 120 seconds"):
                    await asyncio.wait_for(self.wait_ready(self.worker), timeout=2)
            self.assertTrue(entered.is_set())
            self.assertFalse(finished.is_set())
        finally:
            release.set()
            await asyncio.to_thread(finished.wait, 1)

    async def test_external_cancellation_is_not_retried(self):
        entered, release = threading.Event(), threading.Event()
        def delayed_read():
            entered.set()
            release.wait(1)
        self.client.list_mcp = delayed_read
        task = asyncio.create_task(self.wait_ready(self.worker))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(self.client.calls, [("version", "2.0.1")])
        finally:
            release.set()


class StrictReplacementTests(unittest.TestCase):
    def test_only_expected_method_changes(self):
        before = "import asyncio\nclass Worker:\n" + module.ORIGINAL + "\n    untouched = True\n"
        after = module.patched_source(before)
        self.assertEqual(after, "import asyncio\nclass Worker:\n" + module.REPLACEMENT + "\n    untouched = True\n")
        with self.assertRaises(ValueError):
            module.patched_source(after)

    def test_source_drift_and_duplicate_method_fail_closed(self):
        for source in (module.ORIGINAL.replace("+ 60", "+ 61"), module.ORIGINAL * 2):
            with self.assertRaises(ValueError):
                module.patched_source(source)


if __name__ == "__main__":
    unittest.main()
