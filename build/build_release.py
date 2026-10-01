#!/usr/bin/env python3
"""Build a reproducible Linux distribution from verified source."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.artifacts import write_artifacts
from build.source import checked_path, collect_source
from harness_cli.paths import external_location, project_root


def build(root: Path, output: Path, *, allow_dirty: bool = False, platform: str = 'linux') -> dict:
    if platform not in ('linux', 'both'):
        raise ValueError('Build platform must be linux or both')
    root = project_root(root)
    output = external_location(output)
    if output == root or root in output.parents or any(p.casefold() == ".git" for p in output.parts):
        raise ValueError("Build output must be outside the source tree and Git metadata")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Build output must be a new or empty directory; existing files are preserved")
    version, commit, files, bootstraps = collect_source(root, allow_dirty=allow_dirty)
    return write_artifacts(output, version, commit, files, bootstraps, platform=platform)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument('--platform', choices=('linux', 'both'), default='linux',
                        help='Linux by default; both is retained for future Windows validation')
    args = parser.parse_args()
    try:
        print(json.dumps(build(Path(__file__).resolve().parents[1], args.output,
                               allow_dirty=args.allow_dirty, platform=args.platform), indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"build: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
