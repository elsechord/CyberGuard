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
                version = subprocess.run([sys.executable, script, '--version'],
                                         cwd=directory, capture_output=True, text=True)
                self.assertEqual(version.returncode, 0, version.stderr)
                self.assertEqual(version.stdout.strip(), 'cyberguard 0.2.0')
                help_result = subprocess.run([sys.executable, script, 'check', '--help'],
                                             cwd=directory, capture_output=True, text=True)
                self.assertEqual(help_result.returncode, 0, help_result.stderr)
                self.assertIn('check', help_result.stdout)
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

    def test_connection_check_status_and_secret_safety(self):
        fake_key = 'cg_live_' + 'private_test_' * 3
        requests = []
        reply = {'status': 200, 'body': {'data': []}}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                requests.append((self.path, self.headers.get('Authorization') == 'Bearer ' + fake_key))
                self.send_response(reply['status'])
                if reply['status'] == 302:
                    self.send_header('Location', '/credential-sink')
                self.end_headers()
                self.wfile.write(json.dumps(reply['body']).encode())

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                key_file = Path(directory) / 'private-key.txt'
                key_file.write_text(fake_key, encoding='utf-8')
                env = dict(os.environ, CYBERGUARD_CONSOLE_URL=f'http://127.0.0.1:{server.server_port}',
                           CYBERGUARD_SKILL_KEY_FILE=str(key_file),
                           HTTP_PROXY='http://127.0.0.1:1', HTTPS_PROXY='http://127.0.0.1:1', NO_PROXY='')

                def run_check():
                    result = subprocess.run([sys.executable, str(CLIENT), 'check'], env=env,
                                            cwd=directory, capture_output=True, text=True)
                    self.assertNotIn(fake_key, result.stdout + result.stderr)
                    self.assertNotIn(str(key_file), result.stdout + result.stderr)
                    self.assertEqual(list(Path(directory).iterdir()), [key_file])
                    return result

                for incidents in ([], [{'incident_id': 'CG-PRIVATE', 'summary': fake_key}]):
                    with self.subTest(incidents_available=bool(incidents)):
                        reply['body'] = {'data': incidents}
                        result = run_check()
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout), {
                            'connection': 'ok', 'authenticated': True, 'incidents_read': True,
                            'incidents_available': bool(incidents), 'actions_executed_by_client': False})
                        self.assertNotIn('CG-PRIVATE', result.stdout)

                for status, expected in [(401, 'key was not accepted'), (403, 'access was denied'),
                                         (502, 'upstream service failed'), (302, 'Redirect refused')]:
                    with self.subTest(status=status):
                        reply.update(status=status, body={'error': fake_key})
                        result = run_check()
                        self.assertEqual(result.returncode, 2)
                        self.assertEqual(result.stdout, '')
                        self.assertIn(expected, result.stderr)

                reply['status'] = 200
                for invalid in ({'data': {}}, {'data': [None]}, {'data': [{}]},
                                {'data': [], 'error': fake_key}, {'summary': {}}, None):
                    with self.subTest(invalid=invalid):
                        reply['body'] = invalid
                        result = run_check()
                        self.assertEqual(result.returncode, 2)
                        self.assertEqual(result.stdout, '')
                        self.assertIn('connection check did not succeed', result.stderr)
                self.assertTrue(all(item == ('/api/v1/incidents?limit=1', True) for item in requests))

                env['CYBERGUARD_SKILL_KEY_FILE'] = ''
                before = len(requests)
                result = run_check()
                self.assertEqual(result.returncode, 2)
                self.assertIn('KEY_FILE', result.stderr)
                self.assertEqual(len(requests), before)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class InvestigationLifecycleTests(unittest.TestCase):
    def test_real_http_submission_status_result_and_cancel(self):
        requests = []
        state = {'status': 'queued', 'code': 200}
        secret = 'cg_live_' + 'synthetic_only_' * 3

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, post=False):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if post else b''
                requests.append((self.command, self.path, self.headers.get('Idempotency-Key'), body))
                self.send_response(state['code'] if state['code'] != 200 else (202 if post else 200))
                if state['code'] == 302:
                    self.send_header('Location', '/credential-sink')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                job = {'id': 'INV-1', 'status': state['status'], 'links': {}}
                if state['status'] == 'completed':
                    job['report'] = {'finding': 'Synthetic report', 'evidence_refs': ['MAT-1']}
                data = [job] if '?' in self.path else job
                self.wfile.write(json.dumps({'data': data, **({'error': secret} if state['code'] >= 400 else {})}).encode())

            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond(True)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                key = root / 'key'
                key.write_text(secret)
                request = root / 'request.json'
                sample = CLIENT.parents[1] / 'assets/investigation-request.synthetic.json'
                request.write_bytes(sample.read_bytes())
                env = dict(os.environ, CYBERGUARD_CONSOLE_URL=f'http://127.0.0.1:{server.server_port}',
                           CYBERGUARD_SKILL_KEY_FILE=str(key), HTTP_PROXY='http://127.0.0.1:1',
                           HTTPS_PROXY='http://127.0.0.1:1', NO_PROXY='')

                def run(*args):
                    result = subprocess.run([sys.executable, str(CLIENT), *map(str, args)], env=env,
                                            capture_output=True, text=True)
                    self.assertNotIn(secret, result.stdout + result.stderr)
                    return result

                self.assertEqual(run('check', '--investigations').returncode, 0)
                self.assertEqual(requests[-1][1], '/api/v1/investigations?limit=1')
                receipt = root / 'receipt.json'
                args = ('submit', request, '--idempotency-key', 'stable-1', '--out', receipt)
                self.assertEqual(run(*args).returncode, 0)
                self.assertEqual(requests[-1][:3], ('POST', '/api/v1/investigations', 'stable-1'))
                self.assertEqual(json.loads(requests[-1][3]), json.loads(request.read_text()))
                self.assertEqual(json.loads(receipt.read_text())['data']['id'], 'INV-1')
                before = len(requests)
                self.assertEqual(run(*args).returncode, 2)
                self.assertEqual(len(requests), before)
                self.assertEqual(run('status', 'INV-1').returncode, 0)
                report = root / 'report.json'
                waiting = run('result', 'INV-1', '--out', report)
                self.assertEqual(waiting.returncode, 2)
                self.assertIn('not completed', waiting.stderr)
                self.assertFalse(report.exists())
                state['status'] = 'completed'
                self.assertEqual(run('result', 'INV-1', '--out', report).returncode, 0)
                saved = report.read_bytes()
                self.assertEqual(json.loads(saved)['report']['evidence_refs'], ['MAT-1'])
                self.assertEqual(run('result', 'INV-1', '--out', report).returncode, 2)
                self.assertEqual(report.read_bytes(), saved)
                state['status'] = 'canceled'
                self.assertEqual(run('cancel', 'INV-1', '--idempotency-key', 'cancel-1').returncode, 0)
                self.assertEqual(requests[-1][:3], ('POST', '/api/v1/investigations/INV-1/cancel', 'cancel-1'))
                for code in (302, 403, 500):
                    state['code'] = code
                    failed_receipt = root / f'failed-{code}.json'
                    self.assertEqual(run('submit', request, '--idempotency-key', 'retry-stable',
                                         '--out', failed_receipt).returncode, 2)
                    self.assertFalse(failed_receipt.exists())
                self.assertFalse(any(item[1] == '/credential-sink' for item in requests))
                before = len(requests)
                self.assertEqual(run('status', '../wrong').returncode, 2)
                request.write_text('{"title":"bad"}')
                self.assertEqual(run('submit', request, '--idempotency-key', 'bad', '--out', root / 'bad.json').returncode, 2)
                self.assertEqual(len(requests), before)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
