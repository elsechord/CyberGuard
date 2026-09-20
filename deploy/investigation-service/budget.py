"""Read, arm or close the explicitly configured local model budget; never reset it."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'arm', 'close', 'new-run'))
    parser.add_argument('--private-dir', type=Path, default=Path.home()/'.config/cyberguard/native-task-service')
    parser.add_argument('--url', default='http://127.0.0.1:18112')
    parser.add_argument('--run-id', help='Required for new-run; preserves the previous ledger and role credentials')
    args = parser.parse_args()
    config = json.loads((args.private_dir/'model-guard-config.json').read_text(encoding='utf-8'))
    action='status' if args.action == 'new-run' else args.action
    request = urllib.request.Request(args.url.rstrip('/')+'/admin/'+action,
        data=None if action == 'status' else b'{}',
        headers={'Authorization':'Bearer '+config['admin_token'], 'Content-Type':'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        result = json.load(response)
    if args.action == 'new-run':
        if not args.run_id or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,100}',args.run_id) or args.run_id == config['run_id']:
            raise SystemExit('Supply a new valid --run-id')
        if result['run']['status'] == 'open' or result['run']['usage']['concurrency_used']:
            raise SystemExit('Close and drain the current budget first')
        # Never remove the volume: a previously used run ID retains its ledger.
        config['run_id']=args.run_id
        for name,content in [('model-guard-config.json',json.dumps(config)),('model-guard.env','CYBERGUARD_MODEL_GUARD_CONFIG='+json.dumps(config,separators=(',',':'))+'\n')]:
            target=args.private_dir/name
            temp=target.with_suffix(target.suffix+'.new')
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:stream.write(content)
            os.replace(temp,target)
        subprocess.run(['docker','stop','cyberguard-native-model-guard'],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','rm','cyberguard-native-model-guard'],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','run','-d','--name','cyberguard-native-model-guard','--network','agentteams-net',
            '--network-alias','native-model-guard.agentteams.local','--env-file',str(args.private_dir/'model-guard.env'),
            '-e','CYBERGUARD_DATA_DIR=/data','-v','cyberguard-native-model-budget:/data','-p','127.0.0.1:18112:8080',
            '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:rw,noexec,nosuid,size=32m',
            'cyberguard/model-guard:native'],check=True,stdout=subprocess.DEVNULL)
        print(json.dumps({'run_id':args.run_id,'armed':False,'previous_ledger':'preserved','next':'Check status, then arm explicitly'}))
        return
    # Deliberately report only operational state, never stored configuration.
    print(json.dumps({key:result[key] for key in ('armed','run','denials','status') if key in result}, indent=2))


if __name__ == '__main__':
    main()
