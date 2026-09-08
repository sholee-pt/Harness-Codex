#!/usr/bin/env python3
"""Compatibility entry point for project-local generator installation."""
import sys

sys.dont_write_bytecode = True
from harness_cli.project_installer import InstallError, install, main


if __name__ == "__main__":
    raise SystemExit(main())
