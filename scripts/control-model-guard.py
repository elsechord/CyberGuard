"""Local operator controls; credentials stay in a private POSIX configuration file."""
import argparse
import json
import os
from pathlib import Path
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'arm', 'close'))
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/cyberguard/model-guard-config.json')
    parser.add_argument('--origin', default='http://127.0.0.1:18110')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        origin = urlsplit(args.origin)
        if (origin.scheme != 'http' or origin.hostname != '127.0.0.1' or not origin.port
                or origin.username or origin.password or origin.path not in ('', '/') or origin.query or origin.fragment):
            raise ValueError('Explicit loopback origin required')
        if os.name != 'posix' or stat.S_IMODE(args.config.stat().st_mode) & 0o077:
            raise ValueError('Private POSIX configuration required')
        if args.output and args.output.exists():
            raise ValueError('Output already exists')
        config = json.loads(args.config.read_text())
        request = Request(args.origin.rstrip('/') + '/admin/' + args.action,
            data=None if args.action == 'status' else b'{}',
            headers={'Authorization': 'Bearer ' + config['admin_token'], 'Content-Type': 'application/json'})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=10) as response:
            result = json.load(response)
        if result['run']['run_id'] != config['run_id']:
            raise ValueError('Run identity mismatch')
        # Never print arbitrary response fields; these controls require only ledger metadata.
        safe = {key: result[key] for key in ('run', 'armed', 'denials', 'token_reservation_method', 'limitations') if key in result}
        text = json.dumps(safe, indent=2) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(text)
        print(text)
        return 0
    except HTTPError as exc:
        print(json.dumps({'status': 'rejected', 'http_status': exc.code, 'details': 'Inspect the local guard ledger'}))
    except (OSError, ValueError, KeyError, URLError):
        print(json.dumps({'status': 'failed', 'details': 'Invalid private configuration or unavailable local guard'}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
