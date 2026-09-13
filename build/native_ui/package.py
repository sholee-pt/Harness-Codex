"""Keep official Codex helpers intact; replace only the checked UI entrypoint."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness_cli import native_package as package
from harness_cli.main import version
from build.native_ui.dependencies import download
from build.native_ui.source import source_commit

OFFICIAL = {
    'linux-x86_64': 'fc6e3e3b85f2cf7d664520ee5c66a7fe4aa12bae7d46834f47e2f165fd0d6f78',
    'windows-x86_64': '94cc5b3632769504c809f6c0364b693c0dfddc5c30c8361095d2263a07ac45a4',
}


def prepare(output, platform):
    archive = output.with_suffix('.official.tar.gz')
    download('https://github.com/openai/codex/releases/download/rust-v0.154.0/codex-package-'
             + package.TARGETS[platform] + '.tar.gz', archive)
    if package.fingerprint(archive)['sha256'] != OFFICIAL[platform]:
        raise ValueError('Official Codex package checksum mismatch')
    package.extract(archive, output)
    # The canonical archive contains its layout directly, not a parent folder.
    if not (output / 'codex-package.json').is_file():
        raise ValueError('Unexpected official Codex archive layout')
    if platform.startswith('linux-') and os.environ.get('GITHUB_ENV'):
        digest = package.fingerprint(output / 'codex-resources/bwrap')['sha256']
        with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as environment:
            environment.write('CODEX_BWRAP_SHA256=' + digest + '\n')
    print('Verified original Codex helpers and package layout.')


def assemble(root, binary, platform, output):
    commit = source_commit()
    suffix = '.exe' if platform.startswith('windows-') else ''
    original, _ = package.inventory(root)
    shutil.copyfile(binary, root / ('bin/codex' + suffix))
    (root / ('bin/codex' + suffix)).chmod(0o755)
    for name in ('UPSTREAM_LICENSE', 'UPSTREAM_NOTICE'):
        shutil.copyfile(Path(__file__).with_name(name), root / name)
    files, directories = package.inventory(root)
    for name, record in original.items():
        if name != 'bin/codex' + suffix and files[name] != record:
            raise ValueError('An original Codex helper was modified')
    metadata = {'schema': 1, 'version': version(ROOT), 'platform': platform,
                'target': package.TARGETS[platform], 'upstreamCommit': package.UPSTREAM,
                'harnessSourceCommit': commit, 'directIntegrationVersion': 1,
                'officialPackageSha256': OFFICIAL[platform],
                'extensionSha256': hashlib.sha256(Path(__file__).with_name('harness_routing.rs').read_bytes()).hexdigest(),
                'files': files, 'directories': sorted(directories)}
    (root / 'harness-ui.json').write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    package.verify(root, version(ROOT), platform)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f'harness-codex-ui-{version(ROOT)}-{platform}.tar.gz'
    with destination.open('xb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w') as archive:
            for name in sorted([*files, 'harness-ui.json']):
                path = root / name
                member = archive.gettarinfo(str(path), arcname=name)
                member.uid = member.gid = member.mtime = 0
                member.uname = member.gname = ''
                with path.open('rb') as incoming:
                    archive.addfile(member, incoming)
    print(json.dumps({'asset': destination.name, **package.fingerprint(destination), 'provenance': metadata}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'assemble'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--platform', choices=list(OFFICIAL), required=True)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root, args.platform)
    else:
        assemble(args.root, args.binary, args.platform, args.output)
