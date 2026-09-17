"""Set the native gateway provider's explicit Higress host without changing role identity."""
import argparse,json,subprocess
from pathlib import Path
REMOTE=r'''
import json,os,sys,urllib.request
from qwenpaw_worker.api import QwenPawApiClient
p=json.load(sys.stdin)
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
with urllib.request.urlopen(p['guard_url'].removesuffix('/v1')+'/health') as r:assert json.load(r)['armed'] is False
c=QwenPawApiClient('http://127.0.0.1:8088',timeout=30)
before=next(x for x in c._request('GET','/api/models') if x['id']=='agentteams-gateway')
expected='http://aigw-local.agentteams.io:8080'+p['route_prefix']+'/v1'
assert before['base_url'] in (expected,expected.replace('aigw-local.agentteams.io','agentteams-controller'))
c._request('PUT','/api/models/agentteams-gateway/config',{'base_url':expected,'api_key':os.environ['AGENTTEAMS_WORKER_GATEWAY_KEY'],'generate_kwargs':before.get('generate_kwargs') or {}})
after=next(x for x in c._request('GET','/api/models') if x['id']=='agentteams-gateway')
assert after['base_url']==expected
print(json.dumps({'before_base_url':before['base_url'],'after_base_url':after['base_url'],'credential':'existing_worker_gateway_key_preserved'}))
'''
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 plan=json.loads((a.plan/'manifest.json').read_text());assert not a.out.exists();result={}
 for role,entry in plan['roles'].items():
  r=subprocess.run(['docker','exec','-i','agentteams-worker-'+entry['worker'],'/opt/venv/qwenpaw/bin/python','-c',REMOTE],input=json.dumps({**entry,'guard_url':plan['guard_url']}),text=True,capture_output=True,timeout=60)
  if r.returncode:raise SystemExit('Native role host correction failed; guard remains disarmed')
  result[role]=json.loads(r.stdout);a.out.write_text(json.dumps(result,indent=2)+'\n')
 print('Native providers now use the explicit Higress host; role gateway credentials preserved.')
