"""Authorize only the new team on the two existing investigation MCP servers."""
import argparse,json,subprocess
from pathlib import Path
REMOTE=r'''
import http.cookiejar,json,os,sys,urllib.request
p=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):return None
o=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),NoRedirect())
def call(method,path,body=None):
 req=urllib.request.Request('http://127.0.0.1:8001'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json'})
 with o.open(req,timeout=20) as r:
  raw=r.read();v=json.loads(raw) if raw else {}
 assert v.get('success',True), 'Console rejected operation'
 return v.get('data',v)
with o.open(p['guard_url'].removesuffix('/v1')+'/health',timeout=10) as r:assert json.load(r)['armed'] is False
call('POST','/session/login',{'username':os.environ['AGENTTEAMS_ADMIN_USER'],'password':os.environ['AGENTTEAMS_ADMIN_PASSWORD']})
consumers=['worker-'+v['worker'] for v in p['roles'].values()]
audit=[]
for name in ('mcp-cyberguard-investigation-readonly','mcp-cyberguard-investigation-report'):
 # This endpoint changes only consumer authorization, preserving secret backend config.
 call('PUT','/v1/mcpServer/consumers',{'mcpServerName':name,'consumers':consumers})
 audit.append({'server':name,'authorized_consumers':consumers,'mode':'replace_task_specific_consumers'})
print(json.dumps(audit))
'''
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 plan=json.loads((a.plan/'manifest.json').read_text())
 assert plan['team'].startswith('cg-') and not a.out.exists()
 assert all(v['worker']==plan['team']+'-'+r for r,v in plan['roles'].items())
 proc=subprocess.run(['docker','exec','-i','agentteams-controller','python3','-c',REMOTE],input=json.dumps(plan),text=True,capture_output=True,timeout=90)
 if proc.returncode:
  safe=[line for line in proc.stderr.splitlines() if line.startswith(('urllib.error.HTTPError:','AssertionError:','TypeError:','AttributeError:'))]
  print('\n'.join(safe))
  raise SystemExit('MCP authorization failed; keep guard disarmed. No secret response printed.')
 a.out.write_text(proc.stdout);print('Authorized only the fresh team on investigation MCP endpoints; no model call.')
