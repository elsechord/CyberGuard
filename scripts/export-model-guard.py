"""Export one local guard run without exporting its configuration or credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation.model_runner import redact_tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/cyberguard/model-guard-config.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix' or stat.S_IMODE(args.config.stat().st_mode) & 0o077:
        raise SystemExit('Private POSIX configuration required')
    if args.output.exists():
        raise SystemExit('Output exists; refusing to overwrite prior evidence')
    config = json.loads(args.config.read_text())
    # Capture only this run's records. Docker environment/configuration never enters stdout.
    code = '''import hashlib,json,sys
from pathlib import Path
from cyberguard_investigation.admission import AdmissionLedger
run_id = sys.argv[1]
root = Path('/data')
records = []
for path in sorted(root.glob('*.json')):
    data = path.read_bytes()
    value = json.loads(data)
    if value.get('run_id') == run_id:
        records.append({'name':path.name,'source_sha256':hashlib.sha256(data).hexdigest(),'record':value})
print(json.dumps({'run':AdmissionLedger(root/'admission.sqlite').get_run(run_id),'records':records}))
'''
    result = subprocess.run(['docker', 'exec', '-i', 'cyberguard-model-guard', 'python', '-', config['run_id']],
                            input=code, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise SystemExit('Guard export failed; raw diagnostics withheld')
    value = json.loads(result.stdout)
    secrets = [config['upstream_key'], config['admin_token'], *(r['token'] for r in config['roles'].values())]
    for role, item in config['roles'].items():
        worker = item['model_alias'].removesuffix('-model')
        raw = subprocess.run(['docker', 'inspect', 'agentteams-worker-' + worker], capture_output=True, text=True, timeout=20)
        if raw.returncode == 0:
            for entry in json.loads(raw.stdout)[0].get('Config', {}).get('Env', []):
                key, _, secret = entry.partition('=')
                if key == 'AGENTTEAMS_FS_ACCESS_KEY' and secret == worker:
                    continue  # Public MinIO account ID, not its secret key.
                if any(part in key.upper() for part in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD')) and len(secret) >= 16:
                    secrets.append(secret)
    forms = []
    for secret in secrets:
        for _ in range(4):
            forms.append(secret)
            secret = json.dumps(secret, ensure_ascii=True)[1:-1]
    value = redact_tree(value, sorted(set(forms), key=len, reverse=True))
    args.output.mkdir(parents=True, exist_ok=False)
    files = []
    for item in value.pop('records'):
        name = item['name']
        if Path(name).name != name:
            raise SystemExit('Invalid trace filename')
        path = args.output / name
        path.write_text(json.dumps(item['record'], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        files.append({'file':name,'source_sha256':item['source_sha256'],'export_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    value.update(files=files, export_notes=['Known credentials redacted; not a general secret detector.',
        'Source hashes refer to persisted guard records; exported hashes include export-time redaction.',
        'Ledger and traces are a local snapshot; unknown/in-flight usage can settle later.'])
    (args.output/'manifest.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'run_id':config['run_id'],'records_exported':len(files),'status':value['run']['status']}))


if __name__ == '__main__':
    main()
