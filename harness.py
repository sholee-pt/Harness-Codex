#!/usr/bin/env python3
"""Harness command entry point. Runtime dependencies are Python standard library only."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
if sys.version_info < (3, 11):
    raise SystemExit("Harness requires Python 3.11 or later. Use the platform installer from installer/ in a checkout or the archive root to prepare its environment.")

from harness_cli.main import main

if __name__ == "__main__":
    raise SystemExit(main(source_root=Path(__file__).resolve().parent))
