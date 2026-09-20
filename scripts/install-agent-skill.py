"""Install the portable CyberGuard Skill into an explicitly selected project."""
import argparse
import json
import shutil
from pathlib import Path


def install(project: Path, agent: str) -> Path:
    source = Path(__file__).resolve().parents[1] / 'integrations/agent-skills/cyberguard'
    project = project.resolve(strict=True)
    if not project.is_dir():
        raise ValueError('Project must be an existing directory.')
    folder = '.claude' if agent == 'claude' else '.agents'
    target = project / folder / 'skills' / 'cyberguard'
    # Existing installs need an explicit reviewed update; never merge stale helpers.
    if target.exists() or target.is_symlink():
        raise ValueError('CyberGuard is already installed here; review the existing version before updating.')
    if not target.resolve().is_relative_to(project):
        raise ValueError('Skill destination resolves outside the selected project.')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', choices=['codex', 'claude', 'generic'], required=True)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps({'installed': str(install(args.project, args.agent)),
                          'scope': 'project', 'version': '0.2.0'}))
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')
