"""Display projection tests, not evidence of live multi-agent execution."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/operations-console'))
from app.collaboration_view import normalize


class CollaborationViewTests(unittest.TestCase):
    def test_missing_and_malformed_fields_are_optional(self):
        self.assertEqual(normalize(None)['runs'], [])
        result = normalize([None, {'nodes': 'wrong', 'messages': [None, {'answer': {'bad': 1}}]}])
        self.assertEqual(result['runs'][0]['nodes'], [])
        self.assertEqual(result['runs'][0]['messages'][0]['answer'], '')

    def test_counts_distinguish_workers_from_temporary_agents(self):
        result = normalize([
            {'parent_worker': 'investigator', 'run_id': 'r1', 'nodes': [{'agent_id': 'tmp-a'}]},
            {'parent_worker': 'investigator', 'run_id': 'r2', 'nodes': [{'agent_id': 'tmp-a'}]},
            {'parent_worker': 'verifier', 'nodes': [{'agent_id': 'tmp-a'}]}],
            workflow={'nodes': [{'assignee': 'investigator'}, {'assignee': 'verifier'}]})
        self.assertEqual(result['team_worker_count'], 2)
        self.assertEqual(result['temporary_agent_count'], 2)

    def test_preserves_questions_and_uncertain_provenance_without_extra_fields(self):
        result = normalize([{'parent_worker': 'investigator', 'api_key': 'do-not-render',
            'messages': [{'from': 'tmp-a', 'to': 'tmp-b', 'question': '证据冲突？',
                          'answer': '时间不同。', 'event_id': '$self-reported',
                          'changed_conclusion': False, 'secret': 'do-not-render'}],
            'cleanup': {'status': 'completed', 'summary': '2 agents removed', 'token': 'secret'}}])
        run = result['runs'][0]
        self.assertNotIn('api_key', run)
        self.assertNotIn('secret', run['messages'][0])
        self.assertNotIn('token', run['cleanup'])
        self.assertFalse(run['messages'][0]['changed_conclusion'])
        self.assertEqual(result['provenance'], 'worker_exported_native_snapshot')

    def test_template_escapes_untrusted_snapshot_text(self):
        from jinja2 import Environment, FileSystemLoader
        root = Path(__file__).resolve().parents[1] / 'services/operations-console/app/templates'
        env = Environment(loader=FileSystemLoader(root), autoescape=True)
        env.filters['ts'] = str
        source = (root / 'investigation_job.html').read_text(encoding='utf-8')
        start = source.index('{% set collaboration =')
        end = source.index('<section class="card investigation-report">', start)
        view = normalize([{'reason': '<script>alert(1)</script>', 'nodes': [{'role': '<b>role</b>'}]}])
        html = env.from_string(source[start:end]).render(job={'runtime': {'collaboration_view': view}})
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('未在此单独核验', env.from_string(source[start:end]).render(job={'runtime': {
            'collaboration_view': normalize([{'messages': [{'event_id': '$event'}]}])}}))


if __name__ == '__main__':
    unittest.main()
