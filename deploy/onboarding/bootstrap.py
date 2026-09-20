"""Start the local installation helper and Console on Linux / WSL2.

Run with sudo/root in the repository checkout. Model credentials are entered in
the authenticated Console, never in shell arguments or generated prompts.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def private_write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.new-' + secrets.token_hex(4))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w', encoding='utf8', newline='\n') as stream:
        stream.write(content)
    os.replace(temp, path)


def prepare(args):
    private = args.private_dir.resolve()
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime = args.run_dir.resolve()
    runtime.mkdir(parents=True, exist_ok=True, mode=0o750)
    os.chown(runtime, 0, 10003)
    os.chmod(runtime, 0o750)
    token = private / 'onboarding-token'
    if not token.exists():
        private_write(token, secrets.token_urlsafe(48))
    private_write(runtime / 'token', token.read_text(encoding='utf8'), 0o640)
    os.chown(runtime / 'token', 0, 10003)
    os.chmod(runtime / 'token', 0o640)
    service_env = args.service_env.resolve()
    if not service_env.exists():
        if service_env.name != 'agentteams-local.env':
            raise ValueError('Service environment must be named agentteams-local.env')
        subprocess.run([sys.executable, str(ROOT/'deploy/agentteams-local/prepare-local.py'),
                        '--directory', str(service_env.parent)], check=True)
    config = dict(repo=str(ROOT), private_dir=str(private), plan=str(args.plan.resolve()),
                  service_env=str(service_env), token_file=str(runtime/'token'),
                  run_dir=str(runtime), console_origin=args.console_origin,
                  console_containers=['cyberguard-operations-console-1'],
                  compose_overlays=[str(ROOT/'compose.onboarding.yaml')])
    file = private / 'onboarding-service.json'
    private_write(file, json.dumps(config, indent=2) + '\n')
    return file, runtime


def start(file, runtime, private):
    unit = Path('/etc/systemd/system/cyberguard-onboarding.service')
    systemd = Path('/run/systemd/system').is_dir()
    if systemd:
        # Quoting protects paths containing spaces in systemd's ExecStart parser.
        command = ' '.join(json.dumps(str(v)) for v in
                           [sys.executable, ROOT/'deploy/onboarding/service.py',
                            '--config', file, '--socket', runtime/'service.sock'])
        cfg = json.loads(file.read_text(encoding='utf8'))
        prepare_command = ' '.join(json.dumps(str(v)) for v in
            [sys.executable, ROOT/'deploy/onboarding/bootstrap.py', '--prepare-only',
             '--private-dir', private, '--plan', cfg['plan'], '--service-env', cfg['service_env'],
             '--run-dir', runtime, '--console-origin', cfg['console_origin']])
        private_write(unit, '[Unit]\nDescription=CyberGuard local installation helper\nAfter=docker.service\n'
                      '[Service]\nType=simple\nUMask=0077\nExecStartPre=' + prepare_command + '\nExecStart=' + command +
                      '\nRestart=on-failure\nRestartSec=3\n[Install]\nWantedBy=multi-user.target\n', 0o644)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', 'cyberguard-onboarding.service'], check=True)
        subprocess.run(['systemctl', 'restart', 'cyberguard-onboarding.service'], check=True)
    else:
        pid_file = private/'onboarding-service.pid'
        if pid_file.exists():
            pid = int(pid_file.read_text())
            proc = Path('/proc')/str(pid)/'cmdline'
            if proc.exists() and b'deploy/onboarding/service.py' in proc.read_bytes():
                print('Existing installation helper preserved.')
                return
        with (private/'onboarding-service.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, str(ROOT/'deploy/onboarding/service.py'),
                '--config', str(file), '--socket', str(runtime/'service.sock')],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        private_write(pid_file, str(process.pid))
        print('Background helper started. Run this command again after a host reboot (systemd unavailable).')
    for _ in range(30):
        if (runtime/'service.sock').is_socket():
            return
        time.sleep(1)
    raise RuntimeError('Helper did not create its socket. Inspect the private service log / systemd journal.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--private-dir', type=Path, default=Path.home()/'.config/cyberguard/native-task-service')
    p.add_argument('--plan', type=Path, default=Path.home()/'.local/share/cyberguard/native-plan')
    p.add_argument('--service-env', type=Path, default=Path.home()/'.config/cyberguard/agentteams-local.env')
    p.add_argument('--run-dir', type=Path, default=Path('/run/cyberguard-onboarding'))
    p.add_argument('--console-origin', default='http://127.0.0.1:18120')
    p.add_argument('--prepare-only', action='store_true', help='Write private helper configuration only; no Docker or daemon actions')
    args = p.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        p.error('Run with sudo/root on Linux or WSL2.')
    origin = urlsplit(args.console_origin)
    if origin.scheme not in ('https', 'http') or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('', '/'):
        p.error('Use an HTTP(S) Console origin without credentials or path.')
    file, runtime = prepare(args)
    print('Private helper configuration: ' + str(file))
    if args.prepare_only:
        return
    os.environ['CYBERGUARD_ONBOARDING_RUN_DIR'] = str(runtime)
    os.environ['CYBERGUARD_CONSOLE_ORIGIN'] = args.console_origin
    os.environ['CYBERGUARD_COOKIE_SECURE'] = 'false' if origin.scheme == 'http' and origin.hostname in ('localhost', '127.0.0.1', '::1') else 'true'
    if not (ROOT/'.env').exists():
        subprocess.run([sys.executable, str(ROOT/'deploy/init_secrets.py')], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT/'deploy/agentteams-local/ensure-private-network.py')], cwd=ROOT, check=True)
    # Build this release's guard before the UI can apply a provider change.
    # Existing running containers are preserved until the administrator applies it.
    subprocess.run(['docker', 'build', '-f', 'services/model-guard/Dockerfile',
                    '-t', 'cyberguard/model-guard:native', '.'], cwd=ROOT, check=True)
    start(file, runtime, args.private_dir.resolve())
    command = ['docker', 'compose', '-f', str(ROOT/'compose.yaml')]
    override = args.private_dir.resolve()/'console.override.json'
    if override.exists():
        command += ['-f', str(override)]
    command += ['-f', str(ROOT/'compose.onboarding.yaml'), 'up', '-d', '--build']
    subprocess.run(command, cwd=ROOT, check=True)
    print('Open ' + args.console_origin + '/setup; after administrator creation continue at /settings/onboarding.')
    print('First administrator token: docker compose logs operations-console (do not share the log).')


if __name__ == '__main__':
    main()
