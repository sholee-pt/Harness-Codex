"""User-facing CLI and between-session update policy."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

from . import distribution
from .project import register_project_commands, run_project_command


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


def build_parser(source_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Install, configure and use a native Codex project harness.")
    parser.add_argument("--version", "-V", action="store_true", help="Show the installed Harness version and exit.")
    parser.add_argument("--runtime", choices=("codex", "claude"), default="codex",
                        help="Runtime provider (default: codex; Claude installation is not implemented yet).")
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
    update.add_argument("--data-dir", type=Path, default=default_data_root())
    update.add_argument("--branch", help="Select a specific codex/vN[.M] branch.")
    update.add_argument("--repository", help="Choose HTTPS or SSH authentication transport for the same repository.")
    update.add_argument("--timeout", type=float, default=20)
    for command in commands.choices.values():
        command.add_argument("--runtime", choices=("codex", "claude"), default=argparse.SUPPRESS,
                             help="Runtime provider (Codex supported; Claude not implemented yet).")
    return parser


def _environment() -> None:
    # The launcher uses the real dedicated interpreter, not a spoofed Conda label.
    prefix = Path(sys.prefix)
    if prefix.name != "harness" or not (prefix / "conda-meta/history").is_file():
        raise ValueError("Run Harness in its dedicated Conda environment. Use bash install.sh, or conda run -n harness python harness.py ...")
    os.environ["CONDA_PREFIX"] = str(prefix)
    os.environ["CONDA_DEFAULT_ENV"] = "harness"


def _automatic_update(args, source_root: Path, argv: list[str]) -> int | None:
    if (args.command not in {"init", "start", "configure"} or getattr(args, "dry_run", False)
            or getattr(args, "install_only", False) or args.no_update_check
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
        print("harness: Claude runtime installation is not implemented in this tool. "
              "Use --runtime codex; Claude-native editions remain on the separate claude/* repository branches.",
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
            if args.timeout <= 0 or args.timeout > 600:
                raise ValueError("--timeout must be greater than zero and at most 600 seconds.")
            action = distribution.check_update if args.check else distribution.update_tool
            result = action(args.data_dir, branch=args.branch, repository=args.repository, timeout=args.timeout)
            print(json.dumps(result, indent=2))
            if not args.check:
                print("Tool update complete. Existing project artifacts are unchanged; use harness init --project PATH to update and review a project.")
            return 0
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
