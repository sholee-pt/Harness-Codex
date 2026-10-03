"""Supplement an exact-commit Linux release after explicit Windows verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness_cli import native_package
from harness_cli.versions import VERSION_RE
from build.release_publish import tag_commit


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checksums(path):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] in values:
            raise ValueError('Invalid or duplicate release checksum entry')
        values[match[2]] = match[1]
    return values


def prepare(dist, published, commit):
    """No network or release writes until every platform/source binding passes."""
    incoming = json.loads((dist / 'build.json').read_text(encoding='utf-8'))
    original = json.loads((published / 'build.json').read_text(encoding='utf-8'))
    version = incoming.get('version')
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid release version or source commit')
    for report in (incoming, original):
        if report.get('version') != version or report.get('commit') != commit or report.get('developmentBuild') is not False:
            raise ValueError('Windows and Linux must have the same verified source commit and version')
    if incoming.get('platforms') != ['linux', 'windows'] or original.get('platforms') not in (['linux'], ['linux', 'windows']):
        raise ValueError('Expected an existing Linux release and a verified Windows supplement')
    old_sums, new_sums = checksums(published / 'SHA256SUMS'), checksums(dist / 'SHA256SUMS')
    linux = f'harness-codex-{version}-linux.tar.gz'
    for name, field in ((linux, 'sha256'), ('install_harness_codex.sh', 'bootstrapSha256')):
        actual = digest(dist / name)
        if actual != original.get(field) or actual != incoming.get(field) or actual != old_sums.get(name) or actual != new_sums.get(name):
            raise ValueError('Rebuilt Linux payload differs from the published release')
    linux_native = f'harness-codex-ui-{version}-linux-x86_64.tar.gz'
    linux_record = original.get('nativeUi', {}).get(linux_native, {})
    if (linux_native in old_sums or linux_record) and (not linux_record.get('sha256') or linux_record['sha256'] != old_sums.get(linux_native)):
        raise ValueError('The Linux native release is not complete')
    windows = f'harness-codex-{version}-windows.zip'
    bootstrap = 'install_harness_codex.ps1'
    native = f'harness-codex-ui-{version}-windows-x86_64.tar.gz'
    additions = {}
    for name, field in ((windows, 'windowsSha256'), (bootstrap, 'windowsBootstrapSha256')):
        actual = digest(dist / name)
        if actual != incoming.get(field) or actual != new_sums.get(name):
            raise ValueError('Windows asset checksum mismatch')
        additions[name] = actual
    # Same-source provenance includes actual ZIP contents, not just its label.
    with tarfile.open(dist / linux, 'r:gz') as archive:
        expected = {item.name: archive.extractfile(item).read() for item in archive if item.isfile()}
    with zipfile.ZipFile(dist / windows) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected) or any(archive.read(name) != expected[name] for name in names):
            raise ValueError('Windows archive payload differs from the verified Linux source')
    with tempfile.TemporaryDirectory(prefix='harness-windows-package-') as temporary:
        root = Path(temporary) / 'native'
        native_package.extract(dist / native, root)
        metadata = native_package.verify(root, version, 'windows-x86_64')
        if metadata.get('harnessSourceCommit') != commit:
            raise ValueError('Windows native executable was built from another source commit')
    native_record = native_package.fingerprint(dist / native)
    additions[native] = native_record['sha256']
    for name, value in additions.items():
        if name in old_sums and old_sums[name] != value:
            raise ValueError('An existing Windows asset has different bytes; replacement refused')
    merged = {**original, 'platforms': ['linux', 'windows'], 'windowsArtifact': windows,
              'windowsSha256': additions[windows], 'windowsBootstrapSha256': additions[bootstrap],
              'nativeUi': {**original.get('nativeUi', {}), native: native_record}}
    sums = {**old_sums, **additions}
    return merged, sums, additions


def notes(body, version):
    marker = '<!-- harness:windows-supplement -->'
    if marker in body:
        return body
    body = body.replace('Windows releases remain paused.', 'Windows assets are available for this explicitly requested release only.')
    return body.rstrip() + f'''

{marker}
### Windows installation (one-off verified supplement)

```powershell
Invoke-WebRequest 'https://github.com/sholee-pt/Harness-Codex/releases/download/v{version}/install_harness_codex.ps1' -OutFile ./install_harness_codex.ps1
& ./install_harness_codex.ps1
harness-codex --version
```

Run under your normal PowerShell script policy. The installer prepares the isolated
environment and user PATH. The ZIP contains the generator and CLI; the
`harness-codex-ui-{version}-windows-x86_64.tar.gz` package contains the original
Codex UI with Auto and its Windows helpers. SHA256SUMS and build.json cover both
platforms from the same source commit. Windows installer, upgrade and native
TUI/extension checks passed before these assets were added. This does not establish
model quality or token savings. Graft automatic setup remains Linux-only.
Future releases default to Linux unless Windows is explicitly requested again.
'''


def publish(dist, commit, repository):
    if repository != 'sholee-pt/Harness-Codex' or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Select this repository and an exact source commit')
    version = json.loads((dist / 'build.json').read_text(encoding='utf-8')).get('version')
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError('Invalid release version')
    tag = 'v' + version
    def gh(*args):
        return subprocess.check_output(['gh', *map(str, args)], text=True, encoding='utf-8')
    try:
        release = json.loads(gh('release', 'view', tag, '--repo', repository, '--json', 'body,assets,isDraft'))
    except subprocess.CalledProcessError as exc:
        raise ValueError('Matching Linux release is not published. Preserve the Windows artifact and retry only publication after Linux succeeds; no polling was started.') from exc
    endpoint = f'repos/{repository}'
    if release['isDraft'] or tag_commit(gh, endpoint, gh('api', endpoint + '/git/ref/tags/' + tag)) != commit:
        raise ValueError('Release tag does not identify the selected published source')
    with tempfile.TemporaryDirectory(prefix='harness-windows-publish-') as temporary:
        root = Path(temporary)
        gh('release', 'download', tag, '--repo', repository, '--dir', root, '--pattern', 'build.json', '--pattern', 'SHA256SUMS')
        merged, sums, additions = prepare(dist, root, commit)
        existing = {item['name'] for item in release['assets']}
        # Verify partial/repeated publications before any further remote write.
        for name, expected in additions.items():
            if name in existing:
                gh('release', 'download', tag, '--repo', repository, '--dir', root, '--pattern', name)
                if digest(root / name) != expected:
                    raise ValueError('Existing Windows binary differs; it was preserved')
        for name in additions:
            if name not in existing:
                gh('release', 'upload', tag, dist / name, '--repo', repository)
        for name, data in (('build.json', json.dumps(merged, indent=2) + '\n'),
                           ('SHA256SUMS', ''.join(f'{value}  {name}\n' for name, value in sums.items()))):
            path = root / name
            if path.read_text(encoding='utf-8') != data:
                path.write_text(data, encoding='utf-8', newline='\n')
                gh('release', 'upload', tag, path, '--repo', repository, '--clobber')
        body = notes(release['body'], version)
        if body != release['body']:
            path = root / 'release-body.md'
            path.write_text(body, encoding='utf-8', newline='\n')
            gh('release', 'edit', tag, '--repo', repository, '--notes-file', path)
    print(json.dumps({'release': tag, 'sourceCommit': commit, 'windowsAssets': sorted(additions), 'linuxBinariesReplaced': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    publish(args.dist.resolve(), args.commit, args.repository)
