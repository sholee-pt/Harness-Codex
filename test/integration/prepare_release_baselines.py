"""Materialize only the immediately preceding version for comparison."""
import argparse
import io
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASELINES = {
    'v0330': '6e4469a4e0ef2c186d252aad1bb125605a6ad97b',
}


def prepare(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name, commit in BASELINES.items():
        content = subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(),
                                           '-C', str(ROOT), 'archive', commit], timeout=60)
        destination = output / name
        destination.mkdir()
        with tarfile.open(fileobj=io.BytesIO(content)) as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or '\\' in member.name:
                    raise ValueError('Unexpected Git archive path')
                target = destination.joinpath(*path.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
                else:
                    raise ValueError('Unexpected Git archive member type')
        if not (destination / '.agents/skills/harness/scripts/harness_apply.py').is_file():
            raise ValueError('Incomplete baseline: ' + name)
        print(name + ': ' + commit)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
