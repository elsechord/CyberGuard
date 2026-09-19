"""Portable installation and real loopback HTTP behavior; no models or customer data."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'integrations/agent-skills/cyberguard/scripts/cyberguard.py'
INSTALLER = ROOT / 'scripts/install-agent-skill.py'
spec = importlib.util.spec_from_file_location('external_client', CLIENT)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class PortableSkillTests(unittest.TestCase):
    def test_install_and_run_outside_source_tree(self):
        for agent, folder in [('codex', '.agents'), ('claude', '.claude'), ('generic', '.agents')]:
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                command = [sys.executable, str(INSTALLER), '--agent', agent, '--project', directory]
                install = subprocess.run(command, cwd=directory, capture_output=True, text=True)
                self.assertEqual(install.returncode, 0, install.stderr)
                skill = project / folder / 'skills/cyberguard'
                self.assertTrue((skill / 'SKILL.md').is_file())
                self.assertTrue((skill / 'LICENSE').is_file())
                script = str(skill / 'scripts/cyberguard.py')
                snapshot = project / 'exercise.json'
                run = subprocess.run([sys.executable, script, 'demo', '--out', str(snapshot)],
                                     cwd=directory, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(run.stdout)
                self.assertEqual(result['evidence_count'], 2)
                self.assertFalse(result['actions_executed_by_client'])
                check = subprocess.run([sys.executable, script, 'inspect', str(snapshot)],
                                       cwd=directory, capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stderr)
                before = snapshot.read_bytes()
                again = subprocess.run([sys.executable, script, 'demo', '--out', str(snapshot)],
                                       cwd=directory, capture_output=True, text=True)
                self.assertNotEqual(again.returncode, 0)
                self.assertEqual(snapshot.read_bytes(), before)
                self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_inconsistent_and_ambiguous_evidence(self):
        original = client.demo()
        for mutation in ('tamper', 'cross_incident', 'duplicate'):
            with self.subTest(mutation=mutation):
                payload = copy.deepcopy(original)
                if mutation == 'tamper':
                    payload['evidence'][0]['data']['cpu_percent'] = 1
                elif mutation == 'cross_incident':
                    payload['evidence'][0]['incident_id'] = 'OTHER'
                else:
                    payload['evidence'].append(copy.deepcopy(payload['evidence'][0]))
                with self.assertRaises(client.ClientError):
                    client.inspect(payload)
        with self.assertRaises(client.ClientError):
            client.inspect(original, 'OTHER')
        original['evidence'] = []
        self.assertEqual(client.inspect(original)['evidence_count'], 0)
        payload = client.demo()
        del payload['evidence'][0]['envelope_sha256']
        self.assertEqual(client.inspect(payload)['records'][0]['envelope_digest'], 'not_available')

    def test_origin_and_json_rejections(self):
        for origin in ['http://example.com', 'https://u:p@example.com',
                       'https://example.com/path', 'https://example.com?token=secret']:
            with self.subTest(origin=origin), self.assertRaises(client.ClientError):
                client.origin_url(origin)
        for raw in ['{"data":1,"data":2}', '{"value":NaN}', 'not json']:
            with self.subTest(raw=raw), self.assertRaises(client.ClientError):
                client.decode(raw)

    def test_live_get_and_redirect_refusal(self):
        payload = client.demo()
        fake_key = 'cg_live_' + 'test_only_' * 4
        requests = []
        mode = {'value': 'ok'}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers.get('Authorization') == 'Bearer ' + fake_key))
                if mode['value'] == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/credential-sink')
                    self.end_headers()
                elif mode['value'] == 'denied':
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(fake_key.encode())
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'data': payload}).encode())

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                key_file = Path(directory) / 'key.txt'
                key_file.write_text(fake_key, encoding='utf-8')
                env = {'CYBERGUARD_CONSOLE_URL': f'http://127.0.0.1:{server.server_port}',
                       'CYBERGUARD_SKILL_KEY_FILE': str(key_file)}
                with patch.dict(os.environ, env):
                    self.assertEqual(client.fetch('CG-SKILL-EXERCISE')['data'], payload)
                    self.assertEqual(requests, [('/api/v1/incidents/CG-SKILL-EXERCISE', True)])
                    with self.assertRaises(client.ClientError):
                        client.fetch('OTHER')
                    mode['value'] = 'redirect'
                    with self.assertRaisesRegex(client.ClientError, 'Redirect refused'):
                        client.fetch('CG-SKILL-EXERCISE')
                    self.assertFalse(any(path == '/credential-sink' for path, _ in requests))
                    mode['value'] = 'denied'
                    run = subprocess.run([sys.executable, str(CLIENT), 'fetch', 'CG-SKILL-EXERCISE',
                                          '--out', str(Path(directory) / 'unused.json')],
                                         capture_output=True, text=True)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn('403', run.stderr)
                    self.assertNotIn(fake_key, run.stdout + run.stderr)
                    self.assertFalse((Path(directory) / 'unused.json').exists())
                    os.environ['CYBERGUARD_SKILL_KEY_FILE'] = ''
                    with self.assertRaisesRegex(client.ClientError, 'KEY_FILE'):
                        client.fetch('CG-SKILL-EXERCISE')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
