#!/usr/bin/env python3
"""Build reproducible Linux and Windows distributions from verified source."""
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


def build(root: Path, output: Path, *, allow_dirty: bool = False) -> dict:
    root = checked_path(root)
    output = checked_path(output)
    if output == root or root in output.parents or any(p.casefold() == ".git" for p in output.parts):
        raise ValueError("Build output must be outside the source tree and Git metadata")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Build output must be a new or empty directory; existing files are preserved")
    version, commit, files, bootstraps = collect_source(root, allow_dirty=allow_dirty)
    return write_artifacts(output, version, commit, files, bootstraps)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(build(Path(__file__).resolve().parents[1], args.output, allow_dirty=args.allow_dirty), indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"build: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
