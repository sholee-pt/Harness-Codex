"""Keep project process settings separate from the dedicated helper interpreter."""

from __future__ import annotations

import os
from pathlib import Path
import sys


LAUNCHER_MARKER = "HARNESS_LAUNCHER_ENVIRONMENT"
PRESERVED_ENVIRONMENT = "preserved-v1"


def validate_interpreter() -> Path:
    prefix = Path(sys.prefix)
    expected = os.environ.get("HARNESS_INSTALL_EXPECTED_PREFIX")
    mismatch = expected is not None and os.path.normcase(str(prefix.resolve())) != os.path.normcase(str(Path(expected).resolve()))
    if prefix.name != "harness" or not (prefix / "conda-meta/history").is_file() or mismatch:
        raise ValueError("Run Harness in its dedicated Conda environment. "
                         f"Expected prefix: {expected or 'the selected harness environment'}; "
                         f"actual sys.prefix: {sys.prefix}; executable: {sys.executable}; "
                         f"Python: {sys.version.split()[0]}; CONDA_PREFIX: {os.environ.get('CONDA_PREFIX', '<unset>')}. "
                         "Rerun the current platform installer; it selects the environment's absolute Python path.")
    return prefix


def helper_environment() -> dict[str, str]:
    """Only deterministic helper subprocesses receive these Harness settings."""
    prefix = validate_interpreter()
    result = os.environ.copy()
    result["CONDA_PREFIX"] = str(prefix)
    result["CONDA_DEFAULT_ENV"] = "harness"
    # The interpreter directory is known from the running executable. No project
    # environment is guessed, activated, deactivated, or edited.
    executable_directory = str(Path(sys.executable).absolute().parent)
    result["PATH"] = executable_directory + (os.pathsep + result["PATH"] if result.get("PATH") else "")
    result.pop(LAUNCHER_MARKER, None)
    return result


def codex_environment() -> dict[str, str]:
    result = os.environ.copy()
    # This private entry-point marker must not claim provenance for nested calls.
    result.pop(LAUNCHER_MARKER, None)
    result.pop("HARNESS_INSTALL_EXPECTED_PREFIX", None)
    return result
