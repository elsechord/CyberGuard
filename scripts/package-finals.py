"""Package an exact Git revision and its portable Skill for a finals release.

Only committed files enter the source archive. Private local configuration and
runtime directories cannot accidentally enter through a recursive filesystem zip.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def package(revision, output):
    commit = git('rev-parse', '--verify', revision + '^{commit}').decode().strip()
    version = git('show', commit + ':VERSION').decode().strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('Invalid release version')
    output.mkdir(parents=True, exist_ok=True)
    source = output / f'CyberGuard-source-v{version}.zip'
    source.write_bytes(git('archive', '--format=zip', '--prefix=CyberGuard/', commit))
    skill = output / 'cyberguard-skill-v0.2.0.zip'
    prefix = 'CyberGuard/integrations/agent-skills/cyberguard/'
    with ZipFile(io.BytesIO(source.read_bytes())) as archived, ZipFile(skill, 'w', ZIP_DEFLATED) as bundled:
        names = archived.namelist()
        required = ['README.md', 'README.zh-CN.md', 'compose.yaml', 'docs/FINALS_ENTRY.md',
                    'docs/PROVEN_CAPABILITIES.md', 'services/operations-console/app/agentteams_native.py',
                    'deploy/investigation-service/collaboration/case_packet.py']
        missing = [name for name in required if 'CyberGuard/' + name not in names]
        if missing:
            raise ValueError('Committed source is missing finals files: ' + ', '.join(missing))
        if prefix + 'SKILL.md' not in names:
            raise ValueError('Portable Skill is missing from committed source')
        for name in names:
            if name.startswith(prefix) and not name.endswith('/'):
                bundled.writestr(name[len(prefix):], archived.read(name))
    files = [{'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
              'bytes': p.stat().st_size} for p in (source, skill)]
    manifest = {'version': version, 'commit': commit, 'repository': 'https://github.com/elsechord/CyberGuard',
                'files': files, 'source': 'Exact committed Git tree; runtime credentials excluded.'}
    manifest_path = output / 'release-manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    lines = [f'{entry["sha256"]}  {entry["name"]}' for entry in files]
    lines.append(hashlib.sha256(manifest_path.read_bytes()).hexdigest() + '  release-manifest.json')
    (output / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='ascii')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/finals')
    args = parser.parse_args()
    print(json.dumps(package(args.revision, args.output), indent=2))
