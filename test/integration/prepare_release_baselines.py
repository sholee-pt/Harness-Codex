"""Materialize immutable local Git baselines without mixing shell temp roots."""
import argparse
import io
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
BASELINES = {
    'v98_layout': 'fcb9a7d286efc4384c04802abeb6e17af3fda0be',
    'v98': 'e3c8fc5676686215573befdd65570219dc26f7b1',
    'v97': 'd5dba32bc1576e0e4e64624cf87986a03a35fa39',
    'v76': 'd91f0a5ae261d44c86f4082ba5098d55b7e5cc4c',
    'v80': 'ed2972555562c736496e8d90463f52efabf05305',
    'v81': '2a920f9555df7270d8947b9e926654746aeb9247',
    'v90': 'a1e12dadb1805e23df4c283eaa7a613e6b1b1b91',
    'v91': '0d1e2bd885cd9ee4432918a19ec9839339af70e8',
    'v92': '72e5cd82975aac838011d991a3e2e6da349ef4de',
    'v93': 'fa9892cfaa4741edb2e843a4e890f246c5cf1fe3',
    'v94': 'f80ed8b14e74720c2dc19d303d53300c19a1acaf',
    'v95': '3b771abc19b64c473185b40d9217df0c6a0d4c76',
    'v96': 'ee3791f6b6732c61bd6fa5e5e37ece362d808850',
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
