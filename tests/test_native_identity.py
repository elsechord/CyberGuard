import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'deploy/investigation-service/collaboration/native_identity.py'
spec = importlib.util.spec_from_file_location('native_identity', PATH)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


class NativeIdentityTests(unittest.TestCase):
    def test_only_known_local_control_plane_route_is_corrected(self):
        self.assertEqual(identity.normalize_local_gateway('http://agentteams-controller:8080/cg-guard/worker/v1'),
                         'http://aigw-local.agentteams.io:8080/cg-guard/worker/v1')
        for url in ('https://example.com/v1', 'http://agentteams-controller:8080/api',
                    'http://agentteams-controller:8090/cg-guard/worker', ''):
            self.assertEqual(identity.normalize_local_gateway(url), url)

    def test_worker_name_resolves_to_actual_address(self):
        members = [{'name': 'investigator', 'matrixUserId': '@reader:matrix'}]
        self.assertEqual(identity.resolve_matrix_user_id('investigator', members), '@reader:matrix')
        self.assertEqual(identity.resolve_matrix_user_id('@reader:matrix', members), '@reader:matrix')

    def test_unknown_and_ambiguous_names_cannot_be_sent(self):
        for value, members in [('', []), ('missing', []), ('reader', [
            {'name': 'reader', 'matrixUserId': '@one:matrix'},
            {'runtimeName': 'reader', 'matrixUserId': '@two:matrix'}])]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                identity.resolve_matrix_user_id(value, members)

    def test_patch_is_idempotent_and_requires_known_native_anchor(self):
        source = '            assignment_mxid = str(assigned_to or "").strip()\n'
        patched = identity.patch_native_source(source)
        self.assertEqual(identity.patch_native_source(patched), patched)
        with self.assertRaises(ValueError):
            identity.patch_native_source('different native implementation')


if __name__ == '__main__':
    unittest.main()
