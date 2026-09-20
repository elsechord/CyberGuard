"""Isolated preparation checks: no Docker, network, private host files or LLM calls."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

SCRIPT=Path(__file__).with_name('prepare-native-team.py')


class PreparationTests(unittest.TestCase):
    def test_budget_rotation_preserves_credentials_and_never_deletes_volume(self):
        spec=importlib.util.spec_from_file_location('budget',SCRIPT.with_name('budget.py'))
        budget=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(budget)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original={'run_id':'RUN-OLD','admin_token':'TEST_ADMIN','roles':{'investigator':{'token':'TEST_ROLE'}}}
            (root/'model-guard-config.json').write_text(json.dumps(original))
            response=MagicMock()
            response.__enter__.return_value=io.BytesIO(json.dumps({'run':{'status':'closed','usage':{'concurrency_used':0}}}).encode())
            opener=MagicMock()
            opener.open.return_value=response
            with patch.object(sys,'argv',['budget.py','new-run','--private-dir',str(root),'--run-id','RUN-NEW']), patch.object(budget.urllib.request,'build_opener',return_value=opener), patch.object(budget.subprocess,'run') as run, patch('builtins.print'):
                budget.main()
            updated=json.loads((root/'model-guard-config.json').read_text())
            self.assertEqual(updated,{**original,'run_id':'RUN-NEW'})
            commands=[call.args[0] for call in run.call_args_list]
            self.assertFalse(any('volume' in command for command in commands))
            self.assertIn('cyberguard-native-model-budget:/data',commands[-1])

    def test_fresh_configuration_and_preserved_existing_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            model=root/'model.env'
            marker='TEST_ONLY_NOT_A_REAL_PROVIDER_KEY_1234567890'
            model.write_text('AGENTTEAMS_DEFAULT_MODEL=test-model\nAGENTTEAMS_OPENAI_BASE_URL=https://provider.example/v1\nAGENTTEAMS_LLM_API_KEY='+marker+'\n',encoding='utf-8')
            command=[sys.executable,str(SCRIPT),'--prepare-only','--private-dir',str(root/'private'),'--plan',str(root/'plan'),'--model-env',str(model),'--run-id','TEST-FRESH-001','--name-prefix','cg-clean001']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn(marker,result.stdout+result.stderr)
            plan=json.loads((root/'plan/manifest.json').read_text())
            self.assertEqual(plan['orchestration'],'agentteams_native_tasks')
            self.assertEqual(plan['team'],'cg-clean001')
            for path in (root/'plan').glob('*.json'):
                self.assertNotIn(marker,path.read_text())
            for line in (root/'plan/SHA256SUMS').read_text().splitlines():
                digest,name=line.split('  ',1)
                self.assertEqual(hashlib.sha256((root/'plan'/name).read_bytes()).hexdigest(),digest)
            cfg=json.loads((root/'private/model-guard-config.json').read_text())
            self.assertEqual(cfg['upstream_endpoint'],'https://provider.example/v1/chat/completions')
            self.assertEqual(cfg['tool_policy'],'runtime')
            before=(root/'private/model-guard-config.json').read_bytes()
            repeated=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(repeated.returncode,0)
            self.assertEqual(before,(root/'private/model-guard-config.json').read_bytes())

    def test_missing_model_key_creates_no_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            model=root/'model.env'
            model.write_text('AGENTTEAMS_DEFAULT_MODEL=test-model\nAGENTTEAMS_OPENAI_BASE_URL=https://provider.example/v1\n',encoding='utf-8')
            result=subprocess.run([sys.executable,str(SCRIPT),'--prepare-only','--private-dir',str(root/'private'),'--plan',str(root/'plan'),'--model-env',str(model)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((root/'plan').exists())


if __name__=='__main__':
    unittest.main()
