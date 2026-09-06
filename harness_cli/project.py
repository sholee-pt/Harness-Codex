"""Project commands that reuse the installer and the native interactive Codex CLI."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


class ProjectError(ValueError):
    """A project command cannot proceed with the supplied prerequisites."""


def register_project_commands(subparsers) -> None:
    descriptions = {
        "init": "Install the generator and configure a project in interactive Codex.",
        "configure": "Review and configure an installed project harness in interactive Codex.",
        "start": "Open interactive Codex with the project's harness selected.",
        "doctor": "Check project files and activation contracts without launching Codex.",
    }
    for command, description in descriptions.items():
        parser = subparsers.add_parser(command, help=description, description=description)
        parser.set_defaults(command=command)
        parser.add_argument("--project", type=Path, default=Path.cwd(),
                            help="Existing project directory (default: current directory).")
        if command != "doctor":
            parser.add_argument("--codex-binary", default="codex",
                                help="Codex executable name or path (default: codex on PATH).")
        if command in {"init", "configure"}:
            parser.add_argument("--goal", help="Describe the work this project will support.")
        if command == "init":
            parser.add_argument("--dry-run", action="store_true",
                                help="Preview generator installation; do not write or launch Codex.")
            parser.add_argument("--install-only", action="store_true",
                                help="Install the generator without launching Codex.")
        if command == "start":
            parser.add_argument("prompt", nargs="?", help="Optional initial task, supplied as one quoted argument.")


def _installer(source_root: Path):
    path = source_root / "install.py"
    name = "_harness_cli_project_installer"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ProjectError("The Harness installation is missing install.py; reinstall the tool.")
    module = importlib.util.module_from_spec(spec)
    # dataclass resolves its defining module during import.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _project_path(value: Path, installer) -> Path:
    root = installer.checked_path(value)
    if not root.is_dir():
        raise ProjectError("--project must name an existing directory; create the folder first.")
    if any(part.rstrip(" .").casefold() == ".git" for part in root.parts):
        raise ProjectError("--project must not be inside Git metadata.")
    return root


def _codex_command(binary: str) -> list[str]:
    executable = shutil.which(os.path.expanduser(binary))
    if executable is None:
        raise ProjectError(
            "Codex CLI was not found. Install Codex and make it available on PATH, "
            "or pass --codex-binary PATH. Use init --install-only to install just the generator."
        )
    # Batch files may invoke a shell even with shell=False on Windows. A native
    # executable avoids interpreting user goal/prompt text as shell commands.
    if os.name == "nt" and Path(executable).suffix.casefold() in {".bat", ".cmd"}:
        raise ProjectError("Select the native codex.exe with --codex-binary; batch wrappers are not supported.")
    return [str(Path(executable).absolute())]


def _interactive_codex(binary: str) -> list[str]:
    command = _codex_command(binary)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ProjectError(
            "Interactive Codex requires a terminal. Run this command in an interactive terminal. "
            "For unattended installation, use init --install-only (or --dry-run), then run configure in a terminal."
        )
    return command


def _report(source_root: Path, root: Path, *, doctor: bool = False) -> tuple[int, dict]:
    scripts = source_root / ".agents/skills/harness/scripts"
    helper = scripts / ("harness_doctor.py" if doctor else "validate_harness.py")
    if not helper.is_file():
        raise ProjectError(f"The Harness installation is missing {helper.name}; reinstall the tool.")
    arguments = [sys.executable, "-B", str(helper)]
    arguments += ["--root", str(root)] if doctor else [str(root)]
    completed = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", check=False)
    try:
        report = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        detail = completed.stderr.strip()
        raise ProjectError(f"{helper.name} did not return a diagnostic report. {detail}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("valid"), bool):
        raise ProjectError(f"{helper.name} returned an invalid diagnostic report.")
    return completed.returncode, report


def _reviewable_missing_reference(root: Path, label: str, relative: str, *, source_root: Path) -> bool:
    """Missing-path diagnostics skip some metadata checks; complete them here."""
    try:
        value = json.loads((root / ".harness/manifest.json").read_text(encoding="utf-8"))
        for component in label.split("."):
            match = re.fullmatch(r"([A-Za-z]+)(?:\[(\d+)\])?", component)
            if match is None:
                return False
            value = value[match.group(1)]
            if match.group(2) is not None:
                value = value[int(match.group(2))]
        if (not isinstance(value, dict) or value.get("path") != relative
                or not isinstance(value.get("claim"), str) or not value["claim"].strip()
                or not isinstance(value.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None):
            return False
        lines = value.get("lines")
        if lines is not None and (not isinstance(lines, dict)
                                  or type(lines.get("start")) is not int or type(lines.get("end")) is not int
                                  or not 1 <= lines["start"] <= lines["end"]):
            return False
        # The trusted validator already checked portable/reserved path rules.
        # Recheck lexical links before allowing the configuration session to start.
        candidate = _installer(source_root).checked_path(root / relative)
        return not candidate.exists()
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return False


def _only_stale_evidence(report: dict, *, configuration: bool = False,
                         root: Path | None = None, source_root: Path | None = None) -> bool:
    """Allow ordinary content drift only when every safety layer still passes."""
    layers = report.get("validationLayers", {})
    safety = {"transactionSafety", "rootContext", "manifestContract", "workspaceOwnership",
              "topologyAndArtifacts", "managedOwnership", "runtimeStateSeparation"}
    if (not isinstance(layers, dict) or not safety.issubset(layers)
            or report.get("upgradeRequirements")
            or layers.get("evidenceFreshness", {}).get("status") != "failed"):
        return False
    for name, layer in layers.items():
        if name not in {"evidenceFreshness", "artifactCompatibility"} and layer.get("status") != "passed":
            return False
    label = (r"(?:project\.evidence\[\d+\]|topology\."
             r"(?:boundaries|skills|agents|qualityPatternPolicies|routingPolicies)\[\d+\]"
             r"(?:\.persistence)?\.evidence\[\d+\])")
    stale = re.compile(label + r"(?:\.path changed after generation: (?P<changed>[^\r\n]+)"
                       r"|\.lines exceeds (?P<shortened>[^\r\n]+))")
    missing = re.compile(r"invalid (?P<label>" + label + r")\.path: evidence path does not exist: (?P<path>[^\r\n]+)")
    errors = report.get("errors", [])
    if not isinstance(errors, list) or not errors:
        return False
    changed, shortened, absent = set(), set(), set()
    for error in errors:
        match = stale.fullmatch(error) if isinstance(error, str) else None
        if match is None:
            missing_match = missing.fullmatch(error) if isinstance(error, str) else None
            if (configuration and root is not None and source_root is not None and missing_match is not None
                    and _reviewable_missing_reference(root, missing_match.group("label"), missing_match.group("path"),
                                                      source_root=source_root)):
                absent.add(missing_match.group("path"))
                continue
            return False
        if match.group("changed") is not None:
            changed.add(match.group("changed"))
        else:
            shortened.add(match.group("shortened"))
    # A shortened range is evidence drift only alongside a changed content hash;
    # a range-only defect could instead be a malformed manually edited manifest.
    return bool(changed or absent) and shortened.issubset(changed)


def _check_existing(source_root: Path, root: Path, *, required: bool = False) -> bool:
    manifest = root / ".harness/manifest.json"
    if not manifest.exists() and not manifest.is_symlink() and not required:
        return False
    status, report = _report(source_root, root)
    if status == 0 and report["valid"]:
        return False
    if not required and report.get("installationStatus") == "upgrade-required" and report.get("integrityValid"):
        return False
    if _only_stale_evidence(report, configuration=not required, root=root, source_root=source_root):
        print("Project evidence is stale after source edits or removals. Managed files and safety contracts still pass; "
              "Codex must re-read current source before relying on project claims. "
              "The manifest has not been refreshed or declared valid.", file=sys.stderr)
        return True
    print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
    raise ProjectError(
        "The project harness is not ready. Run harness doctor --project PATH and resolve its findings; "
        "use harness init for a new installation or configure for a supported upgrade."
    )


def _configuration_prompt(goal: str | None) -> str:
    prompt = (
        "$harness Configure or update the project harness inside this selected workspace. "
        "Read the installed generator skill and follow its evidence-based analysis, proposal, dry-run, "
        "safe apply, and installed validation workflow. Preserve user-owned files and instructions. "
        "Generate only roles and skills justified by recurring project responsibilities. "
        "If the work or goals are unclear, ask for the missing information instead of inventing a fixed agent team. "
        "Do not commit, push, or modify Git metadata as part of harness configuration. "
        "After configuration, explain the validation result. Confirm whether the new native components are available "
        "before using them; if they are not visible, direct the user to a fresh harness start session."
    )
    if goal:
        prompt += "\n\nThe user's project goal:\n" + goal
    return prompt


def _work_prompt(prompt: str | None, *, stale_evidence: bool = False) -> str:
    instructions = (
        "$project-harness Read and use this project's harness for this session. "
        "Follow existing project instructions and Codex permission settings. "
        "Editing files does not authorize commit or push; require separate authorization for each, "
        "honoring any explicit existing authorization within its stated scope."
    )
    if stale_evidence:
        instructions += (
            "\n\nSome recorded source evidence changed after generation. Re-read the current workspace and "
            "the relevant source files before relying on stale project claims or choosing agents. "
            "Do not automatically regenerate or rewrite the harness merely because source files changed. "
            "If current evidence shows that the task needs a different persistent design, explain the finding "
            "and propose a reviewed harness configure update."
        )
    if prompt:
        return instructions + "\n\nThe user's task:\n" + prompt
    return instructions + "\n\nRead the routing instructions and wait for the user's next task."


def _launch(command: list[str], root: Path, prompt: str) -> int:
    print("Opening interactive Codex with the project harness instructions. Exit Codex to return to Harness.", flush=True)
    try:
        result = subprocess.run([*command, "--cd", str(root), prompt], cwd=root, check=False)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        raise ProjectError(f"Could not launch Codex: {exc}. The installed project files have been retained.") from exc
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def _finish_configuration(source_root: Path, root: Path, command: list[str], goal: str | None) -> int:
    status = _launch(command, root, _configuration_prompt(goal))
    if status:
        print(f"Codex exited with status {status}; configuration has not been confirmed. Run harness doctor --project PATH.",
              file=sys.stderr)
        return status
    status, report = _report(source_root, root)
    if status or not report["valid"]:
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
        print("Codex exited, but a valid project harness was not confirmed. Run harness configure --project PATH to continue.",
              file=sys.stderr)
        return status or 1
    print("Project harness files validate. This check does not prove runtime loading, task quality, or token savings.")
    print("Use harness start --project PATH for your next project session.")
    return 0


def run_project_command(args: argparse.Namespace, *, source_root: Path) -> int:
    """Execute one registered project command; return an ordinary process status."""
    try:
        source_root = Path(source_root).absolute()
        installer = _installer(source_root)
        root = _project_path(args.project, installer)
        source = source_root / ".agents/skills/harness"
        if args.command == "doctor":
            status, report = _report(source_root, root, doctor=True)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return status
        if args.command == "init":
            command = None if args.dry_run or args.install_only else _interactive_codex(args.codex_binary)
            _check_existing(source_root, root)
            report = installer.install(root, source=source, dry_run=args.dry_run)
            print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
            if args.dry_run:
                print("Dry-run only: no generator files were written and Codex was not launched.")
                return 0
            if args.install_only:
                print("Generator installed. This command did not configure the project harness. Run harness configure --project PATH in a terminal.")
                return 0
            return _finish_configuration(source_root, root, command, args.goal)
        if args.command == "configure":
            command = _interactive_codex(args.codex_binary)
            _check_existing(source_root, root)
            destination = root / ".agents/skills/harness"
            if not (destination / "SKILL.md").is_file():
                raise ProjectError("The generator is not installed. Run harness init --project PATH first.")
            installation = installer.install(root, source=source, dry_run=True)
            if installation["writes"] or installation["removes"] or installation["directoriesCreated"]:
                raise ProjectError("The installed generator needs updating. Run harness init --project PATH to update and configure it.")
            return _finish_configuration(source_root, root, command, args.goal)
        if args.command == "start":
            command = _interactive_codex(args.codex_binary)
            stale = _check_existing(source_root, root, required=True)
            return _launch(command, root, _work_prompt(args.prompt, stale_evidence=stale))
        raise ProjectError(f"Unknown project command: {args.command}")
    except KeyboardInterrupt:
        print("Harness interrupted.", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 1
