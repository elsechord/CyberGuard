"""Exercise a separate native console session while the guard is disarmed.

No formal Matrix task is sent. The upstream model must remain inaccessible.
Only session identity and response digest are exported, never request content.
"""
import argparse,json,subprocess,uuid
from pathlib import Path
REMOTE=r'''
import hashlib,json,sys,urllib.request,urllib.error
p=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):return None
o=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
with o.open(p['guard_url'].removesuffix('/v1')+'/health',timeout=10) as r:assert json.load(r)['armed'] is False
body={'session_id':p['session_id'],'user_id':'cyberguard-operator-preflight','channel':'console',
 'input':[{'role':'user','content':[{'type':'text','text':'Local disarmed schema preflight. Do not investigate, use tools, or create tasks. The model endpoint is intentionally disabled.'}]}]}
req=urllib.request.Request('http://127.0.0.1:8088/api/console/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
try:
 with o.open(req,timeout=60) as r:status=r.status;raw=r.read()
except urllib.error.HTTPError as e:status=e.code;raw=e.read()
print(json.dumps({'session_id':p['session_id'],'channel':'console','http_status':status,'response_sha256':hashlib.sha256(raw).hexdigest(),'response_bytes':len(raw),'formal_matrix_room_used':False}))
'''
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 plan=json.loads((a.plan/'manifest.json').read_text());assert not a.out.exists()
 result={'run_id':plan['run_id'],'sessions':{}}
 for role,entry in plan['roles'].items():
  session='disarmed-preflight-'+entry['worker']+'-'+uuid.uuid4().hex
  r=subprocess.run(['docker','exec','-i','agentteams-worker-'+entry['worker'],'/opt/venv/qwenpaw/bin/python','-c',REMOTE],input=json.dumps({'guard_url':plan['guard_url'],'session_id':session}),text=True,capture_output=True,timeout=80)
  if r.returncode:raise SystemExit('Native schema probe failed; keep guard disarmed and inspect local state')
  result['sessions'][role]=json.loads(r.stdout);a.out.write_text(json.dumps(result,indent=2)+'\n')
 print('Separate native console sessions probed. Inspect guard declarations; this is not a completed model task.')
