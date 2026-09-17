"""Audit role routes and issue guarded/unauthorized non-inference probes."""
import argparse,json,subprocess
from pathlib import Path
REMOTE=r'''
import http.cookiejar,json,os,sys,urllib.request
p=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):return None
o=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),NoRedirect())
def call(method,path,body=None):
 r=urllib.request.Request('http://127.0.0.1:8001'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json'})
 with o.open(r,timeout=20) as resp:
  raw=resp.read();v=json.loads(raw) if raw else {}
 return v.get('data',v) if isinstance(v,dict) else v
with o.open(p['guard_url'].removesuffix('/v1')+'/health') as r:assert json.load(r)['armed'] is False
call('POST','/session/login',{'username':os.environ['AGENTTEAMS_ADMIN_USER'],'password':os.environ['AGENTTEAMS_ADMIN_PASSWORD']})
routes=call('GET','/v1/ai/routes')
if isinstance(routes,dict):routes=routes.get('items',routes.get('records',routes.get('data')))
assert isinstance(routes,list),'Unknown routes list shape'
audit=[]
for role,entry in p['roles'].items():
 consumer='worker-'+entry['worker']; granted=[]
 for route in routes:
  full=call('GET','/v1/ai/routes/'+route['name'])
  auth=full['authConfig']
  assert auth['enabled'],'Unauthenticated AI route present'
  if consumer in auth['allowedConsumers']:granted.append(full['name'])
 assert granted==[entry['route']], 'Worker has unexpected model route authorization'
 provider=call('GET','/v1/ai/providers/'+entry['provider'])
 cfg=provider['rawConfigs']
 assert cfg['openaiCustomUrl']==p['guard_url'].rstrip('/'),'Unexpected provider destination'
 own=call('GET','/v1/ai/routes/'+entry['route'])
 audit.append({'role':role,'authorized_routes':granted,'domains':own['domains'],'guard_url':cfg['openaiCustomUrl']})
print(json.dumps(audit))
'''
PROBE=r'''
import json,os,sys,urllib.request,urllib.error
p=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):return None
o=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
with o.open('http://127.0.0.1:8088/api/models',timeout=20) as r:providers=json.load(r)
base=next(x['base_url'] for x in providers if x['id']=='agentteams-gateway').rstrip('/')
if base.endswith('/v1'):base=base[:-3]
from urllib.parse import urlsplit,urlunsplit
parts=urlsplit(base);root=urlunsplit((parts.scheme,parts.netloc,'','',''))
results=[]
for label,path,model in p['probes']:
 req=urllib.request.Request(root+path,data=json.dumps({'model':model,'messages':[{'role':'user','content':'Disarmed local routing preflight; no inference authorized.'}],'max_tokens':1}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['AGENTTEAMS_WORKER_GATEWAY_KEY']})
 try:
  with o.open(req,timeout=15) as r:code=r.status;raw=r.read()
 except urllib.error.HTTPError as e:code=e.code;raw=e.read()
 try:v=json.loads(raw);error=v.get('error',{});errorcode=error.get('code') if isinstance(error,dict) else None
 except (ValueError,AttributeError):errorcode=None
 assert code>=400, 'Unexpected model admission'
 if label=='own':assert errorcode=='guard_not_armed', 'Own route status='+str(code)+' error_code='+str(errorcode)
 else:assert code in (401,403),'Other route did not reject credential'
 results.append({'route':label,'http_status':code,'error_code':errorcode})
print(json.dumps({'probes':results,'upstream_provider_key_in_environment':any(k in os.environ for k in ('AGENTTEAMS_LLM_API_KEY','OPENAI_API_KEY'))}))
'''
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 plan=json.loads((a.plan/'manifest.json').read_text());assert not a.out.exists()
 def run(container,script,payload,python='python3'):
  r=subprocess.run(['docker','exec','-i',container,python,'-c',script],input=json.dumps(payload),text=True,capture_output=True,timeout=100)
  if r.returncode:
   safe=[x for x in r.stderr.splitlines() if x.startswith(('AssertionError:','urllib.error.HTTPError:','KeyError:','TypeError:'))]
   print('\n'.join(safe));raise SystemExit('Routing audit failed; guard remains disarmed')
  return json.loads(r.stdout)
 result={'route_acl':run('agentteams-controller',REMOTE,plan),'workers':{}}
 a.out.write_text(json.dumps(result,indent=2))
 for role,entry in plan['roles'].items():
  sibling=next(v for r,v in plan['roles'].items() if r!=role)
  result['workers'][role]=run('agentteams-worker-'+entry['worker'],PROBE,{'probes':[
   ['own',entry['route_prefix']+'/v1/chat/completions',entry['model_alias']],
   ['legacy','/v1/chat/completions',entry['model_alias']],
   ['sibling',sibling['route_prefix']+'/v1/chat/completions',sibling['model_alias']]]},'/opt/venv/qwenpaw/bin/python')
  a.out.write_text(json.dumps(result,indent=2)+'\n')
 print('All role routes bound to disarmed guard; legacy and sibling authorization rejected.')
