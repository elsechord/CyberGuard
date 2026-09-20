"""Install local collaboration assets into running native Workers, without LLM calls.

Run in WSL as root. By default use output/native-task-service/manifest.json;
pass --workers NAME [NAME ...] to install into an explicit Worker list.
"""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess


REMOTE = r'''
import base64, hashlib, json, pathlib, runpy, sys
from qwenpaw_worker.api import QwenPawApiClient
p = json.load(sys.stdin)
c = QwenPawApiClient('http://127.0.0.1:8088', timeout=30)
before = c._request('GET', '/api/agents/default')
workspace = pathlib.Path(before['workspace_dir']).resolve()
native = pathlib.Path('/opt/agentteams/qwenpaw-builtin/plugins/workerflow/workerflow/mcp/server.py')
if not native.is_file():
    raise SystemExit('Native WorkerFlow module is missing')
installed = []
for name, encoded in p['files'].items():
    relative = pathlib.PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise SystemExit('Invalid asset path')
    if name in ('native_collaboration.py', 'case_packet.py', 'native_identity.py'):
        destination = pathlib.Path('/opt/cyberguard-collaboration') / name
    elif relative.parts[0] in ('skills', 'subagents'):
        destination = workspace.joinpath(*relative.parts)
    else:
        continue
    data = base64.b64decode(encoded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    installed.append({'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
taskflow = pathlib.Path('/opt/agentteams/qwenpaw-builtin/plugins/teamharness/teamharness/mcp/server.py')
patch_source = runpy.run_path('/opt/cyberguard-collaboration/native_identity.py')['patch_native_source']
old_source = taskflow.read_text()
new_source = patch_source(old_source)
compile(new_source, str(taskflow), 'exec')
taskflow.write_text(new_source)
import qwenpaw_worker.update
runtime_source = pathlib.Path(qwenpaw_worker.update.__file__)
patch_runtime = runpy.run_path('/opt/cyberguard-collaboration/native_identity.py')['patch_runtime_source']
runtime_text = patch_runtime(runtime_source.read_text())
compile(runtime_text, str(runtime_source), 'exec')
runtime_source.write_text(runtime_text)
c.refresh_and_enable_skills(p['skills'])
skills = c._request('GET', '/api/skills')
selected = [item for item in skills if item.get('name') in p['skills']]
after = c._request('GET', '/api/agents/default')
preserved = all(before.get(k) == after.get(k) for k in ('running', 'active_model', 'tools', 'mcp', 'channels'))
if not preserved:
    raise SystemExit('Default runtime configuration changed unexpectedly')
print(json.dumps({'worker':p['worker'], 'workspace':str(workspace), 'installed':installed,
 'templates':[x.name for x in sorted((workspace/'subagents').iterdir()) if (x/'AGENTS.md').is_file()],
 'skills':[{k:v for k,v in item.items() if k in ('name','enabled','source')} for item in selected],
 'native_mcp':[{k:v for k,v in item.items() if k in ('key','enabled')} for item in c.list_mcp()],
 'communication_tools':{k:v.get('enabled') for k,v in after.get('tools',{}).get('builtin_tools',{}).items()
    if k in ('list_agents','chat_with_agent','submit_to_agent','check_agent_task','spawn_subagent')},
 'default_configuration_preserved':preserved, 'native_identity_patch_changed':old_source != new_source,
 'model_calls':0},ensure_ascii=False))
'''


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', nargs='+')
    parser.add_argument('--manifest', type=Path, default=root.parent/'output/native-task-service/manifest.json')
    args = parser.parse_args()
    assets = Path(__file__).parent/'collaboration'
    helper = assets/'native_collaboration.py'
    if not helper.is_file():
        raise SystemExit('Collaboration helper is not ready; nothing installed')
    compile(helper.read_text(encoding='utf-8'), str(helper), 'exec')
    skills = sorted(path.parent.name for path in (assets/'skills').glob('*/SKILL.md'))
    if not skills or not list((assets/'subagents').glob('*/AGENTS.md')):
        raise SystemExit('Collaboration skills/templates are not ready; nothing installed')
    files = {path.relative_to(assets).as_posix():base64.b64encode(path.read_bytes()).decode('ascii')
             for path in sorted(assets.rglob('*')) if path.is_file() and path.suffix in ('.py','.md')}
    workers = args.workers
    if not workers:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        workers = [entry['worker'] for entry in manifest['roles'].values()]
    for worker in dict.fromkeys(workers):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', worker):
            raise SystemExit('Invalid Worker name')
        payload = json.dumps(dict(worker=worker, skills=skills, files=files))
        result = subprocess.run(['docker','exec','-i','agentteams-worker-'+worker,
                                 '/opt/venv/qwenpaw/bin/python','-c',REMOTE],
                                input=payload, text=True, capture_output=True)
        if result.returncode:
            raise SystemExit('Install failed for '+worker+': '+result.stderr[-2000:])
        print(result.stdout.strip(), flush=True)


if __name__ == '__main__':
    main()
