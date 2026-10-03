"""Bind a Linux release to an immutable tag before publishing verified assets."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.artifacts import render_bootstraps
from build.source import checked_path, collect_source
from harness_cli import distribution


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


def verified_assets(dist, commit, tag, notes):
    version = tag[1:]
    archive_name = f'harness-codex-{version}-linux.tar.gz'
    limits = {archive_name: distribution.MAX_TREE_BYTES * 2, 'install_harness_codex.sh': 1024 * 1024,
              'SHA256SUMS': 4096, 'build.json': 16384}
    dist = checked_path(dist)
    if not dist.is_dir() or {path.name for path in dist.iterdir()} != set(limits):
        raise ValueError('Linux release requires exactly its archive, bootstrap, SHA256SUMS and build.json')
    assets = {}
    for name, limit in limits.items():
        path = checked_path(dist / name)
        if not path.is_file() or path.stat().st_size > limit:
            raise ValueError('Release assets must be bounded regular files')
        with path.open('rb') as stream:
            assets[name] = stream.read(limit + 1)
        if len(assets[name]) > limit:
            raise ValueError('Release assets exceed size limits')
    notes = checked_path(notes)
    if not notes.is_file() or notes.stat().st_size > 1024 * 1024:
        raise ValueError('Release notes must be a bounded regular file')
    with notes.open('rb') as stream:
        note_bytes = stream.read(1024 * 1024 + 1)
    if len(note_bytes) > 1024 * 1024:
        raise ValueError('Release notes exceed size limits')
    report = json.loads(assets['build.json'])
    if (not isinstance(report, dict) or report.get('runtime') != 'codex'
            or report.get('version') != version or report.get('commit') != commit
            or report.get('developmentBuild') is not False or report.get('platforms') != ['linux']):
        raise ValueError('Linux release assets must match the selected version and verified source commit')
    checksums = {}
    for line in assets['SHA256SUMS'].decode('ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([^/\\]+)', line)
        if match is None or match[2] in checksums:
            raise ValueError('Release checksum manifest is invalid or ambiguous')
        checksums[match[2]] = match[1]
    expected = {name: hashlib.sha256(assets[name]).hexdigest() for name in (archive_name, 'install_harness_codex.sh')}
    if (checksums != expected or report.get('sha256') != expected[archive_name]
            or report.get('bootstrapSha256') != expected['install_harness_codex.sh']):
        raise ValueError('Release checksums disagree with asset bytes or build report')
    files = {}
    total = 0
    prefix = f'harness-codex-{version}/'
    with tarfile.open(fileobj=io.BytesIO(assets[archive_name]), mode='r:gz') as archive:
        for member in archive:
            if not member.name.startswith(prefix) or member.type != tarfile.REGTYPE:
                raise ValueError('Release archive contains an unsupported root or file type')
            name = distribution._relative(member.name[len(prefix):])
            expected_mode = 0o755 if name in {'install.sh', 'harness.py'} else 0o644
            if (member.mode != expected_mode or member.uid != 0 or member.gid != 0 or member.mtime != 0
                    or member.uname or member.gname or member.linkname or set(member.pax_headers) - {'path'}):
                raise ValueError('Release archive ownership, permissions or metadata disagree with the builder')
            total += member.size
            if (name in files or len(files) >= distribution.MAX_FILES or member.size < 0
                    or member.size > distribution.MAX_FILE_BYTES or total > distribution.MAX_TREE_BYTES):
                raise ValueError('Release archive paths or sizes exceed limits')
            files[name] = archive.extractfile(member).read(member.size + 1)
            if len(files[name]) != member.size:
                raise ValueError('Release archive contains incomplete bytes')
    if type(report.get('files')) is not int or report['files'] != len(files):
        raise ValueError('Release archive file count disagrees with build report')
    # Reconstruct from this clean checkout's immutable commit. Self-consistent
    # checksums and caller-supplied provenance alone do not establish identity.
    source_version, source_commit, source_files, bootstraps = collect_source(Path(__file__).resolve().parents[1])
    if (source_version != version or source_commit != commit or source_files != files
            or render_bootstraps(bootstraps, version)['install_harness_codex.sh'] != assets['install_harness_codex.sh']):
        raise ValueError('Release payload does not match the selected immutable source checkout')
    return assets, note_bytes


def publish(dist, commit, tag, notes, repository):
    if (repository != 'sholee-pt/Harness-Codex' or not re.fullmatch(r'[0-9a-f]{40}', commit)
            or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+-beta', tag)):
        raise ValueError('Select this repository, a beta version tag and an exact source commit')
    assets, note_bytes = verified_assets(dist, commit, tag, notes)
    # Upload the exact validated snapshot, even if original build files change
    # while GitHub requests are in flight. Temporary files are private and owned.
    with tempfile.TemporaryDirectory(prefix='harness-publish-') as temporary:
        staged = Path(temporary)
        for name, data in {**assets, 'release-notes.md': note_bytes}.items():
            path = staged / name
            with path.open('xb') as stream:
                stream.write(data)
            path.chmod(0o600)
        publish_verified([staged / name for name in sorted(assets)], commit, tag, staged / 'release-notes.md', repository)


def publish_verified(assets, commit, tag, notes, repository):
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
    publish(args.dist, args.commit, args.tag, args.notes, args.repository)
