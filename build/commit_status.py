"""Attach the actual workflow outcome to its exact commit; no polling."""
from __future__ import annotations

import argparse
import json
import os
import urllib.request


def outcome(results, publish):
    required = ('verify', 'native-release', 'release') if publish else ('verify',)
    values = [results.get(name, {}).get('result') for name in required]
    if all(value == 'success' for value in values):
        return 'success'
    return 'failure' if 'failure' in values else 'error'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('begin', 'finish'))
    parser.add_argument('--publish', choices=('true', 'false'), default='false')
    args = parser.parse_args()
    publish = args.publish == 'true'
    state = 'pending' if args.phase == 'begin' else outcome(json.loads(os.environ['HARNESS_JOB_RESULTS']), publish)
    repository, sha = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
    payload = {'state': state, 'context': 'Harness / release' if publish else 'Harness / verification',
               'description': 'Linux release verification: ' + state if publish else 'Project checks: ' + state,
               'target_url': f'https://github.com/{repository}/actions/runs/' + os.environ['GITHUB_RUN_ID']}
    request = urllib.request.Request(f'https://api.github.com/repos/{repository}/statuses/{sha}',
        data=json.dumps(payload).encode(), method='POST', headers={
            'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json', 'User-Agent': 'Harness-Codex-CI'})
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()
    print(payload['context'] + ': ' + state)
    return 1 if state in {'failure', 'error'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
