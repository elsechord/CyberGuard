"""Durable intake/API tests. Injected tick callbacks are unit doubles, not AgentTeams."""
import copy
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/operations-console'))
# Avoid initializing a deployment database on first import; each test uses its own DB.
_IMPORT_TEMP = tempfile.TemporaryDirectory(prefix='investigation-import-', ignore_cleanup_errors=True)
with patch.dict(os.environ, {'CYBERGUARD_CONSOLE_DB': str(Path(_IMPORT_TEMP.name) / 'db.sqlite')}):
    from app import apikeys, auth, db, errors, intake, jobs
    from app.main import app


def submission():
    return {'title': 'Synthetic investigation', 'objective': 'Compare explanations from supplied materials.',
            'domain': 'security', 'materials': [
                {'source_type': 'server_log', 'name': 'Synthetic log', 'content': 'SYNTHETIC load=87',
                 'media_type': 'text/plain', 'source_uri': 'http://127.0.0.1/never-fetch',
                 'interpretation': 'Unverified hypothesis, not an observation.'}]}


class InvestigationJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='investigation-test-', ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {
            'CYBERGUARD_CONSOLE_DB': str(Path(self.tmp.name) / 'jobs.sqlite'),
            'CYBERGUARD_COOKIE_SECURE': 'false', 'CYBERGUARD_CONSOLE_ORIGIN': '',
            'CYBERGUARD_GATEWAY_URL': '', 'CYBERGUARD_INVESTIGATION_DISPATCH_ENABLED': 'false'})
        self.env.start()
        self.addCleanup(self.env.stop)
        db.init_db()
        jobs.init_db()
        self.client = TestClient(app, base_url='http://127.0.0.1')
        self.addCleanup(self.client.close)
        self.principal = auth.Principal('api_key', None, 'synthetic-key', 'viewer',
                                        {'investigations:read', 'investigations:write'}, key_id=7)

    def key(self, scopes):
        _, raw, _ = apikeys.create_key(name='test-only', scopes=scopes, created_by='test')
        return {'Authorization': 'Bearer ' + raw}

    def session(self, role):
        user = auth.create_user('test-' + role, 'test-password-long-1', role)
        sid, csrf = auth.create_session(user)
        session = TestClient(app, base_url='http://127.0.0.1')
        self.addCleanup(session.close)
        session.cookies.set('cgsession', sid)
        return session, csrf

    def test_intake_provenance_and_bounds(self):
        payload = submission()
        result = intake.validate_submission(payload)
        material = result['materials'][0]
        self.assertEqual(material['source_authenticity'], 'unverified')
        self.assertEqual(material['content'], payload['materials'][0]['content'])
        self.assertEqual(material['interpretation'], payload['materials'][0]['interpretation'])
        self.assertEqual(result, intake.validate_submission(payload))
        for mutation in ('duplicate', 'trusted', 'large', 'binary', 'domain'):
            bad = copy.deepcopy(payload)
            if mutation == 'duplicate':
                bad['materials'].append(copy.deepcopy(bad['materials'][0]))
            elif mutation == 'trusted':
                bad['materials'][0]['source_authenticity'] = 'verified'
            elif mutation == 'large':
                bad['materials'][0]['content'] = '\u4e2d' * (intake.MAX_CONTENT_BYTES // 3 + 1)
            elif mutation == 'binary':
                bad['materials'][0]['content'] = '\x00'
            else:
                bad['domain'] = 'unknown'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                intake.validate_submission(bad)

    def test_concurrent_idempotency_is_atomic_and_conflicts(self):
        barrier = threading.Barrier(8)
        def create(_):
            barrier.wait()
            try:
                return jobs.submit(self.principal, submission(), 'one-logical-request')
            finally:
                db.connection().close()
                db._LOCAL.conn = None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create, range(8)))
        self.assertEqual(len({job['id'] for job, _ in results}), 1)
        self.assertEqual(sum(not replay for _, replay in results), 1)
        self.assertEqual(db.connection().execute('SELECT count(*) FROM investigation_job').fetchone()[0], 1)
        changed = submission()
        changed['objective'] = 'Different objective'
        with self.assertRaises(errors.ApiError) as caught:
            jobs.submit(self.principal, changed, 'one-logical-request')
        self.assertEqual(caught.exception.status_code, 409)

    def test_restart_restores_bridge_checkpoint(self):
        job, _ = jobs.submit(self.principal, submission(), 'restart')
        checkpoint = {'remote_id': 'synthetic-backend-task', 'next_stage': 'verifier'}
        self.assertTrue(jobs.tick('dispatcher', lambda _: {'state': 'running', 'stage': 'planner',
                                                         'bridge_state': checkpoint}))
        db.connection().close()
        db._LOCAL.conn = None
        jobs.init_db()
        self.assertEqual(jobs.get_job(self.principal, job['id'])['status'], 'running')
        seen = []
        def resume(restored):
            seen.append(restored['bridge_state'])
            return {'state': 'completed', 'stage': 'verified', 'report': {'test_double': True}}
        self.assertTrue(jobs.tick('dispatcher', resume))
        self.assertEqual(seen, [checkpoint])
        public = jobs.get_job(self.principal, job['id'])
        self.assertEqual(public['status'], 'completed')
        self.assertNotIn('bridge_state', public)
        self.assertNotIn('owner', public)

    def test_native_cancel_requires_remote_pause(self):
        from app.agentteams_bridge import BridgeError
        job, _ = jobs.submit(self.principal, submission(), 'native-cancel')
        jobs.tick('worker', lambda _: dict(state='running', stage='native_tasks',
            bridge_state={'backend': 'native', 'project_id': 'native-project'}))
        with patch('app.agentteams_native.pause', side_effect=BridgeError('unavailable')):
            with self.assertRaises(errors.ApiError) as failure:
                jobs.cancel(self.principal, job['id'])
            self.assertEqual(failure.exception.status_code, 503)
            self.assertEqual(jobs.get_job(self.principal, job['id'])['status'], 'running')
        with patch('app.agentteams_native.pause') as pause:
            self.assertEqual(jobs.cancel(self.principal, job['id'])['status'], 'canceled')
            pause.assert_called_once()
            jobs.cancel(self.principal, job['id'])
            pause.assert_called_once()

    def test_cancel_wins_over_late_completion(self):
        job, _ = jobs.submit(self.principal, submission(), 'cancel')
        def late(_):
            jobs.cancel(self.principal, job['id'])
            return {'state': 'completed', 'stage': 'done', 'report': {'must_not_publish': True}}
        self.assertFalse(jobs.tick('worker', late))
        final = jobs.get_job(self.principal, job['id'])
        self.assertEqual(final['status'], 'canceled')
        self.assertIsNone(final['report'])
        self.assertEqual(jobs.cancel(self.principal, job['id'])['status'], 'canceled')
        advance = Mock()
        self.assertFalse(jobs.tick('worker', advance))
        advance.assert_not_called()

    def test_dispatch_lease_blocks_competitor_and_fences_expired_owner(self):
        job, _ = jobs.submit(self.principal, submission(), 'lease')
        self.assertTrue(jobs.lease('a'))
        self.assertFalse(jobs.lease('b'))
        advance = Mock()
        self.assertFalse(jobs.tick('b', advance))
        advance.assert_not_called()
        def stolen(_):
            with db.tx() as conn:
                conn.execute('UPDATE investigation_dispatch_lease SET expires=0')
            self.assertTrue(jobs.lease('b'))
            return {'state': 'completed', 'report': {'stale_owner': True}}
        self.assertFalse(jobs.tick('a', stolen))
        self.assertEqual(jobs.get_job(self.principal, job['id'])['status'], 'queued')

    def test_input_tamper_blocks_backend(self):
        job, _ = jobs.submit(self.principal, submission(), 'tamper')
        with db.tx() as conn:
            row = conn.execute('SELECT payload FROM investigation_job WHERE id=?', (job['id'],)).fetchone()
            stored = json.loads(row['payload'])
            stored['materials'][0]['content'] = 'tampered'
            conn.execute('UPDATE investigation_job SET payload=? WHERE id=?', (jobs.canonical(stored), job['id']))
        advance = Mock()
        self.assertTrue(jobs.tick('worker', advance))
        advance.assert_not_called()
        final = jobs.get_job(self.principal, job['id'])
        self.assertEqual(final['status'], 'failed')
        self.assertIsNone(final['report'])

    def test_waiting_backend_and_exception_never_become_success(self):
        job, _ = jobs.submit(self.principal, submission(), 'wait')
        self.assertTrue(jobs.tick('worker', lambda _: {'state': 'waiting_backend', 'stage': 'configuration'}))
        self.assertEqual(jobs.get_job(self.principal, job['id'])['status'], 'waiting_backend')
        self.assertTrue(jobs.tick('worker', Mock(side_effect=RuntimeError('secret-token'))))
        final = jobs.get_job(self.principal, job['id'])
        self.assertEqual(final['status'], 'waiting_backend')
        self.assertIsNone(final['report'])
        self.assertNotIn('secret-token', json.dumps(final))
        self.assertTrue(jobs.tick('worker', lambda _: {'state': 'completed'}))
        self.assertEqual(jobs.get_job(self.principal, job['id'])['status'], 'failed')

    def test_api_auth_scopes_ownership_replay_and_conflict(self):
        path = '/api/v1/investigations'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post(path, json=submission()).status_code, 401)
        reader = self.key(['investigations:read'])
        writer = self.key(['investigations:write'])
        owner = self.key(['investigations:read', 'investigations:write'])
        other = self.key(['investigations:read', 'investigations:write'])
        self.assertEqual(self.client.post(path, headers=reader, json=submission()).status_code, 403)
        self.assertEqual(self.client.get(path, headers=writer).status_code, 403)
        headers = {**owner, 'Idempotency-Key': 'api-create'}
        first = self.client.post(path, headers=headers, json=submission())
        self.assertEqual(first.status_code, 202, first.text)
        location = first.headers['location']
        self.assertEqual(first.headers['idempotent-replay'], 'false')
        replay = self.client.post(path, headers=headers, json=submission())
        self.assertEqual(replay.headers['idempotent-replay'], 'true')
        self.assertEqual(replay.json()['data']['id'], first.json()['data']['id'])
        changed = submission(); changed['title'] = 'Different title'
        self.assertEqual(self.client.post(path, headers=headers, json=changed).status_code, 409)
        self.assertEqual(self.client.get(location, headers=other).status_code, 404)
        self.assertEqual(self.client.post(location + '/cancel', headers=other).status_code, 404)
        self.assertEqual(self.client.get(path, headers=other).json()['data'], [])
        self.assertEqual(self.client.get(location, headers=owner).status_code, 200)
        self.assertEqual(self.client.get(location).status_code, 401)
        self.assertEqual(self.client.post(location + '/cancel').status_code, 401)
        analyst, _ = self.session('analyst')
        self.assertEqual(analyst.get(location).status_code, 404)
        self.assertEqual(analyst.get(path).json()['data'], [])
        admin, _ = self.session('admin')
        self.assertEqual(admin.get(location).status_code, 200)
        self.assertEqual(len(admin.get(path).json()['data']), 1)
        self.assertEqual(admin.post(path, json=submission()).status_code, 403)
        self.assertEqual(admin.post(path, json=submission(), headers={'Origin': 'http://127.0.0.1',
                         'X-Requested-With': 'XMLHttpRequest', 'Idempotency-Key': 'session'}).status_code, 202)
        canceled = self.client.post(location + '/cancel', headers=owner)
        self.assertEqual(canceled.json()['data']['status'], 'canceled')

    def test_api_body_bounds_and_unambiguous_json(self):
        path = '/api/v1/investigations'
        headers = {**self.key(['investigations:write']), 'Idempotency-Key': 'bad', 'Content-Type': 'application/json'}
        cases = [(b'{"title":"a","title":"b"}', 422),
                 (b'{"materials":[{"name":"a","name":"b"}]}', 422), (b'{"x":NaN}', 422),
                 (b'[]', 422), (b'\xff', 422), (b' ' * (intake.MAX_SUBMISSION_BYTES + 1), 413)]
        for body, expected in cases:
            with self.subTest(size=len(body)):
                self.assertEqual(self.client.post(path, headers=headers, content=body).status_code, expected)
        self.assertEqual(self.client.post(path, headers={**headers, 'Content-Type': 'text/plain'},
                                         content='{}').status_code, 415)
        self.assertEqual(self.client.post(path, headers={k:v for k,v in headers.items() if k != 'Idempotency-Key'},
                                         json=submission()).status_code, 422)
        self.assertEqual(db.connection().execute('SELECT count(*) FROM investigation_job').fetchone()[0], 0)

    def test_connect_default_issues_only_task_scopes_for_30_days(self):
        admin, csrf = self.session('admin')
        with patch('app.pages.clients.gateway_incidents', return_value=[]):
            page = admin.get('/connect')
            self.assertEqual(page.status_code, 200)
            self.assertIn('check --investigations', page.text)
            self.assertEqual(len(apikeys.list_keys()), 0)
            result = admin.post('/connect/key', data={'csrf_token': csrf, 'agent': 'codex',
                               'scopes': 'admin decisions:write', 'expires_in_days': '3650'})
        self.assertEqual(result.status_code, 200, result.text)
        rows = apikeys.list_keys()
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]['scopes']), {'investigations:read', 'investigations:write'})
        days = (datetime.fromisoformat(rows[0]['expires_at']) - datetime.fromisoformat(rows[0]['created_at'])).total_seconds() / 86400
        self.assertAlmostEqual(days, 30, places=3)
        viewer, viewer_csrf = self.session('viewer')
        self.assertEqual(viewer.post('/connect/key', data={'csrf_token': viewer_csrf}).status_code, 403)
        self.assertEqual(len(apikeys.list_keys()), 1)


    def test_report_export_pending_ownership_and_attachment(self):
        owner = self.key(['investigations:read', 'investigations:write'])
        other = self.key(['investigations:read'])
        response = self.client.post('/api/v1/investigations', json=submission(),
                                    headers={**owner, 'Idempotency-Key': 'export'})
        job = response.json()['data']
        path = response.headers['location'] + '/report'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers=other).status_code, 404)
        pending = self.client.get(path, headers=owner)
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(pending.json()['error']['code'], 'report_not_ready')
        self.assertNotIn('content-disposition', pending.headers)
        report = {'test_double': True, 'findings': [], 'evidence_refs': [job['materials'][0]['material_id']]}
        runtime = {'backend': 'unit-double', 'execution': 'simulated'}
        self.assertTrue(jobs.tick('export-worker', lambda _: {'state': 'completed', 'stage': 'done',
                                                           'report': report, 'runtime': runtime}))
        ready = self.client.get(path, headers=owner)
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json(), {'job_id': job['id'], 'report': report, 'runtime': runtime})
        self.assertEqual(ready.headers['content-disposition'], f'attachment; filename="{job["id"]}-report.json"')
        self.assertEqual(ready.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get(path, headers=other).status_code, 404)
        admin, _ = self.session('admin')
        self.assertEqual(admin.get(path).json(), ready.json())

    def test_cursor_pagination_ties_no_duplicates_and_owner_binding(self):
        path = '/api/v1/investigations'
        owner = self.key(['investigations:read', 'investigations:write'])
        other = self.key(['investigations:read', 'investigations:write'])
        identifiers = set()
        # Equal timestamps exercise the deterministic ID tie-breaker.
        with patch('app.jobs.audit.now_iso', return_value='2026-09-20T00:00:00+00:00'):
            for number in range(5):
                response = self.client.post(path, json=submission(),
                                            headers={**owner, 'Idempotency-Key': f'page-{number}'})
                self.assertEqual(response.status_code, 202)
                identifiers.add(response.json()['data']['id'])
            foreign = self.client.post(path, json=submission(),
                                       headers={**other, 'Idempotency-Key': 'foreign'}).json()['data']['id']
        collected, cursor = [], None
        for expected_count in (2, 2, 1):
            params = {'limit': 2, **({'cursor': cursor} if cursor else {})}
            response = self.client.get(path, headers=owner, params=params)
            self.assertEqual(response.status_code, 200)
            page = response.json()
            self.assertEqual(len(page['data']), expected_count)
            collected.extend(item['id'] for item in page['data'])
            cursor = page['next_cursor']
            self.assertEqual(page['has_more'], expected_count == 2)
            for item in page['data']:
                self.assertNotIn('materials', item)
                self.assertNotIn('objective', item)
        self.assertIsNone(cursor)
        self.assertEqual(set(collected), identifiers)
        self.assertEqual(len(collected), len(set(collected)))
        self.assertEqual(collected, sorted(identifiers, reverse=True))
        self.assertEqual(self.client.get(path, headers=owner, params={'cursor': foreign}).status_code, 404)
        self.assertEqual(self.client.get(path, headers=other, params={'cursor': collected[0]}).status_code, 404)
        self.assertEqual(self.client.get(path, headers=owner, params={'cursor': 'INV-missing'}).status_code, 404)

    def test_session_intake_detail_cancel_and_csrf(self):
        analyst, csrf = self.session('analyst')
        page = analyst.get('/investigations')
        self.assertEqual(page.status_code, 200)
        key = re.search(r'name="idempotency_key" value="([^"]+)"', page.text).group(1)
        form = {'csrf_token': csrf, 'idempotency_key': key, 'title': 'Synthetic browser task',
                'objective': 'Review supplied synthetic observation', 'domain': 'security',
                'source_type': 'server_log', 'name': 'Synthetic source',
                'content': '<script>alert("untrusted input")</script>', 'interpretation': 'Test only'}
        self.assertEqual(analyst.post('/investigations/new', data={**form, 'csrf_token': 'bad'}).status_code, 403)
        self.assertEqual(db.connection().execute('SELECT count(*) FROM investigation_job').fetchone()[0], 0)
        created = analyst.post('/investigations/new', data=form, follow_redirects=False)
        self.assertEqual(created.status_code, 303, created.text)
        location = created.headers['location']
        replay = analyst.post('/investigations/new', data=form, follow_redirects=False)
        self.assertEqual(replay.headers['location'], location)
        detail = analyst.get(location)
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn('<script>alert(', detail.text)
        self.assertIn('&lt;script&gt;', detail.text)
        self.assertEqual(analyst.post(location + '/cancel', data={'csrf_token': 'bad'}).status_code, 403)
        job_id = location.rsplit('/', 1)[1]
        self.assertEqual(analyst.get('/api/v1/investigations/' + job_id).json()['data']['status'], 'queued')
        viewer, viewer_csrf = self.session('viewer')
        self.assertEqual(viewer.get(location).status_code, 404)
        self.assertEqual(viewer.post('/investigations/new', data={**form, 'csrf_token': viewer_csrf}).status_code, 403)
        self.assertEqual(viewer.post(location + '/cancel', data={'csrf_token': viewer_csrf}).status_code, 403)
        canceled = analyst.post(location + '/cancel', data={'csrf_token': csrf}, follow_redirects=False)
        self.assertEqual(canceled.status_code, 303)
        self.assertEqual(analyst.get('/api/v1/investigations/' + job_id).json()['data']['status'], 'canceled')


    def test_budget_gate_defers_new_work_but_polls_dispatched_work(self):
        job, _ = jobs.submit(self.principal, submission(), 'budget-gate')
        advance = Mock(return_value={'state': 'running', 'stage': 'investigator',
                                     'bridge_state': {'remote_id': 'unit-double-request'}})
        with patch.dict(os.environ, {'CYBERGUARD_INVESTIGATION_REQUIRE_GUARD_ARMED': 'true'}), \
                patch('app.clients.guard_status', return_value={'available': True, 'armed': False}) as guard:
            self.assertTrue(jobs.tick('budget-worker', advance))
            advance.assert_not_called()
            pending = jobs.get_job(self.principal, job['id'])
            self.assertEqual((pending['status'], pending['stage']), ('waiting_backend', 'budget'))
            self.assertIsNone(pending['report'])
            guard.return_value = {'available': True, 'armed': True}
            self.assertTrue(jobs.tick('budget-worker', advance))
            advance.assert_called_once()
            self.assertEqual(jobs.get_job(self.principal, job['id'])['status'], 'running')
            guard.return_value = {'available': False, 'armed': False}
            advance.reset_mock()
            advance.return_value = {'state': 'completed', 'stage': 'verified',
                                    'report': {'unit_double': True, 'existing_request_completed': True}}
            guard.reset_mock()
            self.assertTrue(jobs.tick('budget-worker', advance))
            advance.assert_called_once()
            self.assertEqual(advance.call_args.args[0]['bridge_state'], {'remote_id': 'unit-double-request'})
            guard.assert_not_called()
            final = jobs.get_job(self.principal, job['id'])
            self.assertEqual(final['status'], 'completed')
            self.assertTrue(final['report']['existing_request_completed'])


if __name__ == '__main__':
    unittest.main()
