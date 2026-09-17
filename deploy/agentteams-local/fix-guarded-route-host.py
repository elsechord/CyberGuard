"""Repair only the exact local-host selector on existing role-bound routes."""
import importlib.util,json,sys,subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('audit',Path(__file__).with_name('audit-guarded-routing.py'));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
plan=json.loads((Path(sys.argv[1])/'manifest.json').read_text())
# Reuse audited console transport and verify old/new allowed domain sets before mutation.
source=mod.REMOTE[:mod.REMOTE.index("routes=call")]+'''
audit=[]
for role,entry in p['roles'].items():
 route=call('GET','/v1/ai/routes/'+entry['route'])
 assert set(route['domains']) in ({'aigw-local.agentteams.io'},{'aigw-local.agentteams.io','agentteams-controller'}),'Unexpected previous domains'
 assert 'worker-'+entry['worker'] in route['authConfig']['allowedConsumers'],'Consumer mismatch'
 assert not any(x.startswith('worker-cg-inv005-') and x!='worker-'+entry['worker'] for x in route['authConfig']['allowedConsumers']),'Sibling consumer allowed'
 assert route['upstreams'][0]['provider']==entry['provider'],'Provider mismatch'
 route['domains']=['aigw-local.agentteams.io','agentteams-controller']
 call('PUT','/v1/ai/routes/'+entry['route'],route)
 after=call('GET','/v1/ai/routes/'+entry['route'])
 assert set(after['domains'])==set(route['domains']),'Host readback mismatch'
 audit.append({'route':entry['route'],'domains':after['domains'],'allowedConsumers':after['authConfig']['allowedConsumers']})
print(json.dumps(audit))
'''
r=subprocess.run(['docker','exec','-i','agentteams-controller','python3','-c',source],input=json.dumps(plan),text=True,capture_output=True,timeout=90)
if r.returncode:
 print('\n'.join(x for x in r.stderr.splitlines() if x.startswith(('urllib.error.HTTPError:','AssertionError:','KeyError:','TypeError:','NameError:'))))
 print('Exception type: '+r.stderr.splitlines()[-1].split(':')[0])
 raise SystemExit('Explicit host route repair failed; guard remains disarmed')
Path(sys.argv[2]).write_text(r.stdout);print('Explicit local worker host added to role routes only.')
