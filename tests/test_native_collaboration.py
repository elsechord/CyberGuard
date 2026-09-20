"""Adapter fixture tests; no model calls and no claim of live collaboration."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

MODULE = Path(__file__).resolve().parents[1] / 'deploy/investigation-service/collaboration/native_collaboration.py'
spec = importlib.util.spec_from_file_location('native_collaboration', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NativeCollaborationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = dict(job_id='INV-test', task_id='task-1', parent_worker='investigator',
                         run_id='run-1', room_id='!task:matrix', reason='Two independent sources',
                         materials=[dict(material_id='MAT-1', content='original evidence')],
                         nodes=[dict(id='a', subagent='source-reader', question='What happened?', material_ids=['MAT-1'])])
        self.state_path = self.root / 'run-1/workflow.json'
        self.state = dict(status='running', input='PRIVATE INPUT', submitInstructions=['SECRET PROMPT'],
                          nodes=[dict(id='a', agentId='tmp-a', role='reader', status='ready', summary='awaiting submission')])
        self.profile = dict(active_model={'provider_id':'gateway', 'model':'model'}, running={'max_iters':100})
        self.native = SimpleNamespace(_shared_root=lambda:self.root, _api_base=lambda:'http://127.0.0.1:8088/api',
                                      _resolve_run_id=lambda value,fallback:value,
                                      _json_request=Mock(side_effect=self.request),
                                      _workflow_run=Mock(side_effect=self.start_native),
                                      _workflow=Mock(side_effect=self.update_native))
        self.helper = mod.Collaboration(self.native, self.plan, self.root)

    def request(self, method, base, path, payload=None):
        if method == 'PUT':
            self.profile = payload
        return self.profile.copy()

    def save(self):
        self.state_path.parent.mkdir(exist_ok=True)
        mod.write(self.state_path, self.state)

    def start_native(self, args):
        self.save()
        return dict(nodes=self.state['nodes'], submitInstructions=[{'submitPrompt':'SECRET PROMPT'}])

    def update_native(self, args, action):
        if action in ('workflow_finish', 'workflow_fail'):
            self.state['status'] = 'done' if action == 'workflow_finish' else 'failed'
            self.state['cleanupTempAgents'] = dict(agents=[dict(agentId='tmp-a',ok=True,deleted=True)],deleted=1,failed=0,missing=0)
        self.save()
        return {'action':action, 'readyInstructions':[]}

    def test_start_uses_native_and_explicit_parent_model(self):
        result = self.helper.start()
        args = self.native._workflow_run.call_args.args[0]
        self.assertEqual(args['activeModel'], self.profile['active_model'])
        self.assertIn('MAT-1', args['nodes'][0]['task'])
        self.assertEqual(json.loads(args['input'])['materials'], self.plan['materials'])
        self.assertEqual(self.profile['running']['max_iters'], 10)
        self.assertFalse(self.profile['running']['auto_title_config']['enabled'])
        self.assertIn('submitInstructions', result)
        self.assertEqual(result['submitInstructions'][0]['parent_id'], 'default')
        self.assertIn('peer_agent_ids', result['submitInstructions'][0])

    def test_export_redacts_native_prompts_and_preserves_real_status(self):
        self.helper.start()
        snapshot = mod.read(self.root/'collaboration.json')
        self.assertEqual(snapshot['nodes'][0]['status'], 'ready')
        self.assertEqual(snapshot['nodes'][0]['question'], 'What happened?')
        self.assertNotIn('SECRET', json.dumps(snapshot))
        self.assertNotIn('PRIVATE', json.dumps(snapshot))
        self.assertEqual(mod.read(self.state_path)['input'], 'PRIVATE INPUT')
        self.assertEqual(snapshot['cleanup'], {})

    def test_limit_and_bad_material_fail_before_native_mutation(self):
        self.plan['nodes'] *= 4
        with self.assertRaises(ValueError): self.helper.start()
        self.native._workflow_run.assert_not_called()
        self.plan['nodes'] = [dict(id='a',subagent='reader',question='?',material_ids=['missing'])]
        with self.assertRaises(ValueError): self.helper.start()
        self.native._workflow_run.assert_not_called()

    def test_second_start_does_not_duplicate_agents(self):
        self.helper.start()
        with self.assertRaises(ValueError): self.helper.start()
        self.assertEqual(self.native._workflow_run.call_count, 1)

    def test_finish_delegates_cleanup_and_retains_native_evidence(self):
        self.helper.start()
        self.helper.advance('finish', {'summary':'Merged'})
        args, action = self.native._workflow.call_args.args
        self.assertEqual(action, 'workflow_finish')
        self.assertTrue(args['cleanupWorkspace'])
        self.assertTrue(self.state_path.exists())
        self.assertEqual(mod.read(self.root/'collaboration.json')['cleanup']['deleted'], 1)
        self.assertEqual(mod.read(self.root/'collaboration.json')['cleanup']['status'], 'completed')

    def test_update_uses_native_dependency_advancement(self):
        self.helper.start()
        steps = [{'id':'a','status':'done','summary':'Verified'}]
        self.helper.advance('update', {'steps':steps, 'sharedDir':'do-not-forward'})
        args, action = self.native._workflow.call_args.args
        self.assertEqual(args['steps'], steps)
        self.assertEqual(action, 'workflow_update')
        self.assertNotIn('sharedDir', args)

    def test_recorded_message_is_not_transport_attestation(self):
        self.helper.start()
        snapshot = self.helper.message({'from':'a','to':'b','kind':'question','question':'Check?',
                                        'event_id':'event-1','provenance':'transport_confirmed'})
        self.assertEqual(snapshot['messages'][0]['provenance'], 'agent_recorded')

    def test_depth_and_missing_task_directory(self):
        with self.assertRaises(ValueError): mod.Collaboration(self.native,self.plan,self.root,max_depth=2)
        with self.assertRaises(ValueError): mod.Collaboration(self.native,self.plan,self.root/'absent')

    def test_missing_model_does_not_spawn(self):
        self.profile.pop('active_model')
        with self.assertRaises(ValueError): self.helper.start()
        self.native._workflow_run.assert_not_called()

    def test_child_config_failure_runs_native_cleanup(self):
        self.native._json_request.side_effect = [self.profile, self.profile, RuntimeError('config failed')]
        with self.assertRaises(RuntimeError): self.helper.start()
        self.assertEqual(self.native._workflow.call_args.args[1], 'workflow_fail')
        self.assertEqual(mod.read(self.root/'collaboration.json')['status'], 'failed')

    def cleanup_response(self, failed):
        cleanup = dict(agents=[dict(agentId='tmp-a', ok=not failed,
                                   error='DELETE /agents/tmp-a failed: HTTP 409: agent is starting' if failed else '',
                                   deleted=not failed)], failed=int(failed), deleted=int(not failed), missing=0)
        self.state.update(status='failed', cleanupTempAgents=cleanup)
        self.save()
        return {'cleanupTempAgents': cleanup}

    def test_starting_cleanup_retries_native_then_succeeds(self):
        self.helper.start()
        self.helper.sleep = Mock()
        outcomes = iter([True, False])
        self.native._workflow.side_effect = lambda *_: self.cleanup_response(next(outcomes))
        result = self.helper.advance('fail')
        self.assertEqual(result['cleanupTempAgents']['failed'], 0)
        self.assertEqual(self.native._workflow.call_count, 2)
        self.helper.sleep.assert_called_once_with(1)
        self.assertEqual(mod.read(self.root/'collaboration.json')['cleanup']['status'], 'completed')

    def test_persistent_starting_cleanup_is_bounded_and_visible(self):
        self.helper.start()
        self.helper.sleep = Mock()
        self.native._workflow.side_effect = lambda *_: self.cleanup_response(True)
        result = self.helper.advance('fail')
        self.assertEqual(result['cleanupTempAgents']['failed'], 1)
        self.assertEqual(self.native._workflow.call_count, 5)
        self.assertEqual([call.args[0] for call in self.helper.sleep.call_args_list], [1,2,4,8])
        self.assertEqual(mod.read(self.root/'collaboration.json')['cleanup']['status'], 'partial_failed')

    def test_partial_native_start_failure_uses_bounded_cleanup(self):
        original = RuntimeError('second child creation failed')
        def partial_start(_):
            self.save()
            raise original
        self.native._workflow_run.side_effect = partial_start
        outcomes = iter([True, False])
        self.native._workflow.side_effect = lambda *_: self.cleanup_response(next(outcomes))
        self.helper.sleep = Mock()
        with self.assertRaises(RuntimeError) as raised:
            self.helper.start()
        self.assertIs(raised.exception, original)
        self.assertEqual(self.native._workflow.call_count, 2)
        self.assertEqual(mod.read(self.root/'collaboration.json')['cleanup']['status'], 'completed')

    def test_export_start_failure_cleans_up_and_preserves_original_error(self):
        original = OSError('initial snapshot write failed')
        self.helper.export = Mock(side_effect=[original, OSError('cleanup snapshot write failed')])
        with self.assertRaises(OSError) as raised:
            self.helper.start()
        self.assertIs(raised.exception, original)
        self.assertEqual(self.native._workflow.call_args.args[1], 'workflow_fail')
        self.assertEqual(mod.read(self.state_path)['cleanupTempAgents']['failed'], 0)
        self.assertIn('cleanup snapshot write failed', ' '.join(getattr(original, '__notes__', [])))


if __name__ == '__main__': unittest.main()
