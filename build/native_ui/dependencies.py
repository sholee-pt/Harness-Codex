"""Use the pinned upstream's checked V8 artifacts, without changing dependencies."""
import argparse
import hashlib
import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

DOWNLOAD_ATTEMPTS = 5
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


def _download_once(url, path):
    # Exclusive creation protects existing files; clean up only this attempt.
    output = path.open('xb')
    try:
        with output, urllib.request.urlopen(url, timeout=60) as incoming:
            size = 0
            while block := incoming.read(1024 * 1024):
                size += len(block)
                if size > MAX_DOWNLOAD_BYTES:
                    raise ValueError('Native dependency exceeds the download bound')
                output.write(block)
            length = incoming.headers.get('Content-Length')
            if length is not None and size != int(length):
                raise http.client.IncompleteRead(b'', int(length) - size)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def download(url, path):
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            _download_once(url, path)
            return
        except urllib.error.HTTPError as exc:
            transient = exc.code in TRANSIENT_HTTP_STATUS
            reason = f'HTTP {exc.code}'
            exc.close()
            if not transient or attempt == DOWNLOAD_ATTEMPTS:
                raise
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, (TimeoutError, ConnectionError, socket.gaierror)) or attempt == DOWNLOAD_ATTEMPTS:
                raise
            reason = type(exc.reason).__name__
        except (TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            reason = type(exc).__name__
        delay = 2 ** (attempt - 1)
        print(f'V8 download {path.name}: {reason}; retry {attempt + 1}/{DOWNLOAD_ATTEMPTS} in {delay}s.', flush=True)
        time.sleep(delay)


def setup(root, target, output):
    output.mkdir(parents=True, exist_ok=False)
    version = subprocess.check_output([sys.executable, '-B', str(root / '.github/scripts/rusty_v8_bazel.py'),
        'resolved-v8-crate-version'], text=True, cwd=root).strip()
    if not version or any(c not in '0123456789.' for c in version):
        raise ValueError('Invalid upstream V8 version')
    base = f'https://github.com/openai/codex/releases/download/rusty-v8-v{version}/'
    stem = f'ptrcomp_sandbox_release_{target}'
    archive = ('rusty_v8_' + stem + '.lib.gz') if target.endswith('windows-msvc') else ('librusty_v8_' + stem + '.a.gz')
    binding = 'src_binding_' + stem + '.rs'
    sums = 'rusty_v8_' + stem + '.sha256'
    trusted = root / f'third_party/v8/rusty_v8_{version.replace(".", "_")}_release_manifests.sha256'
    trusted_hashes = dict(line.split()[::-1] for line in trusted.read_text().splitlines() if line.strip())
    download(base + sums, output / sums)
    if hashlib.sha256((output / sums).read_bytes()).hexdigest() != trusted_hashes.get(sums):
        raise ValueError('Upstream native dependency manifest checksum mismatch')
    expected = dict(line.split()[::-1] for line in (output / sums).read_text().splitlines() if line.strip())
    if set(expected) != {archive, binding}:
        raise ValueError('Unexpected upstream V8 assets')
    for name in (archive, binding):
        download(base + name, output / name)
        with (output / name).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != expected[name]:
            raise ValueError('Native dependency checksum mismatch')
    with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as environment:
        environment.write(f'RUSTY_V8_ARCHIVE={output / archive}\nRUSTY_V8_SRC_BINDING_PATH={output / binding}\n')
    print('Verified the pinned upstream V8 archive and bindings.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--target', choices=['x86_64-unknown-linux-musl', 'x86_64-pc-windows-msvc'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    setup(args.root.resolve(), args.target, args.output.resolve())
