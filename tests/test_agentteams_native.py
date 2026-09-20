"""Native API contract tests; these fixtures do not attest live execution."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/operations-console'))
from app import agentteams_native as native
from app.agentteams_bridge import BridgeError


class NativeTasks(unittest.TestCase):
    def setUp(self):
        self.cfg = {key: 'configured' for key in ('CONTROLLER_URL', 'CONTROLLER_TOKEN', 'TEAM_ID', 'LEADER_ROOM_ID', 'LEADER_USER_ID', 'MATRIX_URL', 'MATRIX_TOKEN', 'MATRIX_HOST')}
        self.job = dict(id='INV-test', title='Review', objective='Check original evidence', domain='security',
                        materials=[dict(material_id='MAT-a', content='login denied')], bridge_state={})
        self.report = dict(job_id='INV-test', role='verifier', summary='Login denied',
                           findings=[dict(claim='Login denied', status='supported', limitations='',
                                          citations=[dict(material_id='MAT-a', quote='login denied')])], unknowns=[], next_steps=[])
        self.config_patch = patch.object(native, 'config', return_value=self.cfg)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        observe = patch.object(native, "observe_collaboration")
        observe.start()
        self.addCleanup(observe.stop)
        packet = patch.object(native, 'publish_case', return_value='mxc://matrix/case')
        packet.start()
        self.addCleanup(packet.stop)
        room = patch.object(native, 'create_case_room', return_value='!case:matrix')
        room.start()
        self.addCleanup(room.stop)

    def checkpoint(self, update):
        self.job.update(bridge_state=update['bridge_state'], runtime=update['runtime'])

    def workflow(self):
        return dict(status='completed', nodes=[dict(id='task-1', status='completed')],
                    tasks_detail=[dict(task_id='task-1', deliverables=['shared/tasks/task-1/report.json'])])

    def test_oversized_materials_do_not_create_or_dispatch_project(self):
        self.job['materials'][0]['content'] = 'x' * 65000
        with patch.object(native, 'controller') as http, patch.object(native, '_http') as matrix:
            result = native.advance(self.job)
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(result['runtime']['error_code'], 'materials_too_large')
            http.assert_not_called()
            matrix.assert_not_called()

    def test_console_closes_only_accepted_project_with_valid_report(self):
        self.job['bridge_state'] = dict(backend='native', project_id='native-project', request_event_id='$request')
        workflow = self.workflow()
        workflow['status'] = 'active'
        with patch.object(native, 'controller', side_effect=[workflow, self.report, {}]) as http:
            result = native.advance(self.job)
            self.assertEqual(result['state'], 'running')
            self.assertEqual(http.call_args.args[1], 'POST')
            self.assertIn('/complete?', http.call_args.args[2])
        invalid = dict(self.report, job_id='wrong-job')
        with patch.object(native, 'controller', side_effect=[workflow, invalid]) as http:
            self.assertEqual(native.advance(self.job)['state'], 'failed')
            self.assertEqual(http.call_count, 2)

    def test_native_create_dispatch_poll_artifact(self):
        with patch.object(native, 'controller', return_value={}) as http, patch.object(native, '_http', return_value={'event_id': '$request'}) as matrix:
            first = native.advance(self.job)
            self.assertEqual(first['stage'], 'native_dispatch')
            self.assertEqual(http.call_args.args[1:3], ('POST', '/projects'))
            self.assertNotIn('source_room_id', http.call_args.args[3])
            self.assertNotIn('reply_route', http.call_args.args[3])
            matrix.assert_not_called()
            self.checkpoint(first)
            self.checkpoint(native.advance(self.job))
            self.assertEqual(matrix.call_count, 1)
            self.assertIn('%21case%3Amatrix', matrix.call_args.args[2])
            http.side_effect = [self.workflow(), self.report]
            final = native.advance(self.job)
            self.assertEqual(final['state'], 'completed')
            self.assertEqual(final['runtime']['report_task_id'], 'task-1')
            self.assertEqual(final['report'], self.report)
            self.assertEqual(matrix.call_count, 1)

    def test_retry_creation_resolves_same_project_and_rejects_collision(self):
        with patch.object(native, 'controller', side_effect=[BridgeError('exists', 'matrix_http_409'), {'requester': 'INV-test'}]):
            self.assertEqual(native.advance(self.job)['state'], 'running')
        with patch.object(native, 'controller', side_effect=[BridgeError('exists', 'matrix_http_409'), {'requester': 'other'}]):
            self.assertEqual(native.advance(self.job)['state'], 'failed')

    def test_completed_project_does_not_imply_completed_tasks_or_report(self):
        self.job['bridge_state'] = dict(backend='native', project_id='cg-inv-test', request_event_id='$sent')
        for workflow in ({'status': 'completed', 'nodes': []}, {'status': 'completed', 'nodes': [{'status': 'blocked'}]},
                         {'status': 'completed', 'nodes': [{'status': 'completed'}], 'tasks_detail': []}):
            with self.subTest(workflow=workflow), patch.object(native, 'controller', return_value=workflow):
                self.assertEqual(native.advance(self.job)['state'], 'failed')

    def test_bad_citation_is_not_accepted_from_native_artifact(self):
        self.job['bridge_state'] = dict(backend='native', project_id='cg-inv-test', request_event_id='$sent')
        self.report['findings'][0]['citations'][0]['quote'] = 'fabricated'
        with patch.object(native, 'controller', side_effect=[self.workflow(), self.report]):
            self.assertEqual(native.advance(self.job)['state'], 'failed')

    def test_interruption_is_visible_and_cancel_pauses_real_project(self):
        self.job['bridge_state'] = dict(backend='native', project_id='cg-inv-test', request_event_id='$sent')
        with patch.object(native, 'controller', return_value={'status': 'active', 'interrupts': ['need input']}) as http:
            result = native.advance(self.job)
            self.assertEqual(result['stage'], 'native_attention')
            native.pause(self.job)
            self.assertEqual(http.call_args.args[1], 'POST')
            self.assertIn('/pause?', http.call_args.args[2])

    def test_missing_native_project_rebuilds_after_studio_restart(self):
        self.job['bridge_state'] = dict(backend='native', project_id='cg-inv-test',
                                        request_event_id='$sent', source_room_id='!old:matrix',
                                        case_uri='mxc://old/case')
        with patch.object(native, 'controller', side_effect=BridgeError('not found', 'matrix_http_404')):
            update = native.advance(self.job)
        self.assertEqual(update['state'], 'running')
        self.assertEqual(update['stage'], 'native_dispatch')
        self.assertEqual(update['bridge_state']['restart_count'], 1)
        self.assertNotIn('project_id', update['bridge_state'])
        self.assertNotIn('request_event_id', update['bridge_state'])
        self.checkpoint(update)
        with patch.object(native, 'controller', return_value={}):
            retry = native.advance(self.job)
        self.assertEqual(retry['state'], 'running')
        self.assertEqual(retry['bridge_state']['project_id'], 'cg-inv-test')


class NativeCollaborationObservation(unittest.TestCase):
    def test_case_room_includes_team_so_assignments_can_be_received(self):
        cfg = {'TEAM_ID': 'team-a', 'LEADER_USER_ID': '@leader:matrix', 'MATRIX_TOKEN': 'test'}
        with patch.object(native, 'controller', side_effect=[
                {'workerMembers': [{'name': 'reader'}, {'name': 'reviewer'}]},
                {'matrixUserID': '@reader:matrix'}, {'matrixUserID': '@reviewer:matrix'}]), \
             patch.object(native, '_http', return_value={'room_id': '!case:matrix'}) as matrix:
            self.assertEqual(native.create_case_room(cfg, {'id': 'INV-a'}), '!case:matrix')
            self.assertEqual(matrix.call_args.args[3]['invite'],
                             ['@leader:matrix', '@reader:matrix', '@reviewer:matrix'])
            room = matrix.call_args.args[3]
            self.assertEqual(room['name'], 'TASK：cg-inv-a')
            self.assertEqual(room['initial_state'][0]['type'], 'room.meta')
            meta = room['initial_state'][0]['content']
            self.assertEqual(meta['roomKind'], 'task_room')
            self.assertEqual(meta['leaderWorker']['userId'], '@leader:matrix')
            self.assertEqual({w['userId'] for w in meta['workerMembers']},
                             {'@reader:matrix', '@reviewer:matrix'})

    def test_optional_snapshot_has_native_parent_and_does_not_block_reports(self):
        job = {'id': 'INV-a'}
        workflow = {'status': 'active', 'nodes': [{'assignee': '@reader:matrix'}],
                    'tasks_detail': [{'task_id': 'task-a', 'assigned_to': '@reader:matrix'}]}
        runtime, state = {}, {'project_id': 'project-a'}
        snapshot = {'job_id': 'INV-a', 'task_id': 'task-a', 'parent_worker': 'reader',
                    'run_id': 'run-a', 'nodes': [{'id': 'n1', 'agent_id': 'tmp-native-1'}]}
        with patch.object(native, 'controller', return_value=snapshot):
            native.observe_collaboration({'TEAM_ID': 'team'}, job, workflow, runtime, state)
        self.assertEqual(runtime['collaboration_view']['team_worker_count'], 1)
        self.assertEqual(runtime['collaboration_view']['temporary_agent_count'], 1)
        state['collaboration_checked_at'] = 0
        with patch.object(native, 'controller', side_effect=BridgeError('not available')):
            native.observe_collaboration({'TEAM_ID': 'team'}, job, workflow, runtime, state)
        self.assertEqual(len(runtime['collaboration']), 1)

    def test_snapshot_for_other_job_is_not_shown(self):
        runtime, state = {}, {'project_id': 'project-a'}
        with patch.object(native, 'controller', return_value={'job_id': 'other', 'task_id': 'task-a'}):
            native.observe_collaboration({'TEAM_ID': 'team'}, {'id': 'INV-a'},
                {'tasks_detail': [{'task_id': 'task-a'}]}, runtime, state)
        self.assertEqual(runtime['collaboration'], [])


if __name__ == '__main__':
    unittest.main()
