"""User-facing CLI and between-session update policy."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

from . import distribution, environment
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


def default_data_root() -> Path:
    if os.environ.get("HARNESS_TOOL_HOME"):
        return Path(os.environ["HARNESS_TOOL_HOME"]).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "HarnessCLI"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "harness-cli"


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
                        help="Agent provider (default: codex; Claude integration is not implemented yet).")
    parser.add_argument("--runtime", dest=destination, action="append", choices=("codex", "claude"),
                        default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def build_parser(source_root: Path) -> argparse.ArgumentParser:
    parser = _AgentParser(prog="harness", description="Install, configure and use a native Codex project harness.")
    parser.add_argument("--version", "-V", action="store_true", help="Show the installed Harness version and exit.")
    _agent_options(parser, destination="_root_agent_choices")
    parser.add_argument("--no-update-check", action="store_true", help="Skip automatic upstream checks for this invocation.")
    commands = parser.add_subparsers(dest="command")
    register_project_commands(commands)
    for name in ("init", "start", "configure"):
        commands.choices[name].add_argument("--no-update-check", action="store_true", default=argparse.SUPPRESS)
    install = commands.add_parser("install", help="Install this tool into user-local managed storage.")
    install.add_argument("--data-dir", type=Path, default=default_data_root())
    install.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    install.add_argument("--branch", help="Pin a codex/vN[.M] branch; otherwise track the latest Codex branch.")
    install.add_argument("--repository", default=distribution.DEFAULT_REPOSITORY, help="HTTPS or SSH transport for sholee-pt/Harness.")
    install.add_argument("--auto-update", choices=("compatible", "check", "off"), default="compatible")
    update = commands.add_parser("update", help="Check or install an upstream tool release without changing project files.")
    update.add_argument("--check", action="store_true", help="Only inspect upstream versions; write nothing.")
    update.add_argument("--repair-launcher", action="store_true", help="Repair an owned legacy launcher or interrupted migration offline, then exit.")
    update.add_argument("--data-dir", type=Path, default=default_data_root())
    update.add_argument("--branch", help="Select a specific codex/vN[.M] branch.")
    update.add_argument("--repository", help="Choose HTTPS or SSH authentication transport for the same repository.")
    update.add_argument("--timeout", type=float, default=20)
    for command in commands.choices.values():
        _agent_options(command, destination="_command_agent_choices")
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
    launches_codex = (args.command in {"init", "configure", "start", "reset"}
                      and not getattr(args, "dry_run", False) and not getattr(args, "install_only", False)
                      and not getattr(args, "_existing_init_noop", False)
                      and (args.command != "reset" or getattr(args, "yes", False)))
    if not launches_codex:
        return None
    if status["state"] != "current":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError("The legacy launcher needs offline repair. Run harness update --repair-launcher, then repeat this command from the same parent terminal.")
        distribution.repair_launcher(data_root)
        print("Harness launcher repaired. The legacy invocation already changed its own environment; Codex was not started. "
              "Repeat this command from the same parent terminal to preserve your project environment.", file=sys.stderr)
        return 1
    if os.environ.get(environment.LAUNCHER_MARKER) != environment.PRESERVED_ENVIRONMENT:
        raise ValueError("This invocation cannot establish preserved caller environment after a legacy launcher/update. "
                         "Run the installed harness command again from the same parent terminal; Codex was not started.")
    return None


def _automatic_update(args, source_root: Path, argv: list[str]) -> int | None:
    if (args.command not in {"init", "start", "configure"} or getattr(args, "dry_run", False)
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
        if policy != "compatible" or available.split(".")[0] != version(source_root).split(".")[0]:
            print(f"Harness update available: {available}. Run harness update to install it.", file=sys.stderr)
            return None
        print(f"Installing compatible Harness update {available} before starting Codex...", file=sys.stderr)
        result = distribution.update_tool(data_root, timeout=30, expected_major=int(version(source_root).split(".")[0]))
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
    if args.runtime != "codex":
        print("harness: Claude integration is not implemented in this tool. "
              "Use --agent codex; Claude-native editions remain on the separate claude/* repository branches.",
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
        if args.command == "install":
            result = distribution.install_tool(source_root, args.data_dir, args.bin_dir,
                                               python_executable=sys.executable, branch=args.branch,
                                               repository=args.repository, auto_update=args.auto_update)
            print(json.dumps(result, indent=2))
            print(f"Add {args.bin_dir.expanduser().absolute()} to PATH, then run harness --version.")
            return 0
        if args.command == "update":
            if args.repair_launcher:
                if args.check or args.branch is not None or args.repository is not None:
                    raise ValueError("--repair-launcher is offline and cannot be combined with --check, --branch, or --repository.")
                print(json.dumps(distribution.repair_launcher(args.data_dir), indent=2))
                print("Repeat project commands from the same parent terminal so they inherit its original environment.")
                return 0
            if args.timeout <= 0 or args.timeout > 600:
                raise ValueError("--timeout must be greater than zero and at most 600 seconds.")
            action = distribution.check_update if args.check else distribution.update_tool
            result = action(args.data_dir, branch=args.branch, repository=args.repository, timeout=args.timeout)
            print(json.dumps(result, indent=2))
            if not args.check:
                print("Tool update complete. Use harness init --project PATH --install-only to update the project generator, then harness configure --project PATH for a reviewed project update.")
            return 0
        preflight_project_command(args, source_root=source_root)
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
