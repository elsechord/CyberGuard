"""Connect the Console to a ready native team; preserve native tool capabilities."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = Path('/root/.config/cyberguard/native-task-service')
PLAN = ROOT.parent/'output/native-task-service'
REMOTE = r'''
import json,os,sys
from qwenpaw_worker.api import QwenPawApiClient
p=json.load(sys.stdin)
c=QwenPawApiClient('http://127.0.0.1:8088',timeout=30)
c._request('PUT','/api/models/agentteams-gateway/config',{'base_url':'http://aigw-local.agentteams.io:8080'+p['route_prefix']+'/v1','api_key':os.environ['AGENTTEAMS_WORKER_GATEWAY_KEY'],'generate_kwargs':{'max_tokens':6000}})
profile=c._request('GET','/api/agents/default')
running=profile['running']
running['max_iters']=40
running['auto_title_config']['enabled']=False
c.configure_agent('default',{'running':running})
mcps=c.list_mcp()
print(json.dumps({'native_mcp':[{k:v for k,v in item.items() if k in ('key','enabled')} for item in mcps], 'builtin_tools_enabled':sum(bool(t.get('enabled')) for t in profile['tools']['builtin_tools'].values())}))
'''


def capture(*args):
    return subprocess.check_output(args, text=True)


def main():
    global PRIVATE, PLAN
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-dir', type=Path, default=Path.home()/'.config/cyberguard/native-task-service')
    parser.add_argument('--plan', type=Path, default=ROOT.parent/'output/native-task-service')
    parser.add_argument('--service-env', type=Path, default=Path.home()/'.config/cyberguard/agentteams-local.env')
    parser.add_argument('--matrix-login-url', default='http://127.0.0.1:18080')
    parser.add_argument('--matrix-url', default='http://agentteams-controller:8080')
    parser.add_argument('--matrix-host', default='matrix-local.agentteams.io:18080')
    parser.add_argument('--console-origin', default='http://127.0.0.1:18120')
    args=parser.parse_args()
    PRIVATE, PLAN=args.private_dir.resolve(), args.plan.resolve()
    plan=json.loads((PLAN/'manifest.json').read_text())
    inventory={}
    for role, entry in plan['roles'].items():
        result=subprocess.run(['docker','exec','-i','agentteams-worker-'+entry['worker'],
            '/opt/venv/qwenpaw/bin/python','-c',REMOTE],input=json.dumps(entry),text=True,capture_output=True)
        if result.returncode:
            raise SystemExit('Worker not ready: '+role+'; '+result.stderr.splitlines()[-1].split(':')[0])
        inventory[role]=json.loads(result.stdout)
    workers=json.loads(capture('docker','exec','agentteams-controller','agt','get','workers','-o','json'))['workers']
    teams=json.loads(capture('docker','exec','agentteams-controller','agt','get','teams','-o','json'))['teams']
    team=next(t for t in teams if t['name']==plan['team'])
    leader=next(w for w in workers if w['name']==team['leaderName'])
    local=dict(line.split('=',1) for line in args.service_env.read_text(encoding='utf-8').splitlines() if line and not line.startswith('#') and '=' in line)
    token_path=PRIVATE/'matrix-token'
    if token_path.exists():
        matrix_token=token_path.read_text(encoding='utf-8').strip()
    else:
        login=urllib.request.Request(args.matrix_login_url.rstrip('/')+'/_matrix/client/v3/login',
            data=json.dumps({'type':'m.login.password','identifier':{'type':'m.id.user','user':local['AGENTTEAMS_ADMIN_USER']},'password':local['AGENTTEAMS_ADMIN_PASSWORD']}).encode(),
            headers={'Content-Type':'application/json','Host':args.matrix_host})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(login,timeout=30) as response:
            matrix_token=json.load(response)['access_token']
        fd=os.open(token_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(matrix_token)
    token=capture('docker','exec','agentteams-controller','cat','/var/run/agentteams/cli-token').strip()
    env={'CYBERGUARD_AGENTTEAMS_MATRIX_URL':args.matrix_url,'CYBERGUARD_AGENTTEAMS_MATRIX_TOKEN':matrix_token,'CYBERGUARD_AGENTTEAMS_MATRIX_HOST':args.matrix_host}
    guard=json.loads((PRIVATE/'model-guard-config.json').read_text())
    env.update(CYBERGUARD_AGENTTEAMS_BACKEND='native', CYBERGUARD_AGENTTEAMS_CONTROLLER_URL='http://agentteams-controller:8090',
        CYBERGUARD_AGENTTEAMS_CONTROLLER_TOKEN=token,CYBERGUARD_AGENTTEAMS_TEAM_ID=plan['team'],
        CYBERGUARD_AGENTTEAMS_LEADER_ROOM_ID=team['teamRoomID'],CYBERGUARD_AGENTTEAMS_LEADER_USER_ID=leader['matrixUserID'],
        CYBERGUARD_GUARD_URL='http://native-model-guard.agentteams.local:8080',CYBERGUARD_GUARD_ADMIN_TOKEN=guard['admin_token'],
        CYBERGUARD_CONSOLE_ORIGIN=args.console_origin,CYBERGUARD_INVESTIGATION_REQUIRE_GUARD_ARMED='true')
    for name, content in [('console.env','\n'.join(k+'='+v for k,v in env.items())+'\n'),
        ('console.override.json',json.dumps({'services':{'operations-console':{'environment':{k:v.replace('$','$$') for k,v in env.items()}}}}))]:
        fd=os.open(PRIVATE/name,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(content)
    (PLAN/'runtime-ready.json').write_text(json.dumps({'team':team,'workers':inventory},indent=2))
    print(json.dumps({'team':plan['team'],'leader_ready':team['leaderReady'],'ready_workers':team['readyWorkers'],'runtime':inventory}))


if __name__=='__main__':main()
