"""Run the previous release installer and beta migrator using local Git transport.

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


# The previous source is read-only evidence, including lazily imported modules.
# Keep this true even when the caller does not supply Python's -B option.
sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[2]
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
    tests_root = baseline / ("test" if (baseline / "test").is_dir() else "tests")
    sys.path[:0] = [str(baseline / ".agents/skills/harness/scripts"), str(tests_root)]
    import harness_apply
    import harness_metadata
    import harness_plan_builder
    import harness_transaction
    import test_runtime_teamplay
    import shutil

    assert harness_metadata.HARNESS_VERSION == "0.35.0-beta"
    shutil.copytree(tests_root / "fixtures/coordinated-cross-contract", root)
    draft = test_runtime_teamplay.DeterministicPlanBuilderTests()._draft("coordinated-cross-contract-plan.json")
    plan = harness_plan_builder.materialize_plan(draft, root=root)
    harness_apply.apply_application(harness_apply.build_application(root, plan))
    manifest = json.loads((root / ".harness/manifest.json").read_text(encoding="utf-8"))
    runtime = test_runtime_teamplay.valid_plan(root, manifest)
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    # The new CLI removal journal reserves the existing blocker path without
    # claiming to implement the old generation transaction's Schema 2.
    journal = root / ".harness/transaction.json"
    removal_root = root / ".harness/removals"
    backup_root = removal_root / ("a" * 32)
    backup_root.mkdir(parents=True)
    backup = backup_root / "original.bin"
    backup.write_bytes(b"old recovery must preserve this removal backup")
    journal.write_text(json.dumps({"operation": "remove", "removalSchemaVersion": 1,
                                   "runtime": "codex", "id": "a" * 32,
                                   "state": "preparing", "operations": []}), encoding="utf-8")
    before = state(root)
    for action in (lambda: harness_apply.build_application(root, plan),
                   lambda: harness_transaction.recover_transaction(root)):
        try:
            action()
        except harness_transaction.TransactionError:
            pass
        else:
            raise AssertionError("Old apply/recovery must refuse an independent CLI removal journal")
        assert state(root) == before, "Old apply/recovery changed removal journal, backups, or project files"
    journal.unlink()
    backup.unlink()
    backup_root.rmdir()
    removal_root.rmdir()
    return {"generatorVersion": manifest["generator"]["version"], "runtimePlanCreated": True,
            "oldApplyAndRecoveryRefuseRemovalJournalWithoutWrites": True}


def verify(baseline):
    baseline_before = state(baseline)
    package_spec = importlib.util.spec_from_file_location(
        "_old_harness_cli", baseline / "harness_cli/__init__.py",
        submodule_search_locations=[str(baseline / "harness_cli")])
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_spec.name] = package
    package_spec.loader.exec_module(package)
    spec = importlib.util.spec_from_file_location("_old_harness_cli.distribution", baseline / "harness_cli/distribution.py")
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    old_snapshot = old._snapshot(baseline)
    new_snapshot = current._snapshot(REPO)
    baseline_version = old._source_info(old_snapshot)[0]
    assert current._source_info(old_snapshot)[0] == baseline_version, "Complete historical module layouts must remain readable"
    candidate_version = current._source_info(new_snapshot)[0]
    assert baseline_version == "0.35.0-beta"
    assert candidate_version == "0.35.1-beta"
    optional_installers = {"install.sh", "install.ps1", "install_harness.sh", "install_harness_codex.sh", "install_harness_codex.ps1"}
    retired_installers = optional_installers & (old_snapshot.keys() - new_snapshot.keys())
    assert "install_harness.sh" not in new_snapshot
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
        git("init", "--quiet", "--initial-branch=v" + baseline_version)
        git("config", "core.autocrlf", "false")
        git("add", "--all")
        git("-c", "user.name=Harness fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Real v" + baseline_version + " runtime")
        previous_commit = git("rev-parse", "HEAD").strip()
        with mock.patch.dict(os.environ, environment, clear=True):
            installed = old.install_tool(upstream, data, binary, python_executable=sys.executable, auto_update="off")
        assert installed["commit"] == previous_commit
        old_release_before = state(Path(installed["sourceRoot"]))
        project_report = json.loads(run([sys.executable, "-B", __file__, "--baseline", baseline, "--project-worker", project, "--runtime", runtime_path], environment=environment))
        assert project_report["generatorVersion"] == baseline_version
        assert project_report["oldApplyAndRecoveryRefuseRemovalJournalWithoutWrites"]
        (project / "user-notes.txt").write_bytes(b"Preserve the user's own work.\r\n")
        run(["git", "init", "--quiet", project], environment=environment)
        project_before = state(project)

        if baseline_version != candidate_version:
            git("checkout", "--quiet", "-b", "v" + candidate_version)
        populate(new_snapshot, old_snapshot)
        git("add", "--all")
        git("-c", "user.name=Harness fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Real v" + candidate_version + " runtime")
        next_commit = git("rev-parse", "HEAD").strip()
        real_git = current._git
        calls = []

        def local_transport(arguments, **kwargs):
            calls.append(list(arguments))
            for argument in arguments:
                if argument.startswith(("https://", "http://", "ssh://", "git@")):
                    assert argument in {old.DEFAULT_REPOSITORY, current.DEFAULT_REPOSITORY}, "Unexpected network destination in fixture"
            rewritten = [str(upstream) if argument in {old.DEFAULT_REPOSITORY, current.DEFAULT_REPOSITORY} else argument for argument in arguments]
            # This allowance exists only in the injected test transport.
            return real_git(["-c", "protocol.file.allow=always", *rewritten], **kwargs)

        # Execute the immediately preceding updater itself, including discovery.
        # Both versions already use the canonical Harness-Codex repository.
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(old, "_git", side_effect=local_transport):
            legacy_check = old.check_update(data)
            assert legacy_check['updateAvailable'] and legacy_check['availableCommit'] == next_commit
            updated = old.update_tool(data)
        assert updated["updated"] and updated["installation"]["commit"] == next_commit
        active = current.installed_status(data)
        active_root = Path(active["sourceRoot"])
        assert active["version"] == candidate_version
        for name in retired_installers:
            assert not (active_root / name).exists(), "Retired optional installer leaked into the new runtime"
        assert state(Path(installed["sourceRoot"])) == old_release_before
        launcher = data / "launcher.py"
        legacy_launcher_before = launcher.read_bytes()
        legacy_tool_before = state(data)
        legacy_status = current.launcher_status(data)
        migration_required = baseline_version in {"9.2", "9.3", "9.4"}
        assert legacy_status["state"] == ("legacy" if migration_required else "current"), legacy_status
        assert legacy_status["callerEnvironmentPreserved"] is not migration_required, legacy_status
        version = run([sys.executable, "-B", launcher, "--version"], cwd=project, environment=environment).strip()
        assert version == "Harness for Codex " + candidate_version, version
        for option in ("--agent", "--runtime"):
            selected = run([sys.executable, "-B", launcher, option, "codex", "--version"], cwd=project, environment=environment).strip()
            assert selected == version, "The new agent option and legacy runtime alias must both work after upgrade"
        doctor = json.loads(run([sys.executable, "-B", launcher, "doctor", "--json", "--project", project], environment=environment))
        assert doctor["valid"] and doctor["installationStatus"] == "valid", doctor
        status = json.loads(run([sys.executable, "-B", launcher, "status", "--json", "--project", project], environment=environment))
        assert status["state"] == "configured" and status["harnessPresent"], status
        removal_output = run([sys.executable, "-B", launcher, "remove", "--json", "--project", project], environment=environment)
        removal, _ = json.JSONDecoder().raw_decode(removal_output)
        assert removal["valid"] and removal["dryRun"] and removal["writes"] == 0 and removal["actions"], removal
        reset_output = run([sys.executable, "-B", launcher, "reset", "--json", "--project", project, "--dry-run"], environment=environment)
        reset, _ = json.JSONDecoder().raw_decode(reset_output)
        assert reset["operation"] == "reset" and reset["dryRun"] and reset["removal"]["valid"], reset
        assert state(data) == legacy_tool_before, "Read-only commands implicitly migrated the legacy launcher"
        repair_output = run([sys.executable, "-B", launcher, "update", "--json", "--repair-launcher"], environment=environment)
        repair, _ = json.JSONDecoder().raw_decode(repair_output)
        if migration_required:
            assert repair["state"] == "repaired" and repair["repaired"], repair
            assert launcher.read_bytes() != legacy_launcher_before
        else:
            assert repair["state"] == "unchanged" and repair["writes"] == 0, repair
            assert launcher.read_bytes() == legacy_launcher_before
        assert current.launcher_status(data)["callerEnvironmentPreserved"]
        repaired_tool = state(data)
        repeat_output = run([sys.executable, "-B", launcher, "update", "--json", "--repair-launcher"], environment=environment)
        repeat, _ = json.JSONDecoder().raw_decode(repeat_output)
        assert repeat["state"] == "unchanged" and repeat["writes"] == 0, repeat
        assert state(data) == repaired_tool, "Repeated launcher migration was not a no-op"
        assert state(Path(installed["sourceRoot"])) == old_release_before
        runtime = json.loads(run([sys.executable, "-B", active_root / ".agents/skills/harness/scripts/validate_runtime_plan.py",
                                  "--root", project, "--plan", runtime_path], environment=environment))
        assert runtime["valid"], runtime
        assert state(project) == project_before, "Tool update or validation changed project files/Git metadata"
        baseline_after = state(baseline)
        changed = sorted(name for name in baseline_before.keys() | baseline_after.keys()
                         if baseline_before.get(name) != baseline_after.get(name))
        assert not changed, "Original baseline source was modified: " + ", ".join(changed[:10])
        assert any("fetch" in command and command[-1] == next_commit for command in calls)
        return {"status": "passed", "baselineVersion": baseline_version, "candidateVersion": candidate_version,
                "baselineRuntimeTreeSha256": old._tree_hash(old._hashes(old_snapshot)),
                "candidateRuntimeTreeSha256": current._tree_hash(current._hashes(new_snapshot)),
                "oldInstallerAndDiscoveryExecuted": True, "previousUpdaterExecuted": True,
                "legacyUpdaterRequiresOneTimeReinstall": False, "realLocalGitFetchAndAncestry": True,
                "newLauncherVersion": version, "retiredOptionalInstallersRemoved": sorted(retired_installers),
                "newAgentOptionAndLegacyRuntimeAliasAccepted": True,
                "oldApplyAndRecoveryRefuseRemovalJournalWithoutWrites": True,
                "newInstalledStatusAndRemovalPreviewAcceptPreviousProject": True,
                "resetPreviewAcceptedWithoutWrites": True, "legacyReadOnlyCommandsDoNotMigrate": True,
                "legacyLauncherMigrationRequired": migration_required,
                "offlineLauncherMigrationAndNoopRepeat": migration_required,
                "offlineLauncherRepairCheckAndNoopRepeat": True,
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
