"""Portable CyberGuard investigation client; Python 3.10+ standard library only."""
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
VERSION = '0.2.0'


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


def console_request(path, payload=None, idempotency_key=None):
    """Read a fixed API path using the configured origin and private credential."""
    origin = origin_url(os.environ.get('CYBERGUARD_CONSOLE_URL', ''))
    key_file = os.environ.get('CYBERGUARD_SKILL_KEY_FILE')
    if not key_file:
        raise ClientError('Set CYBERGUARD_SKILL_KEY_FILE to a private file containing a scoped console key.')
    with Path(key_file).open('r', encoding='utf-8') as stream:
        key = stream.read(513).strip()
    if not re.fullmatch(r'cg_live_[A-Za-z0-9_-]{20,256}', key):
        raise ClientError('Expected a console API key; do not use a gateway or approval credential.')
    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}
    if idempotency_key is not None:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', idempotency_key):
            raise ClientError('Use a stable ASCII Idempotency-Key of 1 to 128 characters.')
        headers['Idempotency-Key'] = idempotency_key
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(body) > LIMIT:
            raise ClientError('Request exceeds 8 MiB.')
        headers['Content-Type'] = 'application/json'
    request = Request(origin + path, data=body, headers=headers)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(LIMIT + 1)
    except HTTPError as exc:
        if exc.code == 401:
            message = 'Console returned HTTP 401; the key was not accepted.'
        elif exc.code == 403:
            message = 'Console returned HTTP 403; access was denied. Check the required incidents:read or investigations:read/write permission.'
        elif exc.code >= 500:
            message = (f'Console returned HTTP {exc.code}; console/upstream service failed. '
                       'Connection check did not succeed; this does not establish invalid credentials or an empty incident list.')
        else:
            message = f'Console returned HTTP {exc.code}; check access, request and configuration. Reuse the same idempotency key for a submission retry.'
        raise ClientError(message) from None
    except (URLError, TimeoutError, OSError):
        raise ClientError('Console connection failed; check reachability and TLS configuration.') from None
    if len(raw) > LIMIT:
        raise ClientError('Console response exceeds 8 MiB; obtain a narrower export.')
    return decode(raw)


def console_get(path):
    return console_request(path)


def check(investigations=False):
    """Verify authenticated incident-list access without exporting incident data."""
    kind = 'investigations' if investigations else 'incidents'
    identity = 'id' if investigations else 'incident_id'
    payload = console_get('/api/v1/' + kind + '?limit=1')
    incidents = payload.get('data') if isinstance(payload, dict) else None
    if (not isinstance(incidents, list) or len(incidents) > 1 or 'error' in payload
            or any(not isinstance(item, dict) or not isinstance(item.get(identity), str)
                   or not item[identity] for item in incidents)):
        raise ClientError('Expected a console incident-list response; connection check did not succeed.')
    return {'connection': 'ok', 'authenticated': True, kind + '_read': True,
            kind + '_available': bool(incidents), 'actions_executed_by_client': False}


def fetch(incident):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', incident):
        raise ClientError('Incident ID must use ASCII letters, numbers, dot, underscore or hyphen.')
    payload = console_get('/api/v1/incidents/' + incident)
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


def task_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ClientError('Invalid investigation ID.')
    return value


def investigation(payload, expected=None):
    job = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(job, dict) or 'error' in payload:
        raise ClientError('Expected an investigation response.')
    identity = task_id(job.get('id'))
    if expected and identity != expected:
        raise ClientError('Investigation identity does not match the request.')
    if not isinstance(job.get('status'), str) or not job['status']:
        raise ClientError('Investigation response has no status.')
    return job


def validate_submission(payload):
    if not isinstance(payload, dict):
        raise ClientError('Expected an investigation request object.')
    for field in ('title', 'objective'):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ClientError('Submission requires a title and objective.')
    if payload.get('domain') not in {'security', 'finance', 'legal', 'general'}:
        raise ClientError('Unsupported investigation domain.')
    materials = payload.get('materials')
    if not isinstance(materials, list) or not materials:
        raise ClientError('Supply at least one authorized material.')
    sources = {'agent', 'firewall', 'edr', 'honeypot', 'server_log', 'financial_record',
               'audit_report', 'judicial_document', 'other'}
    for material in materials:
        if not isinstance(material, dict) or material.get('source_type') not in sources:
            raise ClientError('Unsupported material source_type.')
        if material.get('media_type') not in {'text/plain', 'application/json', 'text/markdown', 'text/csv'}:
            raise ClientError('Unsupported material media_type.')
        for field in ('name', 'content'):
            if not isinstance(material.get(field), str) or not material[field].strip():
                raise ClientError('Every material requires a name and textual content.')
        for field in ('source_uri', 'interpretation', 'observed_at'):
            if field in material and not isinstance(material[field], str):
                raise ClientError('Optional material metadata must be strings.')
    return payload


def submit(path, key, output):
    payload = validate_submission(read_json(path))
    # Reserve before sending: an existing receipt must never trigger a POST.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            response = console_request('/api/v1/investigations', payload, key)
            job = investigation(response)
            receipt = {'data': job, 'idempotency_key': key, 'request_sha256': digest(payload)}
            json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise
    return {'id': job['id'], 'status': job['status'], 'saved_to': str(Path(output).resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='cyberguard ' + VERSION)
    commands = parser.add_subparsers(dest='command', required=True)
    check_cmd = commands.add_parser('check', help='Check authenticated list access without exporting content.')
    check_cmd.add_argument('--investigations', action='store_true')
    demo_cmd = commands.add_parser('demo', help='Create labeled synthetic input without network access.')
    demo_cmd.add_argument('--out', required=True)
    fetch_cmd = commands.add_parser('fetch', help='GET one incident from the configured console.')
    fetch_cmd.add_argument('incident_id')
    fetch_cmd.add_argument('--out', required=True)
    inspect_cmd = commands.add_parser('inspect', help='Inspect an exported incident locally.')
    inspect_cmd.add_argument('snapshot')
    submit_cmd = commands.add_parser('submit', help='Submit user-authorized materials to backend AgentTeams.')
    submit_cmd.add_argument('request')
    submit_cmd.add_argument('--idempotency-key', required=True)
    submit_cmd.add_argument('--out', required=True)
    for command in ('status', 'result', 'cancel'):
        cmd = commands.add_parser(command, help='Read task state/result or explicitly cancel a task.')
        cmd.add_argument('id')
        if command == 'cancel':
            cmd.add_argument('--idempotency-key', required=True)
        else:
            cmd.add_argument('--out', required=command == 'result')
    args = parser.parse_args()
    try:
        if args.command == 'check':
            result = check(args.investigations)
        elif args.command == 'submit':
            result = submit(args.request, args.idempotency_key, args.out)
        elif args.command in {'status', 'result', 'cancel'}:
            identity = task_id(args.id)
            path = '/api/v1/investigations/' + identity
            if args.command == 'cancel':
                payload = console_request(path + '/cancel', {}, args.idempotency_key)
            else:
                payload = console_get(path)
            job = investigation(payload, identity)
            result = {'id': job['id'], 'status': job['status'], 'report_available': job.get('report') is not None}
            if args.command == 'result':
                if job['status'] != 'completed':
                    raise ClientError('Investigation is not completed; query status later. No report was saved.')
                if job.get('report') is None:
                    raise ClientError('Completed investigation has no report; no result was saved.')
                save(args.out, {'investigation_id': identity, 'report': job['report']})
            elif args.command == 'status' and args.out:
                save(args.out, payload)
            if getattr(args, 'out', None):
                result['saved_to'] = str(Path(args.out).resolve())
        elif args.command == 'inspect':
            result = inspect(read_json(args.snapshot))
        else:
            payload = demo() if args.command == 'demo' else fetch(args.incident_id)
            result = inspect(payload)
            save(args.out, payload)
            result['saved_to'] = str(Path(args.out).resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ClientError, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ClientError) else 'Local file operation failed; check paths, permissions and existing files.'
        print(json.dumps({'error': message}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
