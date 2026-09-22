"""Bounded TypeSafe transport, isolated from native Codex and its credentials."""
import json
import os
import sys
import urllib.request

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MAX_BYTES = 64 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Jev redirects are not supported')


def fetch(payload):
    key = os.environ.get('TYPESAFE_API_KEY', '').strip()
    if not key:
        raise ValueError('Missing Jev key')
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), method='POST',
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=3) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Oversized Jev response')
    return json.loads(data)


def main():
    try:
        payload = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            return 1
        print(json.dumps(fetch(json.loads(payload))))
        return 0
    except (OSError, ValueError):
        # Provider errors can echo inputs; never relay them into Codex or logs.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
