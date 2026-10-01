"""Project harness management; conversations belong to native Codex."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .environment import codex_environment, helper_environment
from .project_installer import load_installer
from . import presentation as ui


class ProjectError(ValueError):
    """A project command cannot proceed with the supplied prerequisites."""


def register_project_commands(subparsers) -> None:
    descriptions = {
        "init": "Install the generator and configure a project with live progress.",
        "configure": "Review and configure a project harness with live progress.",
        "new": "Start a new Codex conversation using the shared project harness.",
        "resume": "Resume a Codex conversation with the current project harness.",
        "start": "Deprecated alias for new.",
        "doctor": "Check project files and activation contracts without launching Codex.",
        "status": "Show whether a generator and project harness already exist.",
        "remove": "Preview or remove only unchanged Harness-owned project files.",
        "reset": "Preview or remove the generated harness, then configure it afresh.",
    }
    for command, description in descriptions.items():
        parser = subparsers.add_parser("config" if command == "configure" else command,
                                      aliases=["configure"] if command == "configure" else [],
                                      help=description, description=description)
        parser.set_defaults(command=command)
        parser.add_argument("--project", "--project-dir", "--project_dir", dest="project", type=Path,
                            default=None if command in {"new", "resume", "start"} else Path.cwd(),
                            help="Project directory (default: current directory; native resume controls its own directory when omitted).")
        parser.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                            help='Show the complete diagnostic report as JSON.')
        if command in {"init", "configure", "new", "resume", "start", "reset"}:
            parser.add_argument("--codex-binary", default="codex",
                                help="Codex executable name or path (default: codex on PATH).")
            parser.add_argument('--settings', choices=('ask', 'auto', 'manual', 'native'), default='ask',
                                help='Ask for automatic/manual selection (default), select a mode directly, or keep native settings.')
        if command in {"init", "configure", "reset"}:
            parser.add_argument('--routing-profiles', type=Path, help='Optional JSON model preferences for the native Auto extension.')
            parser.add_argument('--native-ui-archive', type=Path, help='Verified native Codex extension archive for offline integration setup.')
            parser.add_argument('--auto-model', choices=('manual', 'auto'), help='Default inference choice for new Codex launches; existing Codex preferences stay unchanged.')
            parser.add_argument('--no-codex-integration', action='store_true', help='Do not install the native Auto extension; --retrieval controls Graft setup separately.')
            parser.add_argument('--activate', choices=('ask', 'shell', 'skip'), default='ask', help='After native integration, offer a Bash with ~/.bashrc loaded; skip in noninteractive/JSON mode.')
            parser.add_argument('--retrieval', choices=('auto', 'off'), default='auto' if command == 'init' else None,
                                help='Prepare Graft and Jev shadow advice on init (Jev needs TYPESAFE_API_KEY for queries), or disable retrieval. Config/reset preserve choices unless specified.')
            parser.add_argument('--maintenance', choices=('off', 'suggest', 'auto'),
                                help='Project maintenance after configuration; interactive init asks when omitted. Auto may update existing skills only.')
            parser.add_argument('--adaptive', choices=('on', 'off'),
                                help='Use recorded outcomes for Auto advice; interactive init asks when omitted. Does not select Auto or grade quality automatically.')
            parser.add_argument('--interactive', action='store_true', help='Use the native Codex conversation screen instead of progress output.')
            parser.add_argument('--details', action='store_true', help='Show the model summary and native session ID after configuration.')
            parser.add_argument('--timeout', type=float, default=1800, help='Configuration time limit in seconds (default: 1800).')
            if command == 'configure':
                parser.add_argument('--resume', metavar='SESSION_ID', help='Continue an unfinished native configuration session.')
            goals = parser.add_mutually_exclusive_group()
            goals.add_argument("--goal", help="Describe the project purpose, responsibilities and constraints.")
            goals.add_argument("--goal-file", type=Path, metavar="MARKDOWN",
                               help="Reference a UTF-8 Markdown brief; no file-size limit and no full-text prompt copy.")
        if command == "init":
            parser.add_argument('--hook-trust', choices=('auto', 'manual'), default='auto',
                                help='Register Harness maintenance hooks and trust their exact definitions through Codex (default: auto), even with maintenance/adaptive off. Manual leaves native trust unchanged.')
            parser.add_argument("--dry-run", action="store_true",
                                help="Preview generator installation; do not write or launch Codex.")
            parser.add_argument("--install-only", action="store_true",
                                help="Install the generator without launching Codex.")
        if command in {"new", "start"}:
            parser.add_argument("prompt", nargs="?", help="Optional initial task, supplied as one quoted argument.")
        if command in {'new', 'resume'}:
            parser.add_argument('--ui', choices=('native', 'harness'), default='native',
                                help='Use the installed Codex (default), or its pinned original UI with the Harness Auto extension.')
            parser.add_argument('--routing-profiles', type=Path, help='Optional JSON model preferences for the Harness UI.')
            parser.add_argument('--native-ui-archive', type=Path, help='Install a downloaded native UI release archive for --ui harness.')
        if command == "resume":
            parser.add_argument("session_id", nargs="?", help="Native Codex session ID or name; omit to open its picker.")
            parser.add_argument("--last", action="store_true", help="Resume the latest Codex conversation in this project.")
            parser.add_argument('--reload-harness', action='store_true',
                                help='Send one brief harness reload request; ordinary resume adds no activation turn.')
        if command in {"remove", "reset"}:
            parser.add_argument("--yes", action="store_true", help="Apply the displayed ownership-checked operation.")
            parser.add_argument("--dry-run", action="store_true", help="Preview only, even when --yes is supplied.")
        if command == "remove":
            parser.add_argument('--expected-plan', help=argparse.SUPPRESS)
            parser.add_argument('--cleanup-empty-dirs', action='store_true', help='After owned file removal, remove only empty component directories; never global Codex settings. Otherwise ask in a terminal.')
            parser.add_argument("--include-generator", action="store_true", help="Also remove unchanged files owned by the generator installer.")
            parser.add_argument("--recover", action="store_true", help="Preview or recover an interrupted CLI removal instead of starting a new removal.")

    # argparse keeps these parsers for one-release compatibility, but not in public help.
    subparsers._choices_actions[:] = [action for action in subparsers._choices_actions
                                     if action.dest not in {'new', 'resume', 'start'}]


def _pending_transaction(root: Path, installer) -> str | None:
    path = installer.checked_path(root / ".harness/transaction.json")
    if not os.path.lexists(path):
        for relative, state in ((".harness/removals", "orphaned-removal-workspace"),
                                (".harness/transactions", "orphaned-transaction-workspace")):
            if os.path.lexists(installer.checked_path(root / relative)):
                return state
        return None
    if path.is_file() and path.stat().st_size <= 4 * 1024 * 1024:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("operation") == "remove":
                return "removal-pending"
        except (ValueError, UnicodeError):
            pass
    return "transaction-pending"


def _assert_no_transaction(root: Path, installer) -> None:
    pending = _pending_transaction(root, installer)
    if pending in {"orphaned-removal-workspace", "orphaned-transaction-workspace"}:
        raise ProjectError("Harness recovery data exists without its journal. Preserve the backup directory and review its ownership manually before configuration; automatic recovery cannot establish the original state.")
    if pending == "removal-pending":
        raise ProjectError("An interrupted removal must be recovered first. Run harness-codex remove --project PATH --recover to preview recovery, then add --yes.")
    if pending:
        raise ProjectError("A project transaction is pending. Run harness-codex doctor --project PATH and recover it before continuing.")


def _goal_input(args, installer) -> str | None:
    goal = getattr(args, "goal", None)
    goal_file = getattr(args, "goal_file", None)
    if goal_file is None:
        if goal is not None and (not goal.strip() or "\0" in goal):
            raise ProjectError("--goal must contain nonempty text without NUL characters.")
        return goal
    from .project_brief import reference
    from .paths import external_location
    return reference(external_location(goal_file))


def _validate_prompt_transport(root: Path, prompt: str, command: list[str] | None = None, *, native_argv=True) -> None:
    if "\0" in prompt or len(prompt.encode("utf-8")) > 72 * 1024:
        raise ProjectError("The combined project prompt is too large or contains a NUL character; shorten the project brief.")
    if os.name == "nt" and native_argv:
        arguments = [*(command or ["codex.exe"]), "--cd", str(root), prompt]
        if len(subprocess.list2cmdline(arguments).encode("utf-16-le")) // 2 + 1 > 32767:
            raise ProjectError("The project brief exceeds the Windows command-line limit; shorten the Markdown before retrying.")


def preflight_project_command(args, *, source_root: Path) -> None:
    """Validate user input before automatic tool updates or project writes."""
    if args.command in {'new', 'resume', 'start'}:
        if args.command == 'resume' and args.last and args.session_id:
            raise ProjectError('Choose a session ID or --last, not both.')
        args._project_preflight_complete = True
        return
    installer = load_installer(source_root)
    from .paths import project_target
    root = project_target(args.project, error_type=ProjectError) if args.command == 'init' else _project_path(args.project, installer)
    if args.command not in {"remove", "status", "doctor"}:
        _assert_no_transaction(root, installer)
    if args.command == "remove" and args.recover and args.include_generator:
        raise ProjectError("--recover restores the recorded operation; it cannot be combined with --include-generator.")
    if args.command in {"init", "configure", "reset"}:
        if not 0 < args.timeout <= 86400:
            raise ProjectError('--timeout must be between 0 and 86400 seconds.')
        if getattr(args, 'resume', None) is not None:
            if args.interactive or not args.resume.strip() or len(args.resume) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in args.resume):
                raise ProjectError('--resume needs a valid native session ID and cannot be combined with --interactive.')
        args._goal_text = _goal_input(args, installer)
        _validate_prompt_transport(root, _configuration_prompt(args._goal_text), native_argv=args.interactive)
    args._existing_init_noop = (args.command == "init" and not args.dry_run and not args.install_only
                                and os.path.lexists(root / ".harness/manifest.json")
                                and not getattr(args, "goal", None) and getattr(args, "goal_file", None) is None)
    args._project_preflight_complete = True


def _project_path(value: Path, installer) -> Path:
    from .paths import project_root
    return project_root(value, error_type=ProjectError)


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
    completed = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", check=False,
                               env=helper_environment())
    try:
        report = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        detail = completed.stderr.strip()
        raise ProjectError(f"{helper.name} did not return a diagnostic report. {detail}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("valid"), bool):
        raise ProjectError(f"{helper.name} returned an invalid diagnostic report.")
    return completed.returncode, report


def _reviewable_missing_reference(root: Path, label: str, relative: str, *, source_root: Path, manifest=None) -> bool:
    """Missing-path diagnostics skip some metadata checks; complete them here."""
    try:
        value = manifest if manifest is not None else json.loads((root / ".harness/manifest.json").read_text(encoding="utf-8"))
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
        candidate = load_installer(source_root).checked_path(root / relative)
        return not candidate.exists()
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return False


def _only_stale_evidence(report: dict, *, root: Path | None = None, source_root: Path | None = None) -> bool:
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
    manifest = None
    for error in errors:
        match = stale.fullmatch(error) if isinstance(error, str) else None
        if match is None:
            missing_match = missing.fullmatch(error) if isinstance(error, str) else None
            if root is not None and source_root is not None and missing_match is not None and manifest is None:
                try:
                    manifest = json.loads((root / '.harness/manifest.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    return False
            if (root is not None and source_root is not None and missing_match is not None
                    and _reviewable_missing_reference(root, missing_match.group("label"), missing_match.group("path"),
                                                      source_root=source_root, manifest=manifest)):
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
    _assert_no_transaction(root, load_installer(source_root))
    manifest = root / ".harness/manifest.json"
    if not manifest.exists() and not manifest.is_symlink() and not required:
        return False
    status, report = _report(source_root, root)
    if status == 0 and report["valid"]:
        return False
    if not required and report.get("installationStatus") == "upgrade-required" and report.get("integrityValid"):
        return False
    if _only_stale_evidence(report, root=root, source_root=source_root):
        print("Project evidence is stale after source edits or removals. Managed files and safety contracts still pass; "
              "Codex must re-read current source before relying on project claims. "
              "The manifest has not been refreshed or declared valid.", file=sys.stderr)
        return True
    ui.report(report, title='Project harness needs attention', error=True)
    raise ProjectError(
        "The project harness is not ready. Run harness-codex doctor --project PATH and resolve its findings; "
        "use harness-codex init for a new installation or config for a supported upgrade."
    )


def _has_router_content(router: Path, installer) -> bool:
    # Removal retains directories it cannot prove it owns. Empty scaffolds,
    # including nested reference directories, are not unowned artifacts.
    pending = [router]
    while pending:
        current = installer.checked_path(pending.pop())
        if not os.path.lexists(current):
            continue
        if not current.is_dir():
            return True
        pending.extend(current.iterdir())
    return False


def project_status(source_root: Path, root: Path, installer) -> dict:
    """Distinguish a copied generator from a configured project harness."""
    result = {"runtime": "codex", "state": "absent", "generator": "absent", "harnessPresent": False, "errors": []}
    pending = _pending_transaction(root, installer)
    manifest = installer.checked_path(root / ".harness/manifest.json")
    result["harnessPresent"] = os.path.lexists(manifest)
    destination = installer.checked_path(root / ".agents/skills/harness")
    if os.path.lexists(destination):
        try:
            if destination == source_root / ".agents/skills/harness":
                result["generator"] = "source-checkout"
            else:
                entries = installer.snapshot(destination)
                managed = installer.read_receipt(entries)
                result["generator"] = "installed" if managed else "absent"
        except (OSError, ValueError) as exc:
            result["generator"] = "invalid-or-unowned"
            result["errors"].append(str(exc))
    if pending:
        result["state"] = pending
        if pending in {"orphaned-removal-workspace", "orphaned-transaction-workspace"}:
            result["errors"].append("Recovery data exists without its journal; preserve it for manual ownership review.")
            result["nextCommand"] = None
        else:
            result["nextCommand"] = ("harness-codex remove --project PATH --recover" if pending == "removal-pending"
                                     else "harness-codex doctor --project PATH")
        return result
    if result["harnessPresent"]:
        code, report = _report(source_root, root)
        if "summary" in report:
            result["summary"] = report["summary"]
        if code == 0 and report["valid"]:
            result["state"] = "configured"
        elif report.get("installationStatus") == "upgrade-required" and report.get("integrityValid"):
            result["state"] = "upgrade-required"
        elif _only_stale_evidence(report, root=root, source_root=source_root):
            result["state"] = "stale-evidence"
        else:
            result["state"] = "invalid"
        result["errors"].extend(report.get("errors", []))
    else:
        # A leftover router without a manifest is not an owned installation.
        router = installer.checked_path(root / ".agents/skills/project-harness")
        if _has_router_content(router, installer):
            result["state"] = "unowned-artifacts"
            result["errors"].append("Project router files exist without a manifest; their ownership is not established.")
        elif result["generator"] in {"installed", "source-checkout"}:
            result["state"] = "generator-only"
    if result["generator"] == "invalid-or-unowned":
        result["state"] = "invalid"
    can_reread = (result["state"] == "stale-evidence"
                  and _only_stale_evidence(report, root=root, source_root=source_root))
    result["nextCommand"] = ("codex" if result["state"] == "configured" or can_reread
                             else "harness-codex config --project PATH" if result["state"] in {"generator-only", "stale-evidence", "upgrade-required"}
                             else "harness-codex init --project PATH" if result["state"] == "absent"
                             else "harness-codex doctor --project PATH")
    if result["state"] == "stale-evidence":
        result["guidance"] = (
            "New conversations can re-read changed source without regenerating the harness. Review configuration only if responsibilities or verification risks changed."
            if can_reread else
            "Some source references require a configuration review before start. Preserve the current harness and inspect the detailed findings."
        )
    return result


def _configuration_prompt(goal: str | None, *, context: str | None = None) -> str:
    prompt = (
        "$harness Configure or update the project harness inside this selected workspace. "
        "Read the installed generator skill and follow its evidence-based analysis, proposal, dry-run, "
        "safe apply, and installed validation workflow. Preserve user-owned files and instructions. "
        "Generate only roles and skills justified by recurring project responsibilities. "
        "If the work or goals are unclear, ask for the missing information instead of inventing a fixed agent team. "
        "Do not commit, push, or modify Git metadata as part of harness configuration. "
        "After configuration, explain the validation result. Confirm whether the new native components are available "
        "before using them; if they are not visible, direct the user to a fresh native codex session."
        " The CLI maintains .harness/GUIDE.md as the single project harness guide. "
        "Do not create dated/versioned Harness guide copies or edit that CLI-owned guide; "
        "keep project-specific routing instructions in the managed project harness."
        " Run bundled Python helpers through harness-codex helper SCRIPT_NAME (without .py); "
        "this selects the installed interpreter without activating or changing the project's environment. "
        "For older generator references, replace conda run -n harness python <skill-root>/scripts/SCRIPT_NAME.py "
        "with that helper command."
    )
    if context:
        prompt += '\n\n' + context
    prompt += "\nVerified helper command prefix (JSON argv; quote for the active shell): " + json.dumps(
        [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'harness.py'), '--no-update-check', 'helper'])
    if goal:
        prompt += "\n\nThe user's project goal:\n" + goal
    return prompt


def _compat_conversation(args):
    """One-release forwarding only: no project validation, metadata query or injected turn."""
    print(f"'harness-codex {args.command}' is deprecated. Run 'codex"
          + (" resume" if args.command == 'resume' else "")
          + "' directly from the configured project.", file=sys.stderr)
    command = _codex_command(args.codex_binary)
    arguments = list(command)
    if args.project is not None:
        arguments += ['--cd', str(args.project.expanduser().absolute())]
    if args.command == 'resume':
        arguments.append('resume')
        if args.last:
            arguments.append('--last')
        elif args.session_id is not None:
            arguments += ['--', args.session_id]
        if args.reload_harness:
            print('--reload-harness no longer inserts a user turn. Ask Codex to re-read project instructions when needed.', file=sys.stderr)
    elif args.prompt is not None:
        arguments += ['--', args.prompt]
    result = subprocess.run(arguments, env=codex_environment(), check=False)
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def _configure_integration(args, source_root):
    if getattr(args, 'no_codex_integration', False):
        return
    from .main import default_data_root
    from .codex_integration import install
    report = install(default_data_root(), source_root,
                     archive=getattr(args, 'native_ui_archive', None), mode=getattr(args, 'auto_model', None),
                     profiles=getattr(args, 'routing_profiles', None))
    ui.report(report, title='Native Codex integration')
    print(report['nextStep'])
    from .shell import offer_activation
    offer_activation(mode=getattr(args, 'activate', 'ask'), cwd=args.project)


def _configure_retrieval(args, source_root, root):
    mode = getattr(args, 'retrieval', None)
    if mode is None or getattr(args, 'dry_run', False) or getattr(args, 'install_only', False):
        return
    from .graft import automatic
    try:
        with ui.Progress('Preparing local code retrieval', compact=True):
            report = automatic(root, source_root, disabled=mode == 'off')
        ui.report(report, title='Graft retrieval')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        ui.report({'state': 'unavailable', 'guidance': 'The project harness remains usable with ordinary code search.',
                   'warnings': [str(exc), 'Retry with harness-codex graft enable --project PATH.']}, title='Graft retrieval', error=True)
        return
    if args.command == 'init' and report.get('state') == 'enabled':
        from .jev import automatic as automatic_jev
        try:
            result = automatic_jev(root, source_root)
            ui.report(result, title='Jev advice')
            if result.get('mode') in {'shadow', 'suggest'} and not result.get('keyAvailable'):
                from .jev_auth import login
                ui.report(login(result['model'], interactive=not getattr(args, 'json', False)), title='Jev authentication')
        except (OSError, ValueError) as exc:
            ui.report({'state': 'unavailable', 'guidance': 'Graft and ordinary code search remain available.',
                       'warnings': [str(exc), 'Retry with harness-codex jev enable --project PATH.']}, title='Jev advice', error=True)


def _launch(command: list[str], root: Path, prompt: str, *, settings: str = 'native', environment=None) -> int:
    """Interactive configuration fallback; work conversations never enter here."""
    if prompt:
        _validate_prompt_transport(root, prompt, command)
    from .native_session import settings_arguments
    arguments = [*command, "--cd", str(root), *settings_arguments(command, root, settings)]
    if prompt:
        arguments.append(prompt)
    if os.name == 'nt' and len(subprocess.list2cmdline(arguments).encode('utf-16-le')) // 2 + 1 > 32767:
        raise ProjectError('The combined native command exceeds the Windows command-line limit.')
    print("Opening interactive Codex configuration. Exit Codex to return to Harness.", flush=True)
    try:
        result = subprocess.run(arguments, cwd=root, check=False, env=codex_environment() if environment is None else environment)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        raise ProjectError(f"Could not launch Codex: {exc}. The installed project files have been retained.") from exc
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def _sync_guide(source_root, root, *, stale=False):
    from .main import version
    from .project_guide import sync
    try:
        state = sync(root, version=version(source_root), revision=harness_revision(root), stale=stale)
        if state.startswith('preserved'):
            print('Project guide: existing user content was preserved at .harness/GUIDE.md.', file=sys.stderr)
    except (OSError, ValueError) as exc:
        print('Project guide update unavailable: ' + ui.clean(exc), file=sys.stderr)


def _finish_configuration(source_root: Path, root: Path, command: list[str], goal: str | None, *, args=None) -> int:
    from .workspace_context import prepare
    context = prepare(root, command)
    prompt = _configuration_prompt(goal, context=context)
    _validate_prompt_transport(root, prompt, command, native_argv=getattr(args, 'interactive', True))
    outcome = None
    if args is not None and not args.interactive:
        from .configuration import run
        print('[1/3] Project generator ready.', flush=True)
        outcome = run(command, root, prompt, timeout=args.timeout,
                      resume_id=getattr(args, 'resume', None), settings=args.settings)
        status = outcome.code
        if outcome.needs_input:
            print('Configuration needs your input:')
            outcome.show_details()
            outcome.show_resume()
            return status
    else:
        status = _launch(command, root, prompt, settings=getattr(args, 'settings', 'native'))
    if status:
        print(f"Configuration {'interrupted' if status == 130 else 'stopped'}; completion has not been confirmed. Run harness-codex status --project PATH.",
              file=sys.stderr)
        return status
    if not os.path.lexists(root / '.harness/manifest.json'):
        if outcome:
            outcome.show_details()
            outcome.show_resume()
        state = project_status(source_root, root, load_installer(source_root))
        ui.report(state, title='Configuration incomplete', error=True)
        print('A complete project harness was not created. Continue with harness-codex config; use --resume SESSION_ID to answer an earlier configuration question.', file=sys.stderr)
        return 1
    with ui.Progress('[3/3] Validate project harness files', compact=True) as progress:
        status, report = _report(source_root, root)
        if status or not report['valid']:
            progress.outcome = 'needs attention'
    if status or not report["valid"]:
        if outcome:
            outcome.show_details()
            outcome.show_resume()
        ui.report(report, title='Configuration needs attention', error=True)
        print("Codex exited, but a valid project harness was not confirmed. Run harness-codex config --project PATH to continue.",
              file=sys.stderr)
        return status or 1
    if outcome and args.details:
        outcome.show_details()
        if outcome.created_session:
            print('Completed setup session: ' + ui.clean(outcome.session_id))
        else:
            outcome.show_resume()
    if ui.JSON_MODE.get():
        ui.report(report, title='Project harness validation')
    print('Configuration complete. Project harness files validate.')
    _sync_guide(source_root, root)
    if outcome and outcome.created_session:
        from .native_session import archive_configuration
        archive_configuration(command, root, outcome.session_id)
    from .project_preferences import configure
    configure(args, source_root, root)
    _configure_retrieval(args, source_root, root)
    _configure_integration(args, source_root)
    print('Next: codex (from this project).')
    return 0


def run_project_command(args: argparse.Namespace, *, source_root: Path) -> int:
    """Execute one registered project command; return an ordinary process status."""
    try:
        ui.JSON_MODE.set(getattr(args, 'json', False))
        source_root = Path(source_root).absolute()
        if not getattr(args, "_project_preflight_complete", False):
            preflight_project_command(args, source_root=source_root)
        if args.command in {'new', 'resume', 'start'}:
            return _compat_conversation(args)
        installer = load_installer(source_root)
        from .paths import project_target
        root = project_target(args.project, error_type=ProjectError) if args.command == 'init' else _project_path(args.project, installer)
        source = source_root / ".agents/skills/harness"
        if args.command == "status":
            report = project_status(source_root, root, installer)
            from .codex_integration import status as integration_status
            from .main import default_data_root
            report['codexIntegration'] = integration_status(default_data_root())
            if hasattr(args, "_launcher_environment_status"):
                report["cliLauncher"] = args._launcher_environment_status
            from . import dashboard
            from .main import version
            report['features'] = dashboard.collect(source_root, root)
            dashboard.display(report, root, version(source_root))
            return 1 if report["state"] in {"invalid", "unowned-artifacts", "removal-pending", "transaction-pending",
                                            "orphaned-removal-workspace", "orphaned-transaction-workspace"} else 0
        if args.command == "doctor":
            status, report = _report(source_root, root, doctor=True)
            from .codex_integration import status as integration_status
            from .main import default_data_root
            report['codexIntegration'] = integration_status(default_data_root())
            if report['codexIntegration']['state'] == 'invalid':
                status = 1
            if hasattr(args, "_launcher_environment_status"):
                report["cliLauncher"] = args._launcher_environment_status
            ui.report(report, title='Project harness diagnosis')
            return status
        if args.command == "init":
            _check_existing(source_root, root)
            existing = os.path.lexists(root / ".harness/manifest.json")
            if existing:
                existing_status = project_status(source_root, root, installer)
                print(f"A project harness already exists ({existing_status['state']}).")
                if existing_status["state"] == "configured":
                    print("Use codex to work, harness-codex config to review it, or reset/remove to replace or remove its owned files.")
                else:
                    print("Review harness-codex status/doctor before use. For a supported upgrade or stale evidence, supply --goal/--goal-file to init for a reviewed update.")
                if args._existing_init_noop:
                    from .project_preferences import configure
                    configure(args, source_root, root)
                    if existing_status['state'] in {'configured', 'stale-evidence'}:
                        from .workspace_context import prepare
                        executable = shutil.which(os.path.expanduser(args.codex_binary))
                        prepare(root, [executable] if executable else [])
                        _configure_retrieval(args, source_root, root)
                    _configure_integration(args, source_root)
                    print("The generated harness was retained; no configuration conversation was launched. Supply --goal/--goal-file to init for an explicit reviewed update.")
                    return 1 if existing_status["state"] == "invalid" else 0
            elif os.path.lexists(root / ".agents/skills/harness"):
                print("The generator is already present; a generated project harness has not yet been confirmed.")
            command = None if args.dry_run or args.install_only else _interactive_codex(args.codex_binary)
            if command is not None:
                _validate_prompt_transport(root, _configuration_prompt(args._goal_text), command, native_argv=args.interactive)
            create_root = not root.exists()
            if create_root and not args.dry_run:
                # The installer validates source/ownership before creating parents.
                if project_target(args.project, error_type=ProjectError) != root:
                    raise ProjectError('Project location changed during preflight; repeat init.')
            report = installer.install(root, source=source, dry_run=args.dry_run, create_root=create_root)
            if create_root and not args.dry_run:
                if _project_path(args.project, installer) != root:
                    raise ProjectError('Project location changed during creation; repeat init.')
                print('Created project directory: ' + str(root))
            if create_root:
                report['projectDirectory'] = 'would-create' if args.dry_run else 'created'
            if args.dry_run or args.install_only or args.interactive or ui.JSON_MODE.get():
                ui.report(report, title='Generator installation')
            if args.dry_run:
                print("Dry-run only: no generator files were written and Codex was not launched.")
                return 0
            if args.install_only:
                print("Generator installed. This command did not configure the project harness. Run harness-codex config --project PATH in a terminal.")
                return 0
            return _finish_configuration(source_root, root, command, args._goal_text, args=args)
        if args.command == "configure":
            command = _interactive_codex(args.codex_binary)
            _validate_prompt_transport(root, _configuration_prompt(args._goal_text), command, native_argv=args.interactive)
            _check_existing(source_root, root)
            destination = root / ".agents/skills/harness"
            if not (destination / "SKILL.md").is_file():
                raise ProjectError("The generator is not installed. Run harness-codex init --project PATH first.")
            installation = installer.install(root, source=source, dry_run=True)
            if installation["writes"] or installation["removes"] or installation["directoriesCreated"]:
                print('Updating the owned project generator before reviewing the existing harness.')
                installer.install(root, source=source)
            return _finish_configuration(source_root, root, command, args._goal_text, args=args)
        if args.command in {"remove", "reset"}:
            from . import lifecycle
            dry_run = args.dry_run or not args.yes
            if args.command == "remove":
                if args.recover:
                    report = lifecycle.recover_removal(root, source_root=source_root, dry_run=dry_run)
                else:
                    report = lifecycle.remove_project(root, source_root=source_root,
                                                      include_generator=args.include_generator, dry_run=dry_run, expected_plan=getattr(args, 'expected_plan', None))
                from .project_cleanup import after_removal
                cleanup = after_removal(root, report, requested=getattr(args, 'cleanup_empty_dirs', False), json_mode=ui.JSON_MODE.get())
                if cleanup is not None:
                    report['directoryCleanup'] = cleanup
                ui.report(report, title='Project removal')
                if cleanup is not None and not ui.JSON_MODE.get():
                    print('Empty directory cleanup: ' + str(len(cleanup['removed'])) + ' removed; ' + str(len(cleanup['retained'])) + ' retained.')
                if dry_run and not ui.JSON_MODE.get():
                    print("Preview only. Add --yes without --dry-run to apply this operation.")
                return 1 if report.get("recoveryRequired") else 0
            # Validate every deterministic prerequisite before resetting owned artifacts.
            plan = lifecycle.remove_project(root, source_root=source_root, dry_run=True)
            installation = installer.install(root, source=source, dry_run=True)
            if dry_run:
                ui.report({"operation": "reset", "dryRun": True, "removal": plan,
                           "generatorInstallation": installation}, title='Project reset preview')
                print("Preview only. Add --yes without --dry-run to remove owned generated files and open fresh configuration.")
                return 0
            command = _interactive_codex(args.codex_binary)
            _validate_prompt_transport(root, _configuration_prompt(args._goal_text), command, native_argv=args.interactive)
            installer.install(root, source=source)
            report = lifecycle.remove_project(root, source_root=source_root, dry_run=False)
            ui.report(report, title='Previous project harness removal')
            if report.get("recoveryRequired"):
                raise ProjectError("Removal committed but cleanup remains pending. Run harness-codex remove --project PATH --recover, then add --yes; run harness-codex config after recovery.")
            _assert_no_transaction(root, installer)
            print("Previous generated harness removed. Starting fresh configuration; if Codex stops early, use harness-codex config to continue.")
            return _finish_configuration(source_root, root, command, args._goal_text, args=args)
        raise ProjectError(f"Unknown project command: {args.command}")
    except KeyboardInterrupt:
        print("Harness interrupted.", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 1


def harness_revision(root: Path) -> str:
    """Fingerprint the canonical manifest, including its recorded managed hashes.

    Call only after ownership validation. Formatting, source drift and session
    metadata do not create different configuration revisions.
    """
    manifest = json.loads((root / ".harness/manifest.json").read_text(encoding="utf-8"))
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()
