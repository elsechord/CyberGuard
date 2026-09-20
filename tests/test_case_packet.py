import hashlib
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'deploy/investigation-service/collaboration/case_packet.py'
spec = importlib.util.spec_from_file_location('case_packet', PATH)
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)


class CasePacketTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'INV-a', 'materials': [{'material_id': 'MAT-a', 'content': '原文\nno miner',
            'sha256': hashlib.sha256('原文\nno miner'.encode()).hexdigest()}]}
        self.report = {'job_id': 'INV-a', 'role': 'verifier', 'summary': '复核', 'findings': [
            {'claim': 'no miner', 'status': 'supported', 'limitations': '',
             'citations': [{'material_id': 'MAT-a', 'quote': 'no miner'}]}], 'unknowns': [], 'next_steps': []}

    def test_original_bytes_and_report(self):
        self.assertTrue(packet.check_report(self.case, self.report)['valid'])

    def test_model_copied_hash_or_evidence_cannot_pass(self):
        self.case['materials'][0]['content'] += '\n'
        with self.assertRaises(ValueError):
            packet.check_report(self.case, self.report)

    def test_wrong_schema_or_interpretation_quote_cannot_pass(self):
        with self.assertRaises(ValueError):
            packet.check_report(self.case, {'task_id': 't', 'claims': []})
        self.report['findings'][0]['citations'][0]['quote'] = 'submitter thinks clean'
        with self.assertRaises(ValueError):
            packet.check_report(self.case, self.report)


if __name__ == '__main__':
    unittest.main()
