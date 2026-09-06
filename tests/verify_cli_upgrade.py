"""Run the real v9.2 tool installer/updater against v9.3 using local Git transport.

Only the fixed upstream URL is replaced for this test. Git branch discovery,
fetch, ancestry, archives, old installation code, and the new launcher are real.
No GitHub request or live Codex call occurs. Run in the harness Conda environment.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harness_cli import distribution as current


def run(arguments, *, cwd=None, environment=None):
    completed = subprocess.run(list(map(str, arguments)), cwd=cwd, env=environment,
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
    if completed.returncode:
        raise AssertionError(f"Fixture process failed ({completed.returncode}): {completed.stdout}\n{completed.stderr}")
    return completed.stdout


def state(root):
    return {path.relative_to(root).as_posix():
            (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def old_project(baseline, root, runtime_path):
    sys.path[:0] = [str(baseline / ".agents/skills/harness/scripts"), str(baseline / "tests")]
    import harness_apply
    import harness_metadata
    import harness_plan_builder
    import test_runtime_teamplay
    import shutil

    assert harness_metadata.HARNESS_VERSION == "9.2"
    shutil.copytree(baseline / "tests/fixtures/coordinated-cross-contract", root)
    draft = test_runtime_teamplay.DeterministicPlanBuilderTests()._draft("coordinated-cross-contract-plan.json")
    plan = harness_plan_builder.materialize_plan(draft, root=root)
    harness_apply.apply_application(harness_apply.build_application(root, plan))
    manifest = json.loads((root / ".harness/manifest.json").read_text(encoding="utf-8"))
    runtime = test_runtime_teamplay.valid_plan(root, manifest)
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    return {"generatorVersion": manifest["generator"]["version"], "runtimePlanCreated": True}


def verify(baseline):
    spec = importlib.util.spec_from_file_location("_old_harness_distribution", baseline / "harness_cli/distribution.py")
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    old_snapshot = old._snapshot(baseline)
    new_snapshot = current._snapshot(REPO)
    assert old._source_info(old_snapshot)[0] == "9.2"
    assert current._source_info(new_snapshot)[0] == "9.3"
    assert "install_harness.sh" in new_snapshot, "The candidate must include the optional bootstrap to test its omission."
    assert not old._runtime("install_harness.sh")
    baseline_before = state(baseline)
    environment = os.environ.copy()
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                 "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"):
        environment.pop(name, None)
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_TERMINAL_PROMPT="0", HARNESS_NO_UPDATE_CHECK="1")
    with tempfile.TemporaryDirectory(prefix="harness-cli-upgrade-") as temporary:
        base = Path(temporary)
        upstream = base / "local upstream"
        upstream.mkdir()
        data, binary, project = base / "tool data", base / "tool bin", base / "user project"
        runtime_path = base / "previous-runtime.json"

        def git(*arguments):
            return run(["git", "-c", "safe.directory=" + upstream.as_posix(), "-C", upstream, *arguments], environment=environment)

        def populate(snapshot, previous=()):
            for name in set(previous) - set(snapshot):
                (upstream / name).unlink()
            for name, content in snapshot.items():
                path = upstream.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

        populate(old_snapshot)
        git("init", "--quiet", "--initial-branch=codex/v9.2")
        git("config", "core.autocrlf", "false")
        git("add", "--all")
        git("-c", "user.name=Harness fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "Real v9.2 runtime")
        previous_commit = git("rev-parse", "HEAD").strip()
        with mock.patch.dict(os.environ, environment, clear=True):
            installed = old.install_tool(upstream, data, binary, python_executable=sys.executable, auto_update="off")
        assert installed["commit"] == previous_commit
        old_release_before = state(Path(installed["sourceRoot"]))
        run([sys.executable, "-B", __file__, "--baseline", baseline, "--project-worker", project, "--runtime", runtime_path], environment=environment)
        (project / "user-notes.txt").write_bytes(b"Preserve the user's own work.\r\n")
        run(["git", "init", "--quiet", project], environment=environment)
        project_before = state(project)

        git("checkout", "--quiet", "-b", "codex/v9.3")
        populate(new_snapshot, old_snapshot)
        git("add", "--all")
        git("-c", "user.name=Harness fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "Real v9.3 runtime")
        next_commit = git("rev-parse", "HEAD").strip()
        real_git = old._git
        calls = []

        def local_transport(arguments, **kwargs):
            calls.append(list(arguments))
            for argument in arguments:
                if argument.startswith(("https://", "http://", "ssh://", "git@")):
                    assert argument == old.DEFAULT_REPOSITORY, "Unexpected network destination in fixture"
            rewritten = [str(upstream) if argument == old.DEFAULT_REPOSITORY else argument for argument in arguments]
            # This allowance exists only in the injected test transport.
            return real_git(["-c", "protocol.file.allow=always", *rewritten], **kwargs)

        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(old, "_git", side_effect=local_transport):
            updated = old.update_tool(data)
        assert updated["updated"] and updated["installation"]["commit"] == next_commit
        active = current.installed_status(data)
        active_root = Path(active["sourceRoot"])
        assert active["version"] == "9.3"
        assert not (active_root / "install_harness.sh").exists(), "The old updater must exercise its original root-file allowlist"
        assert state(Path(installed["sourceRoot"])) == old_release_before
        launcher = data / "launcher.py"
        version = run([sys.executable, "-B", launcher, "--version"], cwd=project, environment=environment).strip()
        assert version == "Harness for Codex 9.3", version
        doctor = json.loads(run([sys.executable, "-B", launcher, "doctor", "--project", project], environment=environment))
        assert doctor["valid"] and doctor["installationStatus"] == "valid", doctor
        runtime = json.loads(run([sys.executable, "-B", active_root / ".agents/skills/harness/scripts/validate_runtime_plan.py",
                                  "--root", project, "--plan", runtime_path], environment=environment))
        assert runtime["valid"], runtime
        assert state(project) == project_before, "Tool update or validation changed project files/Git metadata"
        assert state(baseline) == baseline_before, "Original baseline source was modified"
        assert any("fetch" in command and command[-1] == next_commit for command in calls)
        return {"status": "passed", "baselineVersion": "9.2", "candidateVersion": "9.3",
                "baselineRuntimeTreeSha256": old._tree_hash(old._hashes(old_snapshot)),
                "candidateRuntimeTreeSha256": current._tree_hash(current._hashes(new_snapshot)),
                "oldInstallerAndUpdaterExecuted": True, "realLocalGitFetchAndAncestry": True,
                "newLauncherVersion": version, "optionalBootstrapOmittedByOldUpdater": True,
                "previousProjectAccepted": True, "previousRuntimePlanAccepted": True,
                "oldReleasePreserved": True, "projectFilesAndGitMetadataUnchanged": True,
                "originalBaselineUnchanged": True, "networkUsed": False, "liveCodexInvoked": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--project-worker", type=Path)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    if args.project_worker:
        print(json.dumps(old_project(args.baseline.resolve(), args.project_worker, args.runtime)))
        return 0
    report = verify(args.baseline.resolve())
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
