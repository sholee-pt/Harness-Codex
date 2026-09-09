"""Extract the current changelog section as an inline GitHub release body."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build.source import release_version


def release_notes(root: Path) -> str:
    version = release_version(root)
    heading = '## Harness for Codex v' + version
    content = (root / 'CHANGELOG.md').read_text(encoding='utf-8')
    sections = re.findall(r'^' + re.escape(heading) + r'\n(.*?)(?=^## |\Z)', content, re.M | re.S)
    if len(sections) != 1 or not sections[0].strip():
        raise ValueError('Changelog must have exactly one nonempty current release section')
    return sections[0].strip() + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(release_notes(Path(__file__).resolve().parents[1]), encoding='utf-8', newline='\n')
