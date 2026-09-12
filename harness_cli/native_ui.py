"""Launch the pinned original Codex screen with the Harness Auto extension."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from . import distribution as dist, native_package as package
from .environment import codex_environment
from .presentation import Progress

API = 'https://api.github.com/repos/sholee-pt/Harness-Codex'


def platform_key():
    if platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise ValueError('The extended native UI currently supports Linux/Windows x86_64. Use --ui native on this architecture.')
    if sys.platform not in {'win32', 'linux'}:
        raise ValueError('Use --ui native on this platform.')
    return ('windows-' if sys.platform == 'win32' else 'linux-') + 'x86_64'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _download(url, destination, limit, *, token=None):
    deadline = time.monotonic() + 300
    headers = {'User-Agent': 'Harness-Codex-native-ui'}
    if token:
        if not url.startswith(API + '/releases/'):
            raise ValueError('Credentials are restricted to this GitHub release API')
        headers.update(Authorization='Bearer ' + token, Accept='application/octet-stream')
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(NoRedirect()) if token else urllib.request.build_opener()
    try:
        incoming = opener.open(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if token and exc.code in {301, 302, 303, 307, 308}:
            location = exc.headers.get('Location', '')
            if not location.startswith('https://'):
                raise ValueError('Unsupported release asset redirect') from None
            # Signed asset URLs never receive the GitHub credential.
            incoming = urllib.request.urlopen(location, timeout=60)
        else:
            raise
    with incoming, destination.open('xb') as stream:
        size = 0
        while block := incoming.read(1024 * 1024):
            if time.monotonic() > deadline:
                raise TimeoutError('Native UI download exceeded five minutes; existing files are retained')
            size += len(block)
            if size > limit:
                raise ValueError('Native UI download exceeds its size bound')
            stream.write(block)


def _private_assets(version):
    # Git identity is not authentication. Use an existing HTTPS credential helper.
    response = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
        text=True, capture_output=True, timeout=15, cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'Never'}, check=False)
    values = dict(line.split('=', 1) for line in response.stdout.splitlines() if '=' in line)
    token = values.get('password')
    if response.returncode or not token:
        raise ValueError('Native UI download needs GitHub release access; configure an HTTPS credential or use --native-ui-archive PATH.')
    request = urllib.request.Request(API + '/releases/tags/v' + version,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'User-Agent': 'Harness-Codex-native-ui'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as incoming:
        payload = incoming.read(256 * 1024 + 1)
    if len(payload) > 256 * 1024:
        raise ValueError('GitHub release metadata exceeds its size bound')
    value = json.loads(payload)
    return token, {asset['name']: asset['url'] for asset in value.get('assets', [])}


def fetch(version, name, temporary):
    base = 'https://github.com/sholee-pt/Harness-Codex/releases/download/v' + version + '/'
    sums, archive = temporary / 'SHA256SUMS', temporary / name
    token, assets = None, {}
    try:
        _download(base + 'SHA256SUMS', sums, 128 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code not in {401, 404}:
            raise
        token, assets = _private_assets(version)
        _download(assets['SHA256SUMS'], sums, 128 * 1024, token=token)
    expected = {}
    for line in sums.read_text(encoding='utf-8').splitlines():
        digest, filename = line.split('  ', 1)
        if filename in expected:
            raise ValueError('Duplicate release checksum')
        expected[filename] = digest
    if name not in expected:
        raise ValueError('This release has no verified native UI for the selected platform')
    _download(assets[name] if token else base + name, archive, package.MAX_FILE, token=token)
    if package.fingerprint(archive)['sha256'] != expected[name]:
        raise ValueError('Native UI release checksum mismatch')
    return archive


def ensure(data_root, version, *, archive=None):
    data_root = dist._storage_path(data_root)
    dist.installed_status(data_root)
    platform_name = platform_key()
    destination = dist._storage_path(data_root / 'native-ui' / ('v' + version) / platform_name)
    with dist._lock(data_root):
        if destination.exists():
            package.verify(destination, version, platform_name)
        else:
            with Progress('Preparing the original Codex UI with Harness Auto'), tempfile.TemporaryDirectory(prefix='harness-native-ui-') as temporary:
                temporary = Path(temporary)
                if archive is None:
                    archive = fetch(version, f'harness-codex-ui-{version}-{platform_name}.tar.gz', temporary)
                package.extract(archive, temporary / 'unpacked')
                package.verify(temporary / 'unpacked', version, platform_name)
                # Stage on the destination volume, so the final rename is atomic.
                import shutil
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=destination.parent))
                try:
                    shutil.copytree(temporary / 'unpacked', staging, dirs_exist_ok=True)
                    package.verify(staging, version, platform_name)
                    os.replace(staging, destination)
                finally:
                    # Only our newly created staging directory, never a computed user tree.
                    if staging.exists():
                        shutil.rmtree(staging)
        return destination / ('bin/codex.exe' if platform_name.startswith('windows-') else 'bin/codex')


def removal_files(data_root):
    root = dist._storage_path(data_root / 'native-ui')
    files = {}
    if not root.exists():
        return files
    for release in root.iterdir():
        version = release.name.removeprefix('v')
        dist._version(version)
        for platform_path in dist._storage_path(release).iterdir():
            metadata = package.verify(platform_path, version, platform_path.name)
            files.update({platform_path / name: value for name, value in metadata['files'].items()})
            files[platform_path / 'harness-ui.json'] = package.fingerprint(platform_path / 'harness-ui.json')
    return files


def run(args, root, source_root, prompt):
    from .main import default_data_root, version
    from .project import _launch
    binary = ensure(default_data_root(), version(source_root), archive=args.native_ui_archive)
    mode = args.settings
    if mode == 'ask':
        from .terminal_menu import choose
        with Progress('Choose conversation inference', compact=True) as progress:
            selection = choose(progress, 'Conversation inference', ['Auto — select model and reasoning for new requests',
                               'Manual — use the original /model menu'])
        mode = 'auto' if selection == 0 else 'native'
    env = codex_environment()
    for key in list(env):
        if key.startswith('HARNESS_ROUTER_'):
            del env[key]
    env.update(HARNESS_ROUTER_PYTHON=str(Path(sys.executable).resolve()),
               HARNESS_ROUTER_SCRIPT=str(Path(__file__).with_name('native_router.py').resolve()),
               HARNESS_ROUTER_MODE='auto' if mode == 'auto' else 'manual',
               HARNESS_ROUTER_RESUME='1' if args.command == 'resume' else '0')
    if args.routing_profiles:
        env['HARNESS_ROUTER_PROFILES'] = str(args.routing_profiles.resolve())
    return _launch([str(binary)], root, prompt, resume=args.command == 'resume',
                   session_id=getattr(args, 'session_id', None), last=getattr(args, 'last', False),
                   settings='native', environment=env)
