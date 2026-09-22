"""Bounded TypeSafe transport, isolated from native Codex and its credentials."""
import json
import sys
import urllib.error
import urllib.request

from .jev_auth import resolve

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MAX_BYTES = 64 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Jev redirects are not supported')


def fetch(payload, *, key=None):
    key = resolve() if key is None else key
    if not key:
        raise ValueError('Missing Jev key')
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), method='POST',
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=3) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Oversized Jev response')
    return json.loads(data)


def check_key(value):
    from .jev_auth import _key
    key = _key(value['key'])
    payload = {'model': value['model'], 'state': 'Harness credential check.',
               'questions': {'ready': {'type': 'noul', 'instructions': 'Is this a credential check?'}}}
    try:
        fetch(payload, key=key)
        return 'valid'
    except urllib.error.HTTPError as exc:
        return 'invalid' if exc.code == 401 else 'unverified'
    except (OSError, ValueError):
        return 'unverified'


def main():
    try:
        payload = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            return 1
        if sys.argv[1:] == ['--check-key']:
            print(check_key(json.loads(payload)))
        else:
            print(json.dumps(fetch(json.loads(payload))))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        # Provider errors can echo inputs; never relay them into Codex or logs.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
