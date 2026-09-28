"""Published GitHub releases, independent of development branch heads."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request

from . import distribution as dist

REPOSITORY = 'sholee-pt/Harness-Codex'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def request(url, *, timeout=5, accept='application/vnd.github+json'):
    if not url.startswith(('https://api.github.com/repos/sholee-pt/Harness-Codex/',
                           'https://api.github.com/repos/openai/codex/')):
        raise ValueError('Unexpected release API URL')
    headers = {'User-Agent': 'Harness-Codex-updater', 'Accept': accept}
    token = os.environ.get('HARNESS_GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url, headers=headers), timeout=timeout)


def metadata(repository, suffix, *, timeout=5):
    with request('https://api.github.com/repos/' + repository + '/' + suffix, timeout=timeout) as incoming:
        content = incoming.read(4 * 1024 * 1024 + 1)
    if len(content) > 4 * 1024 * 1024:
        raise ValueError('Release metadata exceeds its size bound')
    return json.loads(content)


def asset(release, name, repository):
    candidates = [item for item in release.get('assets', []) if item.get('name') == name]
    if len(candidates) != 1:
        raise ValueError('Published release is missing a unique asset: ' + name)
    value = candidates[0]
    prefix = 'https://api.github.com/repos/' + repository + '/releases/assets/'
    digest = value.get('digest', '')
    if (not isinstance(value.get('url'), str) or not re.fullmatch(re.escape(prefix) + r'[0-9]+', value['url'])
            or not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
        raise ValueError('Release asset has no trusted URL or SHA-256 digest')
    return value


def download(value, destination, *, limit=512 * 1024 * 1024, timeout=120):
    deadline = time.monotonic() + timeout
    try:
        incoming = request(value['url'], timeout=min(timeout, 15), accept='application/octet-stream')
    except urllib.error.HTTPError as error:
        if error.code not in {301, 302, 303, 307, 308}:
            raise
        url = error.headers.get('Location', '')
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}:
            raise ValueError('Unexpected release download redirect') from None
        # A signed download receives no API credential.
        incoming = urllib.request.urlopen(url, timeout=min(timeout, 15))
    digest, size = hashlib.sha256(), 0
    with incoming, destination.open('xb') as stream:
        while block := incoming.read(1024 * 1024):
            if time.monotonic() > deadline:
                raise TimeoutError('Release download timed out; previous installation is retained')
            size += len(block)
            if size > limit:
                raise ValueError('Release asset exceeds its size bound')
            digest.update(block)
            stream.write(block)
    if value['digest'] != 'sha256:' + digest.hexdigest() or size != value.get('size'):
        raise ValueError('Release asset size or digest mismatch')


def latest_harness(*, timeout=5):
    releases = metadata(REPOSITORY, 'releases?per_page=100', timeout=timeout)
    if not isinstance(releases, list):
        raise ValueError('Invalid GitHub release list')
    candidates = [item for item in releases if not item.get('draft') and
                  isinstance(item.get('tag_name'), str) and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(?:-beta)?', item['tag_name'])]
    if not candidates:
        raise ValueError('No published Harness release is available')
    return max(candidates, key=lambda item: dist._version(item['tag_name'][1:]))


def check(data_root, *, timeout=5):
    state = dist.installed_status(data_root)
    release = latest_harness(timeout=timeout)
    version = release['tag_name'][1:]
    available = dist._version(version) > dist._version(state['version'])
    return {'status': 'update-available' if available else 'up-to-date', 'updateAvailable': available,
            'currentVersion': state['version'], 'availableVersion': version, 'release': release,
            'majorUpgrade': dist._version(version)[0] > dist._version(state['version'])[0]}


def update(data_root, *, selected=None, timeout=120):
    """Install the selected published bytes, retaining the old immutable release."""
    root = dist._storage_path(data_root)
    before = dist.installed_status(root)
    selected = selected or check(root, timeout=min(timeout, 10))
    if not selected['updateAvailable']:
        return {**selected, 'updated': False, 'installation': before}
    version = selected['availableVersion']
    if dist._version(version) <= dist._version(before['version']):
        raise ValueError('Harness update would not be a forward version change')
    release = selected['release']
    if release.get('draft') or release.get('tag_name') != 'v' + version:
        raise ValueError('Selected Harness release identity changed')
    value = asset(release, f'harness-codex-{version}-linux.tar.gz', REPOSITORY)
    with tempfile.TemporaryDirectory(prefix='harness-release-') as temporary:
        temporary = Path(temporary)
        archive = temporary / 'source.tar.gz'
        download(value, archive, limit=dist.MAX_TREE_BYTES, timeout=timeout)
        # Reject unsafe members within the isolated temporary extraction tree.
        from .native_package import extract
        extract(archive, temporary / 'unpacked', max_files=dist.MAX_FILES, max_tree=dist.MAX_TREE_BYTES)
        source = temporary / 'unpacked' / ('harness-codex-' + version)
        snapshot = dist._snapshot(source)
        declared_version, commit = dist._source_info(snapshot)
        if declared_version != version or not commit:
            raise ValueError('Published source lacks matching version and commit provenance')
        with dist._lock(root):
            current = dist.installed_status(root)
            if current != before:
                raise ValueError('Harness installation changed during download; retry')
            active = {key: item for key, item in before.items() if key not in {'dataRoot', 'sourceRoot', 'releasePath', 'release_root'}}
            active.update(version=version, commit=commit)
            installation = dist._activate(snapshot, root, active)
    return {**selected, 'status': 'updated', 'updated': True, 'installation': installation}
