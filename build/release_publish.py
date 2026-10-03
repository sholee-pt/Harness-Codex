"""Bind a Linux release to an immutable tag before publishing verified assets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess


def gh(*arguments, missing=False):
    result = subprocess.run(['gh', *map(str, arguments)], capture_output=True, text=True, timeout=300)
    if result.returncode:
        if missing and 'HTTP 404' in result.stderr:
            return None
        raise ValueError('GitHub release operation failed; existing tags and assets were preserved')
    return result.stdout


def tag_commit(call, endpoint, reference):
    target = json.loads(reference).get('object')
    seen = set()
    for _ in range(8):
        if (not isinstance(target, dict) or not isinstance(target.get('sha'), str)
                or not re.fullmatch(r'[0-9a-f]{40}', target['sha'])):
            break
        if target.get('type') == 'commit':
            return target['sha']
        if target.get('type') != 'tag' or target['sha'] in seen:
            break
        seen.add(target['sha'])
        target = json.loads(call('api', endpoint + '/git/tags/' + target['sha'])).get('object')
    raise ValueError('Release tag cannot be resolved to a bounded exact commit')


def publish(dist, commit, tag, notes, repository):
    if (repository != 'sholee-pt/Harness-Codex' or not re.fullmatch(r'[0-9a-f]{40}', commit)
            or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-beta', tag)):
        raise ValueError('Select this repository, a beta version tag and an exact source commit')
    report = json.loads((dist / 'build.json').read_text(encoding='utf-8'))
    if (report.get('version') != tag[1:] or report.get('commit') != commit
            or report.get('developmentBuild') is not False or report.get('platforms') != ['linux']):
        raise ValueError('Linux release assets must match the selected version and verified source commit')
    assets = sorted(dist.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in assets) or not notes.is_file():
        raise ValueError('Release assets and notes must be regular files')
    endpoint = f'repos/{repository}'
    existing = gh('api', endpoint + '/git/ref/tags/' + tag, missing=True)
    if existing is None:
        # Creation is exclusive. A concurrent tag creation fails without moving it.
        gh('api', '--method', 'POST', endpoint + '/git/refs', '-f', 'ref=refs/tags/' + tag, '-f', 'sha=' + commit)
        existing = gh('api', endpoint + '/git/ref/tags/' + tag)
    if tag_commit(gh, endpoint, existing) != commit:
        raise ValueError('Release tag identifies another source commit; immutable tag preserved')
    gh('release', 'create', tag, *assets, '--repo', repository, '--verify-tag',
       '--title', 'Harness for Codex ' + tag, '--notes-file', notes, '--prerelease')
    print(json.dumps({'release': tag, 'sourceCommit': commit, 'tagVerified': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--notes', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    publish(args.dist.resolve(), args.commit, args.tag, args.notes.resolve(), args.repository)
