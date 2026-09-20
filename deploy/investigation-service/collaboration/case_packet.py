"""Fetch unchanged CyberGuard case bytes from Matrix; check a report before submit.

Uses the Worker's existing Matrix credential. No model calls or task mutations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def check_case(case):
    for material in case['materials']:
        if hashlib.sha256(material['content'].encode('utf-8')).hexdigest() != material['sha256']:
            raise ValueError('Material bytes do not match sha256: ' + material['material_id'])


def check_report(case, report):
    check_case(case)
    if report.get('job_id') != case['id'] or report.get('role') != 'verifier':
        raise ValueError('report must have the exact case job_id and role=verifier')
    if not isinstance(report.get('summary'), str) or not report['summary'].strip():
        raise ValueError('summary must be a nonempty string')
    for key in ('unknowns', 'next_steps'):
        if not isinstance(report.get(key), list) or any(not isinstance(x, str) for x in report[key]):
            raise ValueError(key + ' must be a string array')
    if not isinstance(report.get('findings'), list) or not report['findings']:
        raise ValueError('findings must be a nonempty array')
    materials = {m['material_id']: m['content'] for m in case['materials']}
    for finding in report['findings']:
        if not isinstance(finding.get('claim'), str) or not finding['claim'].strip():
            raise ValueError('Every finding needs a claim')
        status = finding.get('status')
        if status not in ('supported', 'refuted', 'inconclusive'):
            raise ValueError('Invalid finding status')
        limitations = finding.get('limitations')
        if not isinstance(limitations, str) or (status == 'inconclusive' and not limitations.strip()):
            raise ValueError('Inconclusive finding requires limitations')
        citations = finding.get('citations')
        if not isinstance(citations, list) or (status != 'inconclusive' and not citations):
            raise ValueError('Supported/refuted findings require citations')
        for citation in citations:
            text = citation.get('quote')
            if not isinstance(text, str) or not text or text not in materials.get(citation.get('material_id'), ''):
                raise ValueError('Citation is not an exact substring of original material')
    return {'valid': True, 'job_id': case['id'], 'findings': len(report['findings'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    fetch = sub.add_parser('fetch')
    fetch.add_argument('--uri', required=True)
    fetch.add_argument('--job', required=True)
    fetch.add_argument('--directory', required=True)
    validate = sub.add_parser('check')
    validate.add_argument('--case', required=True)
    validate.add_argument('--report', required=True)
    args = parser.parse_args()
    if args.action == 'check':
        print(json.dumps(check_report(json.loads(Path(args.case).read_text(encoding='utf8')),
                                      json.loads(Path(args.report).read_text(encoding='utf8')))))
        return
    uri = urlsplit(args.uri)
    if uri.scheme != 'mxc' or not uri.netloc or not uri.path.strip('/') or uri.query or uri.fragment:
        raise ValueError('Expected an mxc media URI')
    origin = os.environ['AGENTTEAMS_MATRIX_URL'].rstrip('/')
    request = Request(origin + '/_matrix/client/v1/media/download/' + quote(uri.netloc, safe='')
                      + '/' + quote(uri.path.lstrip('/'), safe=''),
                      headers={'Authorization': 'Bearer ' + os.environ['AGENTTEAMS_WORKER_MATRIX_TOKEN']})
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=30) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Case packet exceeds 1 MiB')
    case = json.loads(raw)
    if case['id'] != args.job:
        raise ValueError('Case job_id mismatch')
    check_case(case)
    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / 'case.json'
    destination.write_bytes(raw)
    print(json.dumps({'case': str(destination), 'job_id': case['id'],
                      'materials': len(case['materials']), 'sha256': hashlib.sha256(raw).hexdigest()}))


if __name__ == '__main__':
    main()
