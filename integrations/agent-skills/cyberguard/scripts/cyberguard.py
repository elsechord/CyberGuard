"""Portable read-only CyberGuard client; Python 3.10+ standard library only."""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

LIMIT = 8 * 1024 * 1024


class ClientError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('Redirect refused; verify the configured console origin.')


def decode(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ClientError('Duplicate JSON keys are not accepted.')
            result[key] = value
        return result
    def nonfinite(value):
        raise ClientError('Non-finite JSON number is not accepted.')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ClientError('Expected a UTF-8 JSON incident snapshot.') from exc


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ClientError('Snapshot exceeds 8 MiB; export a narrower incident/run.')
    return decode(raw)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def inspect(payload, expected_incident=None):
    detail = payload.get('data', payload) if isinstance(payload, dict) else None
    if not isinstance(detail, dict) or not isinstance(detail.get('summary'), dict):
        raise ClientError('Expected a console incident response or gateway incident export.')
    incident = detail['summary'].get('incident_id')
    if not isinstance(incident, str) or not incident or (expected_incident and incident != expected_incident):
        raise ClientError('Incident identity is absent or does not match the request.')
    evidence = detail.get('evidence')
    if not isinstance(evidence, list):
        raise ClientError('Incident response has no evidence array.')
    seen, records = set(), []
    for item in evidence:
        if not isinstance(item, dict):
            raise ClientError('Evidence entries must be objects.')
        eid = item.get('evidence_id')
        if not isinstance(eid, str) or not eid or eid in seen or item.get('incident_id') != incident:
            raise ClientError('Evidence identity is absent, duplicated or belongs to another incident.')
        seen.add(eid)
        declared = item.get('envelope_sha256')
        state = 'not_available'
        if declared:
            actual = digest({k: v for k, v in item.items() if k != 'envelope_sha256'})
            if declared != actual:
                raise ClientError('Evidence envelope mismatch; do not use this snapshot as verified input.')
            state = 'matches'
        records.append({'evidence_id': eid, 'source': item.get('source'),
                        'run_id': item.get('run_id'), 'environment': item.get('environment'),
                        'execution': item.get('execution'), 'envelope_digest': state})
    return {'incident_id': incident, 'evidence_count': len(records), 'records': records,
            'source_authenticity': 'not_attested_by_local_hash',
            'analysis_runtime': 'calling_agent', 'actions_executed_by_client': False}


def origin_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ClientError('Invalid console origin.') from exc
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or any(c.isspace() for c in value)):
        raise ClientError('Set CYBERGUARD_CONSOLE_URL to an origin without path, query or credentials.')
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.lower() == 'localhost'
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback):
        raise ClientError('HTTPS is required except for an explicitly configured loopback console.')
    return value.rstrip('/')


def fetch(incident):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', incident):
        raise ClientError('Incident ID must use ASCII letters, numbers, dot, underscore or hyphen.')
    origin = origin_url(os.environ.get('CYBERGUARD_CONSOLE_URL', ''))
    key_file = os.environ.get('CYBERGUARD_SKILL_KEY_FILE')
    if not key_file:
        raise ClientError('Set CYBERGUARD_SKILL_KEY_FILE to a private file containing an incidents:read key.')
    with Path(key_file).open('r', encoding='utf-8') as stream:
        key = stream.read(513).strip()
    if not re.fullmatch(r'cg_live_[A-Za-z0-9_-]{20,256}', key):
        raise ClientError('Expected a console API key; do not use a gateway or approval credential.')
    request = Request(origin + '/api/v1/incidents/' + incident,
                      headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(LIMIT + 1)
    except HTTPError as exc:
        raise ClientError(f'Console returned HTTP {exc.code}; check incident access and configuration.') from None
    except (URLError, TimeoutError, OSError):
        raise ClientError('Console connection failed; check reachability and TLS configuration.') from None
    if len(raw) > LIMIT:
        raise ClientError('Console response exceeds 8 MiB; obtain a narrower export.')
    payload = decode(raw)
    inspect(payload, incident)
    return payload


def demo():
    """Synthetic input only. Interpretation is deliberately left to the caller."""
    incident = 'CG-SKILL-EXERCISE'
    entries = [
        {'evidence_id': 'EV-CPU', 'source': 'exercise/process-snapshot',
         'kind': 'cpu_observation', 'summary': 'Process used 87% CPU during one observation.',
         'data': {'executable': '/opt/research/simulation', 'cpu_percent': 87}},
        {'evidence_id': 'EV-INVENTORY', 'source': 'exercise/workload-inventory',
         'kind': 'authorization_inventory', 'summary': 'Supplied inventory lists a scheduled simulation job.',
         'data': {'executable': '/opt/research/simulation', 'owner': 'research-team',
                  'binary_hash_verified': False}},
    ]
    for entry in entries:
        entry.update(incident_id=incident, run_id='exercise-001', environment='fixture',
                     execution='simulated', observed_at='2026-09-19T00:00:00Z')
        entry['envelope_sha256'] = digest(entry)
    return {'summary': {'incident_id': incident, 'status': 'investigating'},
            'evidence': entries, 'actions': [], 'workflow': None, 'runs': ['exercise-001'],
            'provenance': {'kind': 'synthetic_exercise', 'real_incident': False}}


def save(path, value):
    # Exclusive creation preserves existing evidence. On Windows, parent ACLs apply.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    demo_cmd = commands.add_parser('demo', help='Create labeled synthetic input without network access.')
    demo_cmd.add_argument('--out', required=True)
    fetch_cmd = commands.add_parser('fetch', help='GET one incident from the configured operations console.')
    fetch_cmd.add_argument('incident_id')
    fetch_cmd.add_argument('--out', required=True)
    inspect_cmd = commands.add_parser('inspect', help='Inspect a previously exported incident locally.')
    inspect_cmd.add_argument('snapshot')
    args = parser.parse_args()
    try:
        if args.command == 'inspect':
            result = inspect(read_json(args.snapshot))
        else:
            payload = demo() if args.command == 'demo' else fetch(args.incident_id)
            result = inspect(payload)
            save(args.out, payload)
            result['saved_to'] = str(Path(args.out).resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ClientError, OSError, ValueError) as exc:
        # Do not echo response bodies, credentials, or credential file paths.
        message = str(exc) if isinstance(exc, ClientError) else 'Local file operation failed; check paths, permissions and existing files.'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
