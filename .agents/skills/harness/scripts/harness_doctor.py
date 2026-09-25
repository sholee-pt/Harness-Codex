#!/usr/bin/env python3
"""Read-only installation diagnostics; never launch Codex or alter a workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

import harness_metadata
import harness_instruction_audit
import validate_harness


def diagnose(root: Path) -> dict:
    if not root.is_dir():
        raise ValueError("workspace root must be an existing directory")
    validator = validate_harness.Validator(root.resolve())
    validation = validator.run()
    prefix = Path(sys.prefix)
    harness_environment = prefix.name == "harness" and (prefix / "conda-meta/history").is_file()
    python_supported = sys.version_info >= (3, 11)
    errors = list(validation["errors"])
    if not harness_environment:
        errors.append("Run harness-codex helper harness_doctor with the installed dedicated Python interpreter.")
    if not python_supported:
        errors.append("Harness requires Python 3.11 or later.")
    return {
        "diagnosticVersion": 1,
        "harnessVersion": harness_metadata.HARNESS_VERSION,
        "valid": validation["valid"] and not errors,
        "installationStatus": validation["installationStatus"],
        "integrityValid": validation["integrityValid"],
        "managedIntegrityValid": validation["managedIntegrityValid"],
        "upgradeRequirements": validation["upgradeRequirements"],
        "environment": {
            "harnessCondaEnvironment": harness_environment,
            "pythonSupported": python_supported,
            "codexCliOnPath": shutil.which("codex") is not None,
            "codexCliRequired": "only-for-cli-execution",
        },
        "activation": validation["activation"],
        "validationLayers": validation["validationLayers"],
        "summary": validation["summary"],
        "externalCapabilities": validation["externalCapabilities"],
        "instructionInventory": harness_instruction_audit.inspect(root, validator.manifest),
        "errors": errors,
        "warnings": validation["warnings"],
        "workspaceWrites": False,
        "codexInvoked": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        report = diagnose(Path(args.root))
    except (OSError, ValueError) as exc:
        report = {"valid": False, "errors": [str(exc)], "workspaceWrites": False, "codexInvoked": False}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 2 if report.get("installationStatus") == "upgrade-required" and not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
