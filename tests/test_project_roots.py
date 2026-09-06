from __future__ import annotations

import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"))

import harness_topology
import inventory
from test_harness_tools import minimal_plan


def write(root: Path, relative: str, text: str = "fixture\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ProjectRootTests(unittest.TestCase):
    def test_selected_directory_does_not_require_a_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            root = parent / "project"
            root.mkdir()
            for containing, expected in (
                (None, "plain-directory"),
                (parent, "git-contained-directory"),
            ):
                with self.subTest(kind=expected), mock.patch.object(
                    inventory, "_containing_git_root", return_value=containing
                ):
                    report = inventory.require_workspace_root(root)
                    self.assertEqual(report["workspaceKind"], expected)
                    self.assertFalse(report["rootSelectionRequired"])
                    self.assertEqual(report["scanCompleteness"]["status"], "scanned")

    @unittest.skipUnless(shutil.which("git"), "Git is unavailable")
    def test_real_git_subdirectory_and_nested_repository_remain_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            selected = root / "project"
            nested = selected / "nested"
            nested.mkdir(parents=True)
            for git_root in (root, nested):
                subprocess.run(
                    ["git", "-C", str(git_root), "init", "--quiet"],
                    check=True, capture_output=True, text=True,
                )
            write(nested, "src/module.py", "value = 1\n")
            for selected_root, expected_kind in (
                (root, "git-repository"),
                (selected, "git-contained-directory"),
                (nested, "git-repository"),
            ):
                with self.subTest(root=selected_root):
                    report = inventory.require_workspace_root(selected_root)
                    self.assertEqual(report["workspaceKind"], expected_kind)
                    self.assertFalse(report["rootSelectionRequired"])
            self.assertEqual(inventory.build_inventory(selected, 50)["fileCount"], 1)

    def test_nested_repositories_include_code_and_deeper_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("repo-a", "repo-a/deeper", "repo-b"):
                write(root, f"{relative}/.git/config", "metadata must not count\n")
            write(root, "README.md")
            write(root, "repo-a/pyproject.toml", "[project]\nname = 'a'\n")
            write(root, "repo-a/deeper/tests/test_model.py", "assert True\n")
            write(root, "repo-b/src/module.py", "value = 1\n")
            write(root, "repo-b/.github/workflows/check.yml", "name: fixture\n")
            result = inventory.build_inventory(root, 50)
            self.assertEqual(result["fileCount"], 5)
            self.assertEqual(result["manifests"], ["repo-a/pyproject.toml"])
            self.assertEqual(result["tests"], ["repo-a/deeper/tests/test_model.py"])
            self.assertEqual(result["ci"], ["repo-b/.github/workflows/check.yml"])
            self.assertEqual(
                [item["path"] for item in result["nestedRepositories"]],
                ["repo-a", "repo-a/deeper", "repo-b"],
            )
            boundaries = {item["path"]: item for item in result["candidateBoundaries"]}
            self.assertEqual(boundaries["repo-a"]["fileCount"], 2)
            self.assertEqual(boundaries["repo-a/deeper"]["fileCount"], 1)
            self.assertEqual(boundaries["repo-a/deeper"]["fileRoles"]["test"], 1)
            self.assertEqual(boundaries["repo-b"]["boundaryKind"], "independent-repository")
            self.assertFalse(result["rootSelectionRequired"])

    def test_truncated_scan_does_not_replace_git_classification_or_reject_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / ".git").mkdir()
            (root / "src" / "deeper").mkdir(parents=True)
            with mock.patch.object(inventory, "_containing_git_root", return_value=root):
                report = inventory.inspect_root_context(root, max_directories=1)
            self.assertEqual(report["workspaceKind"], "git-repository")
            self.assertEqual(report["scanCompleteness"]["status"], "truncated")
            self.assertTrue(report["scanTruncated"])
            self.assertEqual(report["scanCompleteness"]["scannedDirectories"], 1)
            self.assertFalse(report["rootSelectionRequired"])
            with mock.patch.object(inventory, "inspect_root_context", return_value=report):
                self.assertEqual(inventory.require_workspace_root(root), report)

    def test_unreadable_scan_is_reported_without_changing_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()

            def interrupted_walk(path: Path, *, followlinks: bool, onerror: object):
                onerror(PermissionError(13, "denied", str(root / "unreadable")))
                yield str(path), [], []

            with mock.patch.object(inventory.os, "walk", side_effect=interrupted_walk), mock.patch.object(
                inventory, "_containing_git_root", return_value=None
            ):
                report = inventory.require_workspace_root(root)
            self.assertEqual(report["workspaceKind"], "plain-directory")
            self.assertEqual(report["scanCompleteness"]["status"], "unknown")
            self.assertEqual(report["scanCompleteness"]["unreadableDirectories"], ["unreadable"])
            self.assertFalse(report["rootSelectionRequired"])

    def test_missing_or_file_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, "file.txt")
            for selected in (root / "missing", root / "file.txt"):
                with self.subTest(path=selected), self.assertRaisesRegex(ValueError, "not a directory"):
                    inventory.require_workspace_root(selected)
            self.assertTrue(inventory.inspect_root_context(root / "missing")["rootSelectionRequired"])

    def test_git_metadata_cannot_be_selected_as_the_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (".git", ".git/objects", "nested/.GIT/info"):
                selected = root / relative
                selected.mkdir(parents=True, exist_ok=True)
                with self.subTest(root=relative), mock.patch.object(
                    inventory, "inspect_root_context"
                ) as inspect:
                    with self.assertRaisesRegex(ValueError, "inside Git metadata"):
                        inventory.require_workspace_root(selected)
                    with self.assertRaisesRegex(ValueError, "inside Git metadata"):
                        inventory.build_inventory(selected, 50)
                    inspect.assert_not_called()

    def test_root_resolving_into_git_metadata_is_rejected_before_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "linked"
            destination = Path(directory) / ".git" / "objects"
            with mock.patch.object(Path, "resolve", return_value=destination), mock.patch.object(
                inventory, "inspect_root_context"
            ) as inspect:
                with self.assertRaisesRegex(ValueError, "resolve inside Git metadata"):
                    inventory.require_workspace_root(selected)
                inspect.assert_not_called()

    def test_local_generator_and_state_do_not_count_as_project_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            excluded = (
                ".agents/skills/harness",
                ".harness",
                "repo/.agents/skills/harness",
                "repo/.harness",
            )
            for relative in excluded:
                write(root, f"{relative}/pyproject.toml")
                write(root, f"{relative}/nested/.git/config")
            write(root, "repo/.git/config")
            write(root, "repo/src/project.py", "value = 1\n")
            write(root, ".agents/skills/user-skill/SKILL.md")
            result = inventory.build_inventory(root, 100, include_artifacts=True)
            self.assertEqual(result["fileCount"], 2)
            self.assertEqual(result["manifests"], [])
            self.assertEqual([item["path"] for item in result["nestedRepositories"]], ["repo"])
            self.assertEqual({item["path"] for item in result["excludedByPolicy"]}, set(excluded))
            root_exclusions = result["rootContext"]["scanCompleteness"]["excludedByPolicy"]
            self.assertTrue(set(excluded).issubset({item["path"] for item in root_exclusions}))

    def test_inventory_does_not_follow_file_or_directory_links_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "selected"
            outside = parent / "outside"
            root.mkdir()
            write(outside, "pyproject.toml")
            write(outside, ".git/config")
            try:
                (root / "linked-directory").symlink_to(outside, target_is_directory=True)
                (root / "linked-file.py").symlink_to(outside / "pyproject.toml")
            except OSError as exc:
                self.skipTest(f"symbolic link creation is unavailable: {exc}")
            result = inventory.build_inventory(root, 100)
            self.assertEqual(result["fileCount"], 0)
            self.assertEqual(result["nestedRepositories"], [])
            self.assertEqual(result["manifests"], [])
            for topology in (
                {"boundaries": [{"readScopes": ["linked-directory/**"]}]},
                {"boundaries": [{"writeScopes": ["linked-directory/new/file.py"]}]},
                {"agents": [{"fileAccess": [{"scope": "linked-file.py"}]}]},
                {"handoffs": [{"scope": "linked-directory/new/**"}]},
            ):
                with self.subTest(topology=topology), self.assertRaisesRegex(
                    harness_topology.TopologyError, "symlink or reparse point"
                ):
                    harness_topology.validate_scope_paths(root, topology)


class ProjectScopeTests(unittest.TestCase):
    def test_scope_paths_accept_multiple_repositories_and_missing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, "repo-a/.git/config")
            write(root, "repo-b/.git/config")
            write(root, "repo-b/src/module.py")
            topology = {
                "boundaries": [{"readScopes": ["repo-b/src/**"], "writeScopes": ["repo-a/new/**"]}],
                "agents": [{"fileAccess": [{"scope": "repo-a/new/file.py"}]}],
                "handoffs": [{"scope": "repo-b/src/module.py"}],
            }
            harness_topology.validate_scope_paths(root, topology)
            self.assertFalse((root / "repo-a" / "new").exists())

    def test_scope_paths_reject_a_file_used_as_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, "file.py")
            for scope in ("file.py/new.py", "file.py/**"):
                with self.subTest(scope=scope), self.assertRaisesRegex(
                    harness_topology.TopologyError, "non-directory"
                ):
                    harness_topology.validate_scope_paths(
                        root, {"boundaries": [{"writeScopes": [scope]}]}
                    )

    def test_scopes_allow_multiple_repositories_and_reject_git_metadata(self) -> None:
        for scope in ("repo-a/src/**", "repo-b/src/model.py", "repo-a/deeper/tests/**"):
            with self.subTest(scope=scope):
                harness_topology.normalize_scope(scope, "scope")
        for scope in (".git/**", "repo-a/.git/config", "repo-b/.GIT/**"):
            with self.subTest(scope=scope), self.assertRaisesRegex(
                harness_topology.TopologyError, "Git metadata"
            ):
                harness_topology.normalize_scope(scope, "scope")

    def test_scopes_reject_absolute_and_parent_paths(self) -> None:
        for scope in ("../src/**", "/tmp/src/**", "repo/../other/**", "C:/outside/**", "C:outside"):
            with self.subTest(scope=scope), self.assertRaises(harness_topology.TopologyError):
                harness_topology.normalize_scope(scope, "scope")

    def test_generated_skill_cannot_claim_generator_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            for name in ("harness", "HARNESS"):
                topology = copy.deepcopy(plan["topology"])
                topology["skills"][0]["name"] = name
                with self.subTest(name=name), self.assertRaisesRegex(
                    harness_topology.TopologyError, "reserved.*generator"
                ):
                    harness_topology.validate_contract(topology, plan["capabilityPolicies"])


if __name__ == "__main__":
    unittest.main()
