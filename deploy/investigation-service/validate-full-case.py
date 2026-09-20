"""Bounded full-case replay via the public Skill; no messages after submission.

Run in WSL as root. A fresh Matrix source room separates each attempt's context.
The existing localhost validation Console database and previous ledgers are kept.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = Path('/root/.config/cyberguard/native-task-service')
ORIGIN = 'http://127.0.0.1:18136'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(origin, path, token, body=None, host=None):
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    if host:
        headers['Host'] = host
    req = urllib.request.Request(origin + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with OPENER.open(req, timeout=30) as response:
        return json.load(response)


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def arm(run_id):
    cfg = json.loads((PRIVATE / 'model-guard-config.json').read_text())
    status = request('http://127.0.0.1:18112', '/admin/status', cfg['admin_token'])
    if status['run']['usage']['concurrency_used']:
        raise RuntimeError('Existing model requests are still running')
    if status['run']['status'] == 'open':
        request('http://127.0.0.1:18112', '/admin/close', cfg['admin_token'], {})
    if cfg['run_id'] == run_id:
        raise RuntimeError('Use a new attempt ID; never reset an existing ledger')
    cfg.update(run_id=run_id, limits=dict(max_requests=120, max_requests_per_role=90,
        max_input_tokens=5000000, max_output_tokens=150000, max_concurrency=4))
    (PRIVATE / 'model-guard-config.json').write_text(json.dumps(cfg))
    (PRIVATE / 'model-guard.env').write_text('CYBERGUARD_MODEL_GUARD_CONFIG=' + json.dumps(cfg, separators=(',', ':')) + '\n')
    docker('rm', '-f', 'cyberguard-native-model-guard')
    docker('run', '-d', '--name', 'cyberguard-native-model-guard', '--network', 'agentteams-net',
        '--network-alias', 'native-model-guard.agentteams.local', '--env-file', str(PRIVATE / 'model-guard.env'),
        '-e', 'CYBERGUARD_DATA_DIR=/data', '-v', 'cyberguard-native-model-budget:/data',
        '-p', '127.0.0.1:18112:8080', '--read-only', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m', 'cyberguard/model-guard:native')
    for _ in range(30):
        try:
            request('http://127.0.0.1:18112', '/admin/arm', cfg['admin_token'], {})
            return cfg
        except OSError:
            time.sleep(1)
    raise RuntimeError('Model guard did not become ready')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--deadline', type=int, default=1200)
    args = parser.parse_args()
    if not args.attempt.isalnum():
        raise ValueError('attempt must be alphanumeric')
    out = ROOT.parent / 'output/full-case' / args.attempt
    out.mkdir(parents=True, exist_ok=False)
    env = dict(line.split('=', 1) for line in (PRIVATE / 'console.env').read_text().splitlines() if '=' in line)
    private_env = PRIVATE / ('case-' + args.attempt + '.env')
    fd = os.open(private_env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('\n'.join(k + '=' + v for k, v in env.items()) + '\n')
    # Let the dispatcher release its lease before reusing the durable database.
    docker('stop', '--time', '10', 'cyberguard-native-validation')
    docker('rm', 'cyberguard-native-validation')
    docker('run', '-d', '--name', 'cyberguard-native-validation', '--network', 'agentteams-net',
        '--env-file', str(private_env), '-e', 'CYBERGUARD_CONSOLE_DB=/data/console.db',
        '-e', 'CYBERGUARD_COOKIE_SECURE=false', '-v', 'cyberguard-native-validation:/data',
        '-p', '127.0.0.1:18136:8080', '--read-only', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
        'cyberguard/operations-console:' + (ROOT/'VERSION').read_text().strip())
    key = (PRIVATE / 'validation-key').read_text()
    for _ in range(30):
        try:
            request(ORIGIN, '/api/v1/investigations', key)
            break
        except OSError:
            time.sleep(1)
    cfg = arm('CG-FULL-CASE-' + args.attempt)
    cli = ['python3', str(ROOT / 'integrations/agent-skills/cyberguard/scripts/cyberguard.py')]
    client_env = dict(os.environ, CYBERGUARD_CONSOLE_URL=ORIGIN, CYBERGUARD_SKILL_KEY_FILE=str(PRIVATE / 'validation-key'))
    case = ROOT / 'deploy/investigation-service/cases/miner-recovery.json'
    job = None
    started = time.monotonic()
    try:
        sent = subprocess.run(cli + ['submit', str(case), '--idempotency-key', 'full-case-' + args.attempt,
            '--out', str(out / 'receipt.json')], env=client_env, text=True, capture_output=True, check=True)
        job_id = json.loads(sent.stdout)['id']
        print(json.dumps({'job_id': job_id}), flush=True)
        (out / 'request.json').write_text(case.read_text(encoding='utf8'), encoding='utf8')
        previous = None
        while time.monotonic() - started < args.deadline:
            value = request(ORIGIN, '/api/v1/investigations/' + job_id, key)
            job = value['data']
            (out / 'job-result.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
            workflow = job.get('runtime', {}).get('workflow', {})
            marker = (job['status'], job['stage'], [(n['id'], n['status']) for n in workflow.get('nodes', [])])
            if marker != previous:
                print(json.dumps({'status': marker[0], 'stage': marker[1], 'tasks': marker[2]}, ensure_ascii=False), flush=True)
                previous = marker
            if job['status'] in ('completed', 'failed', 'canceled'):
                break
            time.sleep(5)
        else:
            request(ORIGIN, '/api/v1/investigations/' + job_id + '/cancel', key, {})
            job = request(ORIGIN, '/api/v1/investigations/' + job_id, key)['data']
            (out / 'job-result.json').write_text(json.dumps({'data': job}, ensure_ascii=False, indent=2), encoding='utf8')
        if job['status'] == 'completed':
            subprocess.run(cli + ['result', job_id, '--out', str(out / 'skill-report.json')], env=client_env, check=True, stdout=subprocess.DEVNULL)
        (out / 'run-summary.json').write_text(json.dumps({'job_id': job_id, 'status': job['status'],
            'elapsed_seconds': round(time.monotonic() - started, 1), 'manual_messages_after_submission': 0,
            'semantic_acceptance': 'requires_report_review'}, indent=2))
    finally:
        status = request('http://127.0.0.1:18112', '/admin/close', cfg['admin_token'], {})
        (out / 'model-budget.json').write_text(json.dumps(status, indent=2))
        print(json.dumps({'model_usage': status['run']['usage']}), flush=True)


if __name__ == '__main__':
    main()
