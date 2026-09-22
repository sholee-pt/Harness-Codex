"""User-facing CLI and between-session update policy."""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import subprocess
import sys

from . import distribution, environment, presentation as ui
from .project import preflight_project_command, register_project_commands, run_project_command


def version(source_root: Path) -> str:
    path = source_root / ".agents/skills/harness/scripts/harness_metadata.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HARNESS_VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError("Harness release metadata is missing.")


def default_data_root(*, installer: bool = False) -> Path:
    if not installer and os.environ.get("HARNESS_TOOL_HOME"):
        return Path(os.environ["HARNESS_TOOL_HOME"]).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "HarnessCodex"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "harness-codex"


def default_bin_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Programs/HarnessCodex/bin"
    return Path.home() / ".local/bin"


def _register_path(bin_dir: Path, *, dry_run: bool = False) -> dict:
    if os.name == "nt":
        from .windows_path import register_path
    else:
        from .shell import register_path
    return register_path(bin_dir, dry_run=dry_run)


class _AgentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        choices = []
        for name in ("_root_agent_choices", "_command_agent_choices"):
            choices.extend(getattr(parsed, name, []))
            if hasattr(parsed, name):
                delattr(parsed, name)
        if len(set(choices)) > 1:
            self.error("Conflicting --agent/--runtime selections; choose one agent provider.")
        # Keep the internal provider field compatible with v9.3 callers.
        parsed.runtime = choices[0] if choices else "codex"
        return parsed


def _agent_options(parser, *, destination: str) -> None:
    parser.add_argument("--agent", dest=destination, action="append", choices=("codex", "claude"),
                        default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    parser.add_argument("--runtime", dest=destination, action="append", choices=("codex", "claude"),
                        default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def build_parser(source_root: Path) -> argparse.ArgumentParser:
    parser = _AgentParser(prog="harness-codex", description="Install, configure and use a native Codex project harness.")
    parser.add_argument("--version", "-V", action="store_true", help="Show the installed Harness version and exit.")
    parser.add_argument('--json', action='store_true', help='Show complete diagnostic reports as JSON.')
    _agent_options(parser, destination="_root_agent_choices")
    parser.add_argument("--no-update-check", action="store_true", help="Skip automatic upstream checks for this invocation.")
    commands = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    register_project_commands(commands)
    from .maintenance import register
    register(commands)
    from .routing import register as register_routing
    register_routing(commands)
    from .checkpoint import register as register_checkpoint
    register_checkpoint(commands)
    from .graft import register as register_graft
    register_graft(commands)
    from .jev import register as register_jev
    register_jev(commands)
    for name in ("init", "new", "resume", "start", "configure"):
        commands.choices[name].add_argument("--no-update-check", action="store_true", default=argparse.SUPPRESS)
    install = commands.add_parser("install", help="Install this tool into user-local managed storage.")
    install.add_argument("--data-dir", type=Path, default=default_data_root(installer=True))
    install.add_argument("--bin-dir", type=Path, default=default_bin_root())
    install.add_argument("--branch", help="Pin vX.Y.Z[-beta]; otherwise follow the latest release branch. Legacy branches remain readable.")
    install.add_argument("--repository", default=distribution.DEFAULT_REPOSITORY, help="HTTPS or SSH transport for sholee-pt/Harness-Codex.")
    install.add_argument("--auto-update", choices=("compatible", "check", "off"), default="compatible")
    install.add_argument("--no-modify-path", action="store_true", help="Skip user PATH registration (Bash startup on Linux; user registry on Windows).")
    install.add_argument("--existing", choices=("ask", "reuse", "reset"), default="ask",
                         help="When installation traces exist, choose whether to reuse or reset Harness tool settings.")
    install.add_argument("--owned-runtime", type=Path, help=argparse.SUPPRESS)
    uninstall = commands.add_parser("uninstall", help="Remove the CLI and its owned runtime after typing yes; keep project harnesses and reused environments.")
    uninstall.add_argument("--data-dir", type=Path, default=default_data_root())
    uninstall.add_argument("--dry-run", action="store_true", help="Preview tool removal without confirmation or writes.")
    update = commands.add_parser("update", help="Check or install an upstream tool release without changing project files.")
    update.add_argument("--check", action="store_true", help="Only inspect upstream versions; write nothing.")
    update.add_argument("--repair-launcher", action="store_true", help="Repair an owned legacy launcher or interrupted migration offline, then exit.")
    update.add_argument("--data-dir", type=Path, default=default_data_root())
    update.add_argument("--branch", help="Select vX.Y.Z[-beta] or a legacy version branch.")
    update.add_argument("--repository", help="Choose HTTPS or SSH authentication transport for the same repository.")
    update.add_argument("--timeout", type=float, default=20)
    for command in dict.fromkeys(commands.choices.values()):
        _agent_options(command, destination="_command_agent_choices")
        if '--json' not in command._option_string_actions:
            command.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='Show the complete diagnostic report as JSON.')
    return parser


def _environment() -> None:
    environment.validate_interpreter()


def _launcher_environment_gate(args, source_root: Path) -> int | None:
    if not os.environ.get("HARNESS_TOOL_HOME"):
        return None
    data_root = default_data_root()
    status = distribution.launcher_status(data_root)
    if Path(status["sourceRoot"]).resolve() != source_root.resolve():
        if source_root.resolve().is_relative_to((data_root / "releases").resolve()):
            raise ValueError("The active Harness release changed after this command started. "
                             "Repeat the installed harness command from the same parent terminal; Codex was not started.")
        return None
    args._launcher_environment_status = status
    launches_codex = (args.command in {"init", "configure", "reset"}
                      and not getattr(args, "dry_run", False) and not getattr(args, "install_only", False)
                      and not getattr(args, "_existing_init_noop", False)
                      and (args.command != "reset" or getattr(args, "yes", False)))
    if not launches_codex:
        return None
    if status["state"] != "current":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            repair = status.get("repairCommand") or "harness update --repair-launcher"
            raise ValueError(f"The legacy launcher needs offline repair. Run {repair}, then repeat this command from the same parent terminal.")
        distribution.repair_launcher(data_root)
        print("Harness launcher repaired. The legacy invocation already changed its own environment; Codex was not started. "
              "Repeat this command from the same parent terminal to preserve your project environment.", file=sys.stderr)
        return 1
    if os.environ.get(environment.LAUNCHER_MARKER) != environment.PRESERVED_ENVIRONMENT:
        raise ValueError("This invocation cannot establish preserved caller environment after a legacy launcher/update. "
                         "Run the installed harness command again from the same parent terminal; Codex was not started.")
    return None


def _automatic_update(args, source_root: Path, argv: list[str]) -> int | None:
    if (args.command not in {"init", "configure"} or getattr(args, "dry_run", False)
            or getattr(args, "install_only", False) or getattr(args, "_existing_init_noop", False) or args.no_update_check
            or os.environ.get("HARNESS_NO_UPDATE_CHECK") == "1"
            or not os.environ.get("HARNESS_TOOL_HOME")
            or not sys.stdin.isatty() or not sys.stdout.isatty()):
        return None
    data_root = default_data_root()
    try:
        state = distribution.installed_status(data_root)
        policy = state.get("auto_update", "compatible")
        if policy == "off" or not distribution.check_due(data_root):
            return None
        distribution.mark_check(data_root)
        result = distribution.check_update(data_root, timeout=5)
        if not result.get("updateAvailable"):
            return None
        available = result.get("availableVersion", "")
        if policy != "compatible" or distribution._version(available)[0] != distribution._version(version(source_root))[0]:
            print(f"Harness update available: {available}. Run {state.get('command', 'harness')} update to install it.", file=sys.stderr)
            return None
        with ui.Progress(f'Installing compatible Harness update {available}'):
            distribution.update_tool(data_root, timeout=30, expected_major=distribution._version(version(source_root))[0])
        active = distribution.installed_status(data_root)
        new_root = Path(active["release_root"])
        if new_root.resolve() != source_root.resolve():
            environment = os.environ.copy()
            environment["HARNESS_NO_UPDATE_CHECK"] = "1"
            return subprocess.call([sys.executable, "-B", str(new_root / "harness.py"), *argv], env=environment)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Harness update check unavailable; continuing with the installed version. {exc}", file=sys.stderr)
    return None


def main(argv: list[str] | None = None, *, source_root: Path | None = None) -> int:
    source_root = source_root or Path(__file__).resolve().parents[1]
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(source_root)
    args = parser.parse_args(argv)
    ui.JSON_MODE.set(args.json)
    if args.runtime != "codex":
        print("harness: Claude integration is not implemented in this tool. "
              "This command is Codex-only. Claude editions use a separate harness-claude command.",
              file=sys.stderr)
        return 2
    if args.version:
        print(f"Harness for Codex {version(source_root)}")
        parser.exit(0)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        _environment()
        if args.command == "uninstall":
            from .uninstall import run
            return run(args.data_dir, dry_run=args.dry_run)
        if args.command == "install":
            from .setup import choose, path_registration, reset_check_cache
            choice, previous = choose(args.data_dir, args.bin_dir, args.existing)
            if args.owned_runtime:
                from .footprint import validate_root
                validate_root(args.owned_runtime, args.data_dir)
            if previous is not None and choice == 'reuse':
                args.branch, args.repository, args.auto_update = previous['branch'], previous['repository'], previous['auto_update']
                if distribution.version_key(version(source_root)) >= distribution.version_key('0.11.0-beta'):
                    args.repository = distribution.canonical_repository(args.repository)
                    if args.branch and args.branch.startswith('codex/'):
                        args.branch = None
                        print('Legacy codex/ branch pin retired; updates now follow the newest compatible Harness-Codex release.')
            if not args.no_modify_path:
                path_registration(args.bin_dir, reset=choice == 'reset', dry_run=True)
            if args.owned_runtime:
                from .footprint import record
                # Validate and seal native runtime ownership before creating or
                # updating the CLI's active installation state.
                record(args.owned_runtime, args.data_dir, attach=False)
            result = distribution.install_tool(source_root, args.data_dir, args.bin_dir,
                                               python_executable=sys.executable, branch=args.branch,
                                               repository=args.repository, auto_update=args.auto_update)
            ui.report(result, title='Tool installation')
            if args.owned_runtime:
                from .footprint import record
                runtime = record(args.owned_runtime, args.data_dir)
                if args.json:
                    ui.report(runtime, title='Runtime ownership')
            if choice == 'reset':
                reset_check_cache(args.data_dir)
            if not args.no_modify_path:
                ui.report(path_registration(args.bin_dir, reset=choice == 'reset'), title='PATH registration')
            hint = "Open a new terminal." if os.name == "nt" else "Apply PATH in this Bash session: source ~/.bashrc"
            if args.no_modify_path:
                hint = "PATH registration skipped; invoke the command by its full path."
            print(f"Installed {result.get('command', 'harness')} in {args.bin_dir.expanduser().absolute()}. {hint}")
            return 0
        if args.command == "update":
            if args.repair_launcher:
                if args.check or args.branch is not None or args.repository is not None:
                    raise ValueError("--repair-launcher is offline and cannot be combined with --check, --branch, or --repository.")
                ui.report(distribution.repair_launcher(args.data_dir), title='Launcher repair')
                print("Repeat project commands from the same parent terminal so they inherit its original environment.")
                return 0
            if args.timeout <= 0 or args.timeout > 600:
                raise ValueError("--timeout must be greater than zero and at most 600 seconds.")
            action = distribution.check_update if args.check else distribution.update_tool
            with ui.Progress('Checking for Harness updates' if args.check else 'Updating Harness'):
                result = action(args.data_dir, branch=args.branch, repository=args.repository, timeout=args.timeout)
            ui.report(result, title='Tool update')
            if not args.check:
                from .codex_integration import read as integration_read, install as integration_install
                if integration_read(args.data_dir) is not None:
                    active = distribution.installed_status(args.data_dir)
                    ui.report(integration_install(args.data_dir, Path(active['release_root'])), title='Native Codex integration')
                print("Tool update complete. Use harness-codex config --project PATH to refresh the owned generator and review the existing project harness.")
            return 0
        if args.command == 'maintenance':
            from .maintenance import run
            return run(args, source_root)
        if args.command == 'routing':
            from .routing import run
            return run(args, source_root)
        if args.command == 'checkpoint':
            from .checkpoint import run
            return run(args, source_root)
        if args.command == 'graft':
            from .graft import run
            return run(args, source_root)
        if args.command == 'jev':
            from .jev import run
            return run(args, source_root)
        preflight_project_command(args, source_root=source_root)
        if args.command == "init" and not args.dry_run and os.environ.get("HARNESS_TOOL_HOME"):
            _register_path(Path(distribution.installed_status(default_data_root())["binDir"]))
        launcher_result = _launcher_environment_gate(args, source_root)
        if launcher_result is not None:
            return launcher_result
        updated = _automatic_update(args, source_root, argv)
        if updated is not None:
            return updated
        return run_project_command(args, source_root=source_root)
    except KeyboardInterrupt:
        print("Harness interrupted.", file=sys.stderr)
        return 130
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 1
