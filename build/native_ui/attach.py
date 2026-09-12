"""Attach both verified native assets to an exact-commit tool release."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harness_cli import native_package as package


def attach(dist, artifacts):
    build = json.loads((dist / 'build.json').read_text(encoding='utf-8'))
    if not build.get('commit') or build.get('developmentBuild'):
        raise ValueError('Native components require a verified source release')
    entries, selected = {}, {}
    with tempfile.TemporaryDirectory(prefix='harness-ui-attach-') as temporary:
        for platform in package.TARGETS:
            name = f'harness-codex-ui-{build["version"]}-{platform}.tar.gz'
            candidates = list(artifacts.rglob(name))
            if len(candidates) != 1 or (dist / name).exists():
                raise ValueError('Expected exactly one new native release asset per platform')
            unpacked = Path(temporary) / platform
            package.extract(candidates[0], unpacked)
            metadata = package.verify(unpacked, build['version'], platform)
            if metadata.get('harnessSourceCommit') != build['commit']:
                raise ValueError('Native UI was not built from this exact Harness commit')
            entries[name] = package.fingerprint(candidates[0])
            selected[name] = candidates[0]
    for name, path in selected.items():
        shutil.copyfile(path, dist / name)
        if package.fingerprint(dist / name) != entries[name]:
            raise ValueError('Native asset changed while attaching the release')
    sums = dist / 'SHA256SUMS'
    with sums.open('a', encoding='utf-8', newline='\n') as stream:
        for name, value in sorted(entries.items()):
            stream.write(value['sha256'] + '  ' + name + '\n')
    build['nativeUi'] = entries
    (dist / 'build.json').write_text(json.dumps(build, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'attached': entries, 'commit': build['commit']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    attach(args.dist, args.artifacts)
