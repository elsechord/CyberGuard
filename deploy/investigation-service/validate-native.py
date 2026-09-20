"""Run one synthetic investigation through the native scheduler and public Skill."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
PRIVATE=Path('/root/.config/cyberguard/native-task-service')
OUT=ROOT.parent/'output/native-task-service'
ORIGIN='http://127.0.0.1:18136'


def main():
    def docker(*args): return subprocess.check_output(['docker',*args],text=True).strip()
    docker('run','-d','--name','cyberguard-native-validation','--network','agentteams-net',
        '--env-file',str(PRIVATE/'console.env'),'-e','CYBERGUARD_CONSOLE_DB=/data/console.db',
        '-e','CYBERGUARD_COOKIE_SECURE=false','-v','cyberguard-native-validation:/data',
        '-p','127.0.0.1:18136:8080','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=32m',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true','cyberguard/operations-console:'+ (ROOT/'VERSION').read_text().strip())
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(30):
        try:
            opener.open(ORIGIN+'/healthz',timeout=2).close();break
        except OSError:time.sleep(1)
    code="from app import apikeys,auth; from pathlib import Path; _,k,_=apikeys.create_key(name='native-skill-validation',scopes=['investigations:read','investigations:write'],created_by='local-validation',expires_at=apikeys.expiry_from_days(1)); p=Path('/data/validation-key');p.write_text(k);p.chmod(0o600);auth.create_user('native-preview','local-native-preview-2026','admin');auth.finish_setup()"
    docker('exec','cyberguard-native-validation','python','-c',code)
    key=docker('exec','cyberguard-native-validation','cat','/data/validation-key')
    fd=os.open(PRIVATE/'validation-key',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(key)
    guard=json.loads((PRIVATE/'model-guard-config.json').read_text())
    def request(origin,path,token,body=None):
        req=urllib.request.Request(origin+path,data=json.dumps(body).encode() if body is not None else None,
             headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with opener.open(req,timeout=30) as response:return json.load(response)
    request('http://127.0.0.1:18112','/admin/arm',guard['admin_token'],{})
    payload={'title':'原生 Task 调度：核对登录记录', 'objective':'请调查这条合成登录记录能否支持账号被盗的判断，由另一位 Worker 独立复核，并给出简洁中文报告和原文引用。仅分析，不执行处置。',
             'domain':'security','materials':[{'source_type':'server_log','name':'合成登录日志','media_type':'text/plain',
             'content':'SYNTHETIC EXERCISE ONLY\n2026-09-20T00:00:00Z user=demo host=exercise-app result=login_success src=192.0.2.10\nNo other records were collected.',
             'interpretation':'提交者猜测账号可能被盗，但没有提供其他证据。'}]}
    (OUT/'request.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf8')
    env=dict(os.environ,CYBERGUARD_CONSOLE_URL=ORIGIN,CYBERGUARD_SKILL_KEY_FILE=str(PRIVATE/'validation-key'))
    cli=[ 'python3',str(ROOT/'integrations/agent-skills/cyberguard/scripts/cyberguard.py')]
    sent=subprocess.run(cli+['submit',str(OUT/'request.json'),'--idempotency-key','native-task-validation-001','--out',str(OUT/'receipt.json')],env=env,text=True,capture_output=True,check=True)
    job_id=json.loads(sent.stdout)['id']
    print(json.dumps({'job_id':job_id}),flush=True)
    previous=None
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        value=request(ORIGIN,'/api/v1/investigations/'+job_id,key)
        job=value['data']
        (OUT/'job-result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
        workflow=job.get('runtime',{}).get('workflow',{})
        marker=(job['status'],job['stage'],[(n['id'],n['status']) for n in workflow.get('nodes',[])])
        if marker!=previous:print(json.dumps({'status':marker[0],'stage':marker[1],'tasks':marker[2]},ensure_ascii=False),flush=True);previous=marker
        if job['status'] in ('completed','failed','canceled'):break
        time.sleep(5)
    else:
        request(ORIGIN,'/api/v1/investigations/'+job_id+'/cancel',key,{})
    status=request('http://127.0.0.1:18112','/admin/status',guard['admin_token'])
    (OUT/'budget-status.json').write_text(json.dumps(status,indent=2))
    print(json.dumps({'model_usage':status['run']['usage']}),flush=True)
    if job['status']=='completed':
        subprocess.run(cli+['result',job_id,'--out',str(OUT/'skill-report.json')],env=env,check=True)


if __name__=='__main__':main()
