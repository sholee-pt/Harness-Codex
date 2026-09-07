from __future__ import annotations

import copy
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness_apply  # noqa: E402
import harness_agent_contract
import harness_change_discipline  # noqa: E402
import harness_metadata  # noqa: E402
import harness_plan_builder  # noqa: E402
import harness_state  # noqa: E402
import harness_teamplay  # noqa: E402
import harness_topology  # noqa: E402
import harness_transaction  # noqa: E402
import harness_workspace  # noqa: E402
import evaluate_topology  # noqa: E402
import inventory  # noqa: E402
import validate_harness  # noqa: E402


def minimal_plan(root: Path, *, skill_suffix: str = "", skill_mode: str = "0644") -> dict:
    evidence_path = root / "pyproject.toml"
    if not evidence_path.exists():
        evidence_path.write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    evidence = {
        "path": "pyproject.toml",
        "sha256": harness_state.digest_bytes(evidence_path.read_bytes()),
        "claim": "Defines the fixture project boundary.",
        "lines": {"start": 1, "end": 2},
    }
    skill_content = (
        "---\n"
        "name: project-harness\n"
        "description: Coordinate fixture work when repository-wide routing is needed.\n"
        "---\n\n"
        "# Project Harness\n\n"
        "Run the smallest evidence-backed workflow.\n"
        f"\n{harness_change_discipline.PROJECT_BLOCK}\n"
        f"\n{harness_teamplay.PROJECT_BLOCK}\n"
        f"{skill_suffix}"
    )
    return {
        "schemaVersion": 3,
        "artifactContractVersion": harness_metadata.ARTIFACT_CONTRACT_VERSION,
        "project": {
            "summary": "Fixture project",
            "evidence": [evidence],
            "rationale": {
                "summary": "The project is small, so only the orchestrator is justified.",
                "uncertainties": [],
            },
        },
        "topology": {
            "classification": {
                "class": "minimal",
                "materialBoundaryCount": 1,
                "dependencyShape": "independent",
                "recurringCoordination": False,
                "coordinationReasons": [],
                "rationale": "One persistent decision boundary requires no recurring coordination.",
                "mergedCandidates": [],
                "uncertainties": [],
            },
            "boundaries": [
                {
                    "id": "project-core",
                    "name": "Project core",
                    "types": ["responsibility"],
                    "summary": "Owns the fixture's single project responsibility.",
                    "evidence": [evidence],
                    "decisionAreaIds": ["project-core"],
                    "inputs": ["user request"],
                    "outputs": ["verified project change"],
                    "contracts": [],
                    "readScopes": ["pyproject.toml"],
                    "writeScopes": [],
                    "verification": ["project-native tests"],
                    "failureImpact": "The requested project change may be incorrect.",
                    "persistence": {
                        "kind": "stable-structure",
                        "evidence": [evidence],
                    },
                    "separationBenefits": {
                        "specializedJudgment": False,
                        "parallelizable": False,
                        "contextIsolation": False,
                        "reusable": True,
                        "independentReview": False,
                    },
                    "dependsOn": [],
                    "interactsWith": [],
                    "overlapWith": [],
                }
            ],
            "collaborationPatterns": [],
            "qualityPatternPolicies": [],
            "agents": [],
            "skills": [
                {
                    "name": "project-harness",
                    "path": ".agents/skills/project-harness/SKILL.md",
                    "purpose": "Coordinate repository-wide fixture work.",
                    "evidence": [evidence],
                    "scope": "project",
                    "boundaryRefs": [],
                }
            ],
            "routingPolicies": [],
            "executionPhases": [],
            "handoffs": [],
        },
        "capabilityPolicies": [
            {
                "id": "direct-default",
                "semanticMode": "direct-execution",
                "requiredCapabilities": [],
                "preferredRuntimeMapping": "instruction-driven",
                "reason": "The minimal topology does not require runtime orchestration primitives.",
            }
        ],
        "artifacts": [
            {
                "path": ".agents/skills/project-harness/SKILL.md",
                "mode": skill_mode,
                "content": skill_content,
            }
        ],
        "instruction": {
            "managedBlock": (
                "<!-- harness:begin -->\n"
                "## Project Harness\n\n"
                "Use the `$project-harness` skill for coordinated fixture work.\n"
                "<!-- harness:end -->"
            )
        },
    }


class InventoryTests(unittest.TestCase):
    def test_inventory_is_bounded_and_ignores_dependencies_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "package.json").write_text("{}\n", encoding="utf-8")
            (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "index.js").write_text("ignored\n", encoding="utf-8")

            result = inventory.build_inventory(root, max_files=10)

            self.assertEqual(result["fileCount"], 2)
            self.assertEqual(result["sensitiveFilesSkipped"], 1)
            self.assertEqual(result["manifests"], ["package.json"])
            self.assertNotIn("node_modules", result["topLevel"])

    def test_inventory_reports_active_root_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("base\n", encoding="utf-8")
            (root / "AGENTS.override.md").write_text("override\n", encoding="utf-8")

            result = inventory.build_inventory(root, max_files=10)

            self.assertEqual(result["existingActiveRootInstruction"], "AGENTS.override.md")
            self.assertEqual(result["plannedRootInstruction"], "AGENTS.override.md")
            self.assertEqual(result["instructions"], ["AGENTS.md", "AGENTS.override.md"])

    def test_inventory_distinguishes_missing_instruction_from_planned_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = inventory.build_inventory(Path(directory), max_files=10)

            self.assertIsNone(result["existingActiveRootInstruction"])
            self.assertEqual(result["plannedRootInstruction"], "AGENTS.md")

    def test_inventory_reports_conda_nested_repositories_and_research_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / "environment.yml").write_text("name: fixture\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "model.py").write_text("MODEL = True\n", encoding="utf-8")
            (root / "model.pt").write_bytes(b"checkpoint")
            (root / "data").mkdir()
            (root / "data" / "large.npy").write_bytes(b"array")
            (root / "vendor-project" / ".git").mkdir(parents=True)
            (root / "vendor-project" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

            result = inventory.build_inventory(root, max_files=20)

            self.assertEqual(result["schemaVersion"], harness_metadata.INVENTORY_SCHEMA_VERSION)
            self.assertEqual(result["rootGitState"], "directory")
            self.assertFalse(result["rootSelectionRequired"])
            self.assertEqual(result["workspaceKind"], "git-repository")
            self.assertEqual(result["rootContext"]["scanCompleteness"]["status"], "scanned")
            self.assertEqual(
                result["nestedRepositories"],
                [
                    {
                        "path": "vendor-project",
                        "markerType": "directory",
                        "kind": "independent-repository",
                    }
                ],
            )
            self.assertIn("environment.yml", result["manifests"])
            self.assertEqual(result["artifactFileCount"], 1)
            self.assertEqual(result["nonArtifactFileCount"], 3)
            self.assertNotIn("sourceFileCount", result)
            self.assertEqual(result["fileRoleSummary"]["code"], 2)
            self.assertEqual(result["fileRoleSummary"]["config"], 1)
            self.assertEqual(result["fileRoleSummary"]["research-artifact"], 1)
            self.assertEqual(result["artifactSummary"]["excludedDirectories"], ["data"])
            self.assertEqual(result["artifactSummary"]["extensions"], {".pt": 1})
            boundaries = {item["path"]: item["fileCount"] for item in result["candidateBoundaries"]}
            self.assertEqual(boundaries["src"], 1)
            self.assertEqual(boundaries["vendor-project"], 1)

    def test_inventory_does_not_treat_registered_submodule_as_root_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / "dependency" / ".git").mkdir(parents=True)
            with mock.patch.object(
                inventory, "_classify_nested_repository", return_value="submodule"
            ):
                context = inventory.inspect_root_context(root)

            self.assertFalse(context["rootSelectionRequired"])
            self.assertEqual(context["nestedRepositories"][0]["kind"], "submodule")

    def test_inventory_recognizes_an_actual_registered_submodule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            child = parent / "child-source"
            root = parent / "project"
            subprocess.run(["git", "init", str(child)], check=True, capture_output=True)
            (child / "README.md").write_text("child\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(child), "add", "README.md"], check=True, capture_output=True)
            subprocess.run(
                [
                    "git", "-C", str(child), "-c", "user.name=Harness Tests",
                    "-c", "user.email=harness@example.invalid", "commit", "-m", "child",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "protocol.file.allow=always",
                    "submodule", "add", str(child), "dependency",
                ],
                check=True,
                capture_output=True,
            )

            context = inventory.require_workspace_root(root)

            self.assertEqual(context["workspaceKind"], "git-repository")
            self.assertFalse(context["rootSelectionRequired"])
            self.assertEqual(context["nestedRepositories"][0]["kind"], "submodule")

    def test_plain_directory_workspace_keeps_nested_git_roots_as_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "vendor" / "nested" / ".git").mkdir(parents=True)
            (root / "node_modules" / "package" / ".git").mkdir(parents=True)

            context = inventory.require_workspace_root(root)

            self.assertEqual(context["workspaceKind"], "directory-workspace")
            self.assertFalse(context["rootSelectionRequired"])
            self.assertEqual(
                [item["path"] for item in context["nestedRepositories"]],
                ["node_modules/package", "vendor/nested"],
            )
            result = inventory.build_inventory(root, max_files=10)
            repository_boundaries = [
                item["path"]
                for item in result["candidateBoundaries"]
                if item["analysisPriority"] == "repository-boundary"
            ]
            self.assertEqual(repository_boundaries, ["node_modules/package", "vendor/nested"])

    def test_root_scan_reports_truncation_instead_of_claiming_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one" / "two").mkdir(parents=True)

            context = inventory.inspect_root_context(root, max_directories=1)

            self.assertEqual(context["workspaceKind"], "plain-directory")
            self.assertEqual(context["scanCompleteness"]["status"], "truncated")
            self.assertFalse(context["rootSelectionRequired"])

    def test_inventory_excludes_nested_output_directories_from_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "benchmark" / "script").mkdir(parents=True)
            (root / "benchmark" / "script" / "run.py").write_text(
                "print('run')\n", encoding="utf-8"
            )
            (root / "benchmark" / "output").mkdir()
            (root / "benchmark" / "output" / "scores.csv").write_text(
                "score\n1\n", encoding="utf-8"
            )

            result = inventory.build_inventory(root, max_files=10)

            self.assertIn("benchmark/output", result["artifactSummary"]["excludedDirectories"])
            boundary = next(
                item for item in result["candidateBoundaries"] if item["path"] == "benchmark"
            )
            self.assertEqual(boundary["fileCount"], 1)
            self.assertEqual(boundary["fileRoles"]["code"], 1)

    def test_inventory_can_include_excluded_artifact_directories_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "checkpoints").mkdir()
            (root / "checkpoints" / "model.ckpt").write_bytes(b"checkpoint")

            result = inventory.build_inventory(root, max_files=10, include_artifacts=True)

            self.assertTrue(result["artifactSummary"]["included"])
            self.assertEqual(result["artifactFileCount"], 1)
            self.assertEqual(result["artifactSummary"]["excludedDirectories"], [])


class StateTests(unittest.TestCase):
    def test_resolve_inside_normalizes_the_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            (root / "evidence.txt").write_text("evidence\n", encoding="utf-8")
            resolved = harness_state.resolve_inside(
                root, "evidence.txt", must_exist=True
            )

            self.assertEqual(resolved, (root / "evidence.txt").resolve())
            self.assertEqual(
                harness_state.normalize_relative(root, "evidence.txt"),
                "evidence.txt",
            )

    def test_resolve_inside_accepts_a_relative_repository_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            absolute_root = Path(directory) / "repository"
            absolute_root.mkdir()
            (absolute_root / "evidence.txt").write_text("evidence\n", encoding="utf-8")
            relative_root = Path(os.path.relpath(absolute_root, Path.cwd()))

            resolved = harness_state.resolve_inside(
                relative_root, "evidence.txt", must_exist=True
            )

            self.assertEqual(resolved, (absolute_root / "evidence.txt").resolve())
            self.assertEqual(
                harness_state.normalize_relative(relative_root, "evidence.txt"),
                "evidence.txt",
            )

    def test_record_status_and_rebaseline_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "generated.txt").write_text("stable\n", encoding="utf-8")
            (root / "AGENTS.md").write_text(
                "User content\n\n<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n",
                encoding="utf-8",
            )
            self.write_manifest(root, schema_version=4)

            harness_state.record_manifest(root, ["generated.txt"], ["AGENTS.md"])
            clean = harness_state.status_report(root)
            self.assertEqual(clean["counts"], {"unchanged": 2})

            with self.assertRaises(harness_state.StateError):
                harness_state.record_manifest(root, ["generated.txt"], ["AGENTS.md"])

            (root / "generated.txt").write_text("user edit\n", encoding="utf-8")
            modified = harness_state.status_report(root)
            self.assertEqual(modified["counts"], {"unchanged": 1, "modified": 1})

    def test_schema_v1_migration_preserves_clean_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "AGENTS.md").write_text(
                "<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n", encoding="utf-8"
            )
            self.write_manifest(root, schema_version=1)
            harness_state.record_manifest(root, [], ["AGENTS.md"])

            migrated = harness_state.migrate_manifest(root)

            self.assertEqual(migrated["schemaVersion"], 4)
            self.assertEqual(migrated["instructionFile"], "AGENTS.md")
            self.assertIn("rationale", migrated["project"])
            self.assertEqual(migrated["application"]["mode"], "journaled")
            self.assertEqual(harness_state.status_report(root)["counts"], {"unchanged": 1})

    def test_schema_v2_migration_adds_journaled_application_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "AGENTS.md").write_text(
                "<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n", encoding="utf-8"
            )
            self.write_manifest(root, schema_version=2)
            harness_state.record_manifest(root, [], ["AGENTS.md"])

            migrated = harness_state.migrate_manifest(root)

            self.assertEqual(migrated["schemaVersion"], 4)
            self.assertEqual(migrated["generator"]["version"], "4.0")
            self.assertEqual(
                migrated["application"],
                {"mode": "journaled", "transactionSchemaVersion": 2},
            )
            self.assertEqual(harness_state.status_report(root)["counts"], {"unchanged": 1})

            application = harness_apply.build_application(root, minimal_plan(root))
            transaction = harness_apply.apply_application(application)

            self.assertEqual(transaction["state"], "committed")
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_schema_v3_migration_structures_evidence_and_records_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "AGENTS.md").write_text(
                "<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n", encoding="utf-8"
            )
            (root / "generated.txt").write_text("stable\n", encoding="utf-8")
            self.write_manifest(root, schema_version=3)
            harness_state.record_manifest(root, ["generated.txt"], ["AGENTS.md"])

            migrated = harness_state.migrate_manifest(root)

            self.assertEqual(migrated["schemaVersion"], 4)
            self.assertIsInstance(migrated["project"]["evidence"][0], dict)
            self.assertEqual(migrated["application"]["transactionSchemaVersion"], 2)
            generated = next(
                item for item in migrated["managedFiles"] if item["path"] == "generated.txt"
            )
            self.assertRegex(generated["mode"], r"^0[0-7]{3}$")

    def test_schema_v4_state_upgrades_only_through_a_schema_v3_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "AGENTS.md").write_text(
                "<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n", encoding="utf-8"
            )
            self.write_manifest(root, schema_version=4)
            harness_state.record_manifest(root, [], ["AGENTS.md"])

            unchanged = harness_state.migrate_manifest(root)
            self.assertEqual(unchanged["schemaVersion"], 4)

            harness_apply.apply_application(
                harness_apply.build_application(root, minimal_plan(root))
            )
            upgraded = json.loads(
                (root / ".harness" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(upgraded["schemaVersion"], harness_metadata.MANIFEST_SCHEMA_VERSION)
            self.assertEqual(upgraded["topology"]["classification"]["class"], "minimal")

    def test_schema_v4_upgrade_rejects_stale_legacy_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "AGENTS.md").write_text(
                "<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n", encoding="utf-8"
            )
            self.write_manifest(root, schema_version=4)
            harness_state.record_manifest(root, [], ["AGENTS.md"])
            (root / "pyproject.toml").write_text(
                "[project]\nname = 'changed-before-upgrade'\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(harness_apply.PlanError, "changed after analysis"):
                harness_apply.build_application(root, minimal_plan(root))

    def test_snapshot_detects_post_freeze_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "evidence.json").write_text("{}\n", encoding="utf-8")

            harness_state.write_snapshot(root, ".harness/phase-1.json", ["evidence.json"])
            clean = harness_state.verify_snapshot(root, ".harness/phase-1.json")
            self.assertFalse(harness_state.has_conflict(clean["files"]))

            (root / "evidence.json").write_text('{"changed": true}\n', encoding="utf-8")
            changed = harness_state.verify_snapshot(root, ".harness/phase-1.json")
            self.assertTrue(harness_state.has_conflict(changed["files"]))

    def test_orphaned_transaction_workspace_blocks_new_plans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness" / "transactions" / "orphan").mkdir(parents=True)

            status = harness_state.status_report(root)

            self.assertEqual(status["transaction"]["state"], "orphaned-workspace")
            with self.assertRaises(harness_transaction.TransactionError):
                harness_apply.build_application(root, minimal_plan(root))

            inspection = harness_transaction.inspect_transaction(root)
            self.assertEqual(inspection["workspaces"], ["orphan"])
            self.assertTrue(inspection["cleanupAllowed"])
            cleanup = harness_transaction.clean_orphaned_workspace(root)
            self.assertTrue(cleanup["cleaned"])
            self.assertIsNone(harness_state.transaction_status(root))
            harness_apply.build_application(root, minimal_plan(root))

    def test_evidence_hash_drift_rejects_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            (root / "pyproject.toml").write_text("[project]\nname = 'changed'\n", encoding="utf-8")

            with self.assertRaises(harness_apply.PlanError):
                harness_apply.build_application(root, plan)

    def test_evidence_cannot_be_a_planned_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            output = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            output.parent.mkdir(parents=True)
            output.write_text("preexisting evidence\n", encoding="utf-8")
            evidence = {
                "path": ".agents/skills/project-harness/SKILL.md",
                "sha256": harness_state.digest_bytes(output.read_bytes()),
                "claim": "Must not justify its own generated replacement.",
            }
            plan["project"]["evidence"] = [evidence]
            plan["topology"]["skills"][0]["evidence"] = [evidence]

            with self.assertRaisesRegex(harness_apply.PlanError, "cannot also be planned outputs"):
                harness_apply.build_application(root, plan)

    def test_evidence_rejects_reserved_control_namespaces_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (".git/config", ".GIT/config", ".harness/manifest.json"):
                with self.subTest(relative=relative):
                    with self.assertRaisesRegex(
                        harness_apply.PlanError, "reserved control namespace"
                    ):
                        harness_apply.validate_evidence(
                            root,
                            [
                                {
                                    "path": relative,
                                    "sha256": "0" * 64,
                                    "claim": "Must be rejected without reading control metadata.",
                                }
                            ],
                            "project.evidence",
                        )

    def test_configured_instruction_fallback_is_preserved_as_explicit_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / ".codex" / "config.toml"
            config.parent.mkdir(parents=True)
            config.write_text(
                'project_doc_fallback_filenames = ["PROJECT_GUIDE.md"]\n',
                encoding="utf-8",
            )
            (root / "PROJECT_GUIDE.md").write_text(
                "# Existing project instructions\n", encoding="utf-8"
            )

            application = harness_apply.build_application(root, minimal_plan(root))

            self.assertEqual(
                application["report"]["workspace"]["instructionMode"],
                "explicit-skill",
            )
            manifest = json.loads(application["manifestText"])
            self.assertIsNone(manifest["instructionFile"])
            self.assertFalse(
                any(
                    item["path"] == "AGENTS.md"
                    for item in application["report"]["actions"]
                )
            )

    def test_atomic_write_requests_parent_directory_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "managed.txt"
            with mock.patch.object(harness_state, "sync_directory", return_value=True) as sync:
                harness_state.atomic_write_bytes(target, b"durable\n")

            self.assertEqual(target.read_bytes(), b"durable\n")
            sync.assert_called_once_with(target.parent)

    @staticmethod
    def write_manifest(root: Path, schema_version: int) -> None:
        evidence_path = root / "pyproject.toml"
        if not evidence_path.exists():
            evidence_path.write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
        legacy_evidence: list[object] = ["pyproject.toml"]
        structured_evidence: list[object] = [
            {
                "path": "pyproject.toml",
                "sha256": harness_state.digest_bytes(evidence_path.read_bytes()),
                "claim": "Defines the fixture project boundary.",
            }
        ]
        evidence = structured_evidence if schema_version >= 4 else legacy_evidence
        manifest = {
            "schemaVersion": schema_version,
            "generator": {"name": "Harness", "version": "1.0.0", "runtime": "codex"},
            "project": {"summary": "Fixture project", "evidence": evidence},
            "topology": {
                "patterns": [],
                "agents": [],
                "skills": [
                    {
                        "name": "project-harness",
                        "path": ".agents/skills/project-harness/SKILL.md",
                        "purpose": "Coordinate fixture work.",
                        "evidence": evidence,
                    }
                ],
            },
            "managedFiles": [],
        }
        if schema_version >= 2:
            manifest["instructionFile"] = "AGENTS.md"
            manifest["project"]["rationale"] = {"summary": "Fixture rationale", "uncertainties": []}
        if schema_version >= 3:
            manifest["application"] = {
                "mode": "journaled",
                "transactionSchemaVersion": 2 if schema_version >= 4 else 1,
            }
        (root / ".harness" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class ApplyTests(unittest.TestCase):
    def test_apply_accepts_nested_repository_inside_selected_git_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            (root / ".git").mkdir()
            (root / "nested-project" / ".git").mkdir(parents=True)

            application = harness_apply.build_application(root, plan)

            self.assertFalse((root / ".harness" / "manifest.json").exists())
            self.assertFalse((root / "AGENTS.md").exists())
            harness_apply.apply_application(application)
            self.assertTrue(validate_harness.Validator(root).run()["valid"])
            self.assertFalse((root / "nested-project" / ".harness").exists())
            self.assertEqual(list((root / ".git").iterdir()), [])

    def test_project_harness_requires_one_canonical_change_discipline_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            content = plan["artifacts"][0]["content"]
            plan["artifacts"][0]["content"] = content.replace(
                harness_change_discipline.PROJECT_BLOCK, "## Change discipline\n\nMarker only."
            )
            with self.assertRaisesRegex(harness_apply.PlanError, "canonical change-discipline"):
                harness_apply.build_application(root, plan)

            plan = minimal_plan(root)
            plan["artifacts"][0]["content"] += "\n" + harness_change_discipline.PROJECT_BLOCK
            with self.assertRaisesRegex(harness_apply.PlanError, "exactly once"):
                harness_apply.build_application(root, plan)

    def test_plan_rejects_case_only_artifact_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan["artifacts"].extend(
                [
                    {
                        "path": ".agents/skills/project-harness/references/API.md",
                        "mode": "0644",
                        "content": "upper\n",
                    },
                    {
                        "path": ".agents/skills/project-harness/references/api.md",
                        "mode": "0644",
                        "content": "lower\n",
                    },
                ]
            )

            with self.assertRaisesRegex(harness_apply.PlanError, "portable path collision"):
                harness_apply.build_application(root, plan)

            self.assertFalse((root / ".harness" / "transaction.json").exists())

    def test_plan_rejects_file_and_child_artifact_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan["artifacts"].extend(
                [
                    {
                        "path": ".agents/skills/project-harness/references",
                        "mode": "0644",
                        "content": "file\n",
                    },
                    {
                        "path": ".agents/skills/project-harness/references/guide.md",
                        "mode": "0644",
                        "content": "child\n",
                    },
                ]
            )

            with self.assertRaisesRegex(harness_apply.PlanError, "file/child path conflict"):
                harness_apply.build_application(root, plan)

            self.assertFalse((root / ".harness" / "transaction.json").exists())

    def test_transaction_rejects_portable_output_collisions_before_journaling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = ".agents/skills/project-harness/references/API.md"
            second = ".agents/skills/project-harness/references/api.md"
            outputs = {first: "upper\n", second: "lower\n"}
            actions = {first: "create", second: "create"}
            modes = {first: 0o644, second: 0o644}

            with self.assertRaisesRegex(
                harness_transaction.TransactionError, "portable path collision"
            ):
                harness_transaction.prepare_transaction(
                    root, outputs, actions, {}, {}, modes, []
                )

            self.assertFalse((root / ".harness" / "transaction.json").exists())

    def test_coordinated_full_plan_round_trip_is_valid_and_idempotent(self) -> None:
        fixture_root = REPO_ROOT / "tests" / "fixtures" / "coordinated-cross-contract"
        plan_path = (
            REPO_ROOT / "tests" / "fixtures" / "coordinated-cross-contract-plan.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(fixture_root, root, dirs_exist_ok=True)
            plan = harness_apply.load_plan(plan_path)
            plan["authoringContractVersion"] = harness_metadata.AUTHORING_CONTRACT_VERSION
            for artifact in plan["artifacts"]:
                if artifact["path"] == ".agents/skills/project-harness/SKILL.md":
                    artifact["content"] += (
                        "\n" + harness_plan_builder.PROJECT_TEAMPLAY_PLACEHOLDER + "\n"
                    )
                elif artifact["path"].startswith(".codex/agents/"):
                    before, closing = artifact["content"].rsplit('"""', 1)
                    artifact["content"] = (
                        before
                        + "\n"
                        + harness_plan_builder.AGENT_TEAMPLAY_PLACEHOLDER
                        + "\n\"\"\""
                        + closing
                    )
            plan = harness_plan_builder.materialize_plan(plan, root=root)

            dry_run = harness_apply.build_application(root, plan)
            self.assertFalse((root / ".harness" / "manifest.json").exists())
            self.assertTrue(
                all(item["action"] == "create" for item in dry_run["report"]["actions"])
            )

            first = harness_apply.apply_application(dry_run)
            self.assertEqual(first["state"], "committed")
            self.assertTrue(validate_harness.Validator(root).run()["valid"])
            self.assertFalse((root / ".harness" / "transaction.json").exists())

            second_application = harness_apply.build_application(root, plan)
            second = harness_apply.apply_application(second_application)
            self.assertEqual(second, {"state": "unchanged", "writes": 0, "cleaned": True})
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_dry_run_is_no_write_and_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)

            application = harness_apply.build_application(root, plan)

            self.assertFalse((root / ".harness" / "manifest.json").exists())
            self.assertTrue(all(item["action"] == "create" for item in application["report"]["actions"]))
            self.assertEqual(
                application["report"]["workspace"]["gitProtection"],
                {"mode": "not-managed", "patterns": []},
            )

            harness_apply.apply_application(application)
            first_manifest = (root / ".harness" / "manifest.json").read_bytes()
            second = harness_apply.build_application(root, plan)
            self.assertTrue(all(item["action"] == "unchanged" for item in second["report"]["actions"]))
            with mock.patch.object(
                harness_state, "atomic_write_bytes", wraps=harness_state.atomic_write_bytes
            ) as atomic_write:
                harness_apply.apply_application(second)
            atomic_write.assert_not_called()
            self.assertEqual((root / ".harness" / "manifest.json").read_bytes(), first_manifest)
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_apply_writes_only_changed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))

            updated = harness_apply.build_application(
                root, minimal_plan(root, skill_suffix="\nUpdated\n")
            )
            actions = {item["path"]: item["action"] for item in updated["report"]["actions"]}
            self.assertEqual(actions[".agents/skills/project-harness/SKILL.md"], "update")
            self.assertEqual(actions["AGENTS.md"], "unchanged")
            self.assertEqual(actions[".harness/manifest.json"], "update")

            with mock.patch.object(
                harness_state, "atomic_write_bytes", wraps=harness_state.atomic_write_bytes
            ) as atomic_write:
                harness_apply.apply_application(updated)

            written_paths = {Path(call.args[0]) for call in atomic_write.call_args_list}
            self.assertIn(
                (root / ".agents" / "skills" / "project-harness" / "SKILL.md").resolve(),
                written_paths,
            )
            self.assertIn((root / ".harness" / "manifest.json").resolve(), written_paths)
            self.assertNotIn((root / "AGENTS.md").resolve(), written_paths)
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not enforceable on Windows")
    def test_mode_only_update_is_applied_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(
                harness_apply.build_application(root, minimal_plan(root, skill_mode="0644"))
            )

            updated = harness_apply.build_application(root, minimal_plan(root, skill_mode="0755"))
            actions = {item["path"]: item["action"] for item in updated["report"]["actions"]}
            self.assertEqual(actions[".agents/skills/project-harness/SKILL.md"], "update")
            harness_apply.apply_application(updated)

            skill = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            self.assertEqual(stat.S_IMODE(skill.stat().st_mode), 0o755)
            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            entry = next(item for item in manifest["managedFiles"] if item["path"] == ".agents/skills/project-harness/SKILL.md")
            self.assertEqual(entry["mode"], "0755")

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not enforceable on Windows")
    def test_recovery_restores_original_content_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(
                harness_apply.build_application(root, minimal_plan(root, skill_mode="0755"))
            )
            skill = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            original = skill.read_bytes()
            updated = harness_apply.build_application(
                root,
                minimal_plan(root, skill_suffix="\nUpdated\n", skill_mode="0644"),
            )
            journal = harness_transaction.prepare_transaction(
                root,
                harness_apply.application_outputs(updated),
                harness_apply.application_actions(updated),
                updated["originalHashes"],
                updated["originalModes"],
                updated["desiredModes"],
                updated["managedPreconditions"],
            )
            operation = next(
                item
                for item in journal["operations"]
                if item["path"] == ".agents/skills/project-harness/SKILL.md"
            )
            stage = harness_state.resolve_inside(root, operation["stage"], must_exist=True)
            harness_state.atomic_write_bytes(
                skill, stage.read_bytes(), mode=operation["desiredMode"]
            )

            recovery = harness_transaction.recover_transaction(root)

            self.assertEqual(recovery["state"], "rolled-back")
            self.assertEqual(skill.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(skill.stat().st_mode), 0o755)

    def test_apply_rejects_incomplete_action_map_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = harness_apply.build_application(root, minimal_plan(root))
            application["report"]["actions"].pop()

            with mock.patch.object(
                harness_state, "atomic_write_bytes", wraps=harness_state.atomic_write_bytes
            ) as atomic_write:
                with self.assertRaises(harness_apply.PlanError):
                    harness_apply.apply_application(application)

            atomic_write.assert_not_called()
            self.assertFalse((root / ".harness" / "manifest.json").exists())

    def test_apply_rejects_incomplete_mode_map_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = harness_apply.build_application(root, minimal_plan(root))
            application["desiredModes"].pop("AGENTS.md")

            with mock.patch.object(
                harness_state, "atomic_write_bytes", wraps=harness_state.atomic_write_bytes
            ) as atomic_write:
                with self.assertRaises(harness_apply.PlanError):
                    harness_apply.apply_application(application)

            atomic_write.assert_not_called()
            self.assertFalse((root / ".harness" / "manifest.json").exists())

    def test_apply_rolls_back_all_outputs_after_mid_transaction_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = harness_apply.build_application(root, minimal_plan(root))
            original_write = harness_state.atomic_write_bytes
            failed = False

            def fail_once(path: Path, data: bytes, *, mode: int | None = None) -> None:
                nonlocal failed
                if Path(path) == (root / "AGENTS.md").resolve() and not failed:
                    failed = True
                    raise OSError("injected target failure")
                original_write(Path(path), data, mode=mode)

            with mock.patch.object(harness_state, "atomic_write_bytes", side_effect=fail_once):
                with self.assertRaises(harness_transaction.TransactionError):
                    harness_apply.apply_application(application)

            self.assertTrue(failed)
            self.assertFalse((root / ".agents" / "skills" / "project-harness" / "SKILL.md").exists())
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / ".harness" / "manifest.json").exists())
            self.assertFalse((root / ".harness" / "transaction.json").exists())

    def test_recover_removes_a_created_file_even_without_applied_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = harness_apply.build_application(root, minimal_plan(root))
            actions = harness_apply.application_actions(application)
            journal = harness_transaction.prepare_transaction(
                root,
                harness_apply.application_outputs(application),
                actions,
                application["originalHashes"],
                application["originalModes"],
                application["desiredModes"],
                application["managedPreconditions"],
            )
            self.assertIsNotNone(journal)
            operation = journal["operations"][0]
            target = harness_state.resolve_inside(root, operation["path"])
            stage = harness_state.resolve_inside(root, operation["stage"], must_exist=True)
            harness_state.atomic_write_bytes(
                target, stage.read_bytes(), mode=operation["desiredMode"]
            )

            recovery = harness_transaction.recover_transaction(root)

            self.assertEqual(recovery["state"], "rolled-back")
            self.assertEqual(recovery["removed"], 1)
            self.assertFalse(target.exists())
            self.assertFalse((root / ".harness" / "transaction.json").exists())

    def test_recover_cleans_an_interrupted_preparing_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = harness_apply.build_application(root, minimal_plan(root))
            actions = harness_apply.application_actions(application)
            original_write = harness_state.atomic_write_bytes
            failed = False

            def fail_first_stage(path: Path, data: bytes, *, mode: int | None = None) -> None:
                nonlocal failed
                normalized = Path(path).as_posix()
                if "/.harness/transactions/" in normalized and not failed:
                    failed = True
                    raise OSError("injected staging failure")
                original_write(Path(path), data, mode=mode)

            with mock.patch.object(
                harness_state, "atomic_write_bytes", side_effect=fail_first_stage
            ):
                with self.assertRaises(OSError):
                    harness_transaction.prepare_transaction(
                        root,
                        harness_apply.application_outputs(application),
                        actions,
                        application["originalHashes"],
                        application["originalModes"],
                        application["desiredModes"],
                        application["managedPreconditions"],
                    )

            self.assertTrue(failed)
            self.assertEqual(harness_state.transaction_status(root)["state"], "preparing")
            recovery = harness_transaction.recover_transaction(root)
            self.assertEqual(recovery["state"], "preparing")
            self.assertFalse((root / ".harness" / "transaction.json").exists())
            self.assertFalse((root / ".harness" / "transactions").exists())

    def test_update_failure_restores_the_previous_managed_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            skill = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            manifest = root / ".harness" / "manifest.json"
            skill_before = skill.read_bytes()
            manifest_before = manifest.read_bytes()
            updated = harness_apply.build_application(
                root, minimal_plan(root, skill_suffix="\nUpdated\n")
            )
            original_write = harness_state.atomic_write_bytes
            failed = False

            def fail_manifest_once(path: Path, data: bytes, *, mode: int | None = None) -> None:
                nonlocal failed
                if Path(path) == manifest.resolve() and not failed:
                    failed = True
                    raise OSError("injected manifest failure")
                original_write(Path(path), data, mode=mode)

            with mock.patch.object(
                harness_state, "atomic_write_bytes", side_effect=fail_manifest_once
            ):
                with self.assertRaises(harness_transaction.TransactionError):
                    harness_apply.apply_application(updated)

            self.assertTrue(failed)
            self.assertEqual(skill.read_bytes(), skill_before)
            self.assertEqual(manifest.read_bytes(), manifest_before)
            self.assertFalse((root / ".harness" / "transaction.json").exists())
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_apply_refuses_target_drift_before_transaction_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = harness_apply.build_application(root, minimal_plan(root))
            (root / "AGENTS.md").write_text("user-owned late file\n", encoding="utf-8")

            with self.assertRaises(harness_transaction.TransactionError):
                harness_apply.apply_application(application)

            self.assertEqual(
                (root / "AGENTS.md").read_text(encoding="utf-8"), "user-owned late file\n"
            )
            self.assertFalse((root / ".agents" / "skills" / "project-harness" / "SKILL.md").exists())
            self.assertFalse((root / ".harness" / "transaction.json").exists())

    def test_plan_rejects_traversal_inside_an_allowed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan["artifacts"].append(
                {
                    "path": ".agents/skills/../../escaped.md",
                    "mode": "0644",
                    "content": "must not be written\n",
                }
            )

            with self.assertRaises(harness_apply.PlanError):
                harness_apply.build_application(root, plan)

            self.assertFalse((root / "escaped.md").exists())

    def test_recovery_preserves_external_edits_and_keeps_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = harness_apply.build_application(root, minimal_plan(root))
            actions = harness_apply.application_actions(application)
            journal = harness_transaction.prepare_transaction(
                root,
                harness_apply.application_outputs(application),
                actions,
                application["originalHashes"],
                application["originalModes"],
                application["desiredModes"],
                application["managedPreconditions"],
            )
            operation = journal["operations"][0]
            target = harness_state.resolve_inside(root, operation["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("external edit\n", encoding="utf-8")

            with self.assertRaises(harness_transaction.TransactionError):
                harness_transaction.recover_transaction(root)

            self.assertEqual(target.read_text(encoding="utf-8"), "external edit\n")
            self.assertTrue((root / ".harness" / "transaction.json").is_file())

    def test_recovery_preserves_an_externally_deleted_update_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            updated = harness_apply.build_application(
                root, minimal_plan(root, skill_suffix="\nUpdated\n")
            )
            actions = harness_apply.application_actions(updated)
            harness_transaction.prepare_transaction(
                root,
                harness_apply.application_outputs(updated),
                actions,
                updated["originalHashes"],
                updated["originalModes"],
                updated["desiredModes"],
                updated["managedPreconditions"],
            )
            skill = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            skill.unlink()

            with self.assertRaises(harness_transaction.TransactionError):
                harness_transaction.recover_transaction(root)

            self.assertFalse(skill.exists())
            self.assertTrue((root / ".harness" / "transaction.json").is_file())

    def test_apply_uses_active_agents_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("base instructions\n", encoding="utf-8")
            (root / "AGENTS.override.md").write_text("override instructions\n", encoding="utf-8")

            application = harness_apply.build_application(root, minimal_plan(root))
            harness_apply.apply_application(application)

            self.assertEqual((root / "AGENTS.md").read_text(encoding="utf-8"), "base instructions\n")
            self.assertEqual(
                (root / "AGENTS.override.md").read_text(encoding="utf-8"),
                "override instructions\n",
            )
            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIsNone(manifest["instructionFile"])
            self.assertEqual(manifest["workspace"]["instructionMode"], "explicit-skill")

    def test_git_workspace_preserves_metadata_and_tracked_user_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("tracked project instructions\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", "pyproject.toml", "AGENTS.md"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Harness Tests",
                    "-c", "user.email=harness@example.invalid", "commit", "-m", "fixture",
                ],
                check=True,
                capture_output=True,
            )

            metadata_before = {
                path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (root / ".git").rglob("*") if path.is_file()
            }
            application = harness_apply.build_application(root, minimal_plan(root))
            harness_apply.apply_application(application)
            self.assertEqual(
                {
                    path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (root / ".git").rglob("*") if path.is_file()
                },
                metadata_before,
            )

            self.assertEqual(
                (root / "AGENTS.md").read_text(encoding="utf-8"),
                "tracked project instructions\n",
            )
            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["workspace"]["scope"], "project-local")
            self.assertEqual(manifest["workspace"]["kind"], "git-repository")
            self.assertEqual(manifest["workspace"]["instructionMode"], "explicit-skill")
            self.assertIsNone(manifest["instructionFile"])
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                set(status.stdout.splitlines()),
                {"?? .agents/skills/project-harness/SKILL.md", "?? .harness/manifest.json"},
            )
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_git_workspace_creates_a_pointer_without_ignoring_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            plan = minimal_plan(root)
            subprocess.run(
                ["git", "-C", str(root), "add", "pyproject.toml"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Harness Tests",
                    "-c", "user.email=harness@example.invalid", "commit", "-m", "fixture",
                ],
                check=True,
                capture_output=True,
            )

            harness_apply.apply_application(harness_apply.build_application(root, plan))

            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["workspace"]["instructionMode"], "managed-pointer")
            self.assertEqual(manifest["instructionFile"], "AGENTS.md")
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                set(status.stdout.splitlines()),
                {
                    "?? .agents/skills/project-harness/SKILL.md",
                    "?? .harness/manifest.json",
                    "?? AGENTS.md",
                },
            )

    def test_git_workspace_can_create_an_absent_target_regardless_of_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            plan = minimal_plan(root)
            target = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("legacy tracked target\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", "pyproject.toml", target.relative_to(root).as_posix()],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Harness Tests",
                    "-c", "user.email=harness@example.invalid", "commit", "-m", "fixture",
                ],
                check=True,
                capture_output=True,
            )
            target.unlink()

            application = harness_apply.build_application(root, plan)
            self.assertFalse((root / ".harness" / "manifest.json").exists())
            harness_apply.apply_application(application)
            self.assertEqual(target.read_text(encoding="utf-8"), plan["artifacts"][0]["content"])
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_schema5_installation_upgrades_through_reviewed_project_local_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            harness_apply.apply_application(harness_apply.build_application(root, plan))
            manifest_path = root / ".harness" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schemaVersion"] = 5
            manifest["generator"]["version"] = "6.10"
            manifest.pop("workspace")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            application = harness_apply.build_application(root, plan)
            harness_apply.apply_application(application)
            upgraded = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(upgraded["schemaVersion"], harness_metadata.MANIFEST_SCHEMA_VERSION)
            self.assertEqual(upgraded["workspace"]["scope"], "project-local")


class WorkspaceTests(unittest.TestCase):
    def test_remote_git_commands_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(harness_workspace.WorkspaceError, "prohibited"):
                harness_workspace._run_git(Path(directory), ["remote"])

    def test_directory_workspace_allows_declared_nested_repository_write_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "models" / "external" / ".git").mkdir(parents=True)
            plan = minimal_plan(root)
            plan["topology"]["boundaries"][0]["writeScopes"] = ["models/external/src/**"]
            application = harness_apply.build_application(root, plan)
            harness_apply.apply_application(application)
            report = validate_harness.Validator(root).run()
            self.assertTrue(report["valid"], report)

    def test_multiple_worktrees_support_generation_without_shared_exclusion_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repository"
            worktree = parent / "worktree"
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            (repository / "pyproject.toml").write_text(
                "[project]\nname = 'fixture'\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "-C", str(repository), "add", "pyproject.toml"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(repository), "-c", "user.name=Harness Tests",
                    "-c", "user.email=harness@example.invalid", "commit", "-m", "fixture",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "add", "-b", "fixture-worktree", str(worktree)],
                check=True,
                capture_output=True,
            )

            exclude = repository / ".git" / "info" / "exclude"
            before = exclude.read_bytes()
            before_mtime = exclude.stat().st_mtime_ns
            for selected in (repository, worktree):
                with self.subTest(selected=selected):
                    application = harness_apply.build_application(selected, minimal_plan(selected))
                    harness_apply.apply_application(application)
                    self.assertTrue(validate_harness.Validator(selected).run()["valid"])
                    # The evaluator's optional shared-exclusion operation stays guarded.
                    with self.assertRaisesRegex(
                        harness_workspace.WorkspaceError, "shared across registered worktrees"
                    ):
                        harness_workspace.require_exclusive_info_exclude(selected)
            self.assertEqual(exclude.read_bytes(), before)
            self.assertEqual(exclude.stat().st_mtime_ns, before_mtime)

    def test_validator_accepts_a_sibling_worktree_added_after_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repository"
            worktree = parent / "worktree"
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            plan = minimal_plan(repository)
            subprocess.run(
                ["git", "-C", str(repository), "add", "pyproject.toml"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(repository), "-c", "user.name=Harness Tests",
                    "-c", "user.email=harness@example.invalid", "commit", "-m", "fixture",
                ],
                check=True,
                capture_output=True,
            )
            harness_apply.apply_application(harness_apply.build_application(repository, plan))
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "add", "-b", "sibling", str(worktree)],
                check=True,
                capture_output=True,
            )

            report = validate_harness.Validator(repository).run()

            self.assertTrue(report["valid"], report)
            self.assertEqual(
                report["validationLayers"]["workspaceOwnership"]["status"], "passed"
            )

    def test_gitignore_metacharacters_are_encoded_as_literal_path_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            target_relative = "notes/[ab] report.txt"
            sibling_relative = "notes/a report.txt"
            protection = harness_workspace.plan_local_protection(
                root, "git-repository", [target_relative]
            )

            self.assertIn("/notes/\\[ab\\]\\ report.txt", protection["patterns"])
            self.assertEqual(
                harness_workspace._normalize_pattern("notes/*-draft?.txt"),
                "/notes/\\*-draft\\?.txt",
            )
            harness_workspace.apply_local_protection(root, protection, [target_relative])
            for relative in (target_relative, sibling_relative):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")

            target = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "--no-index", target_relative],
                check=False,
                capture_output=True,
                text=True,
            )
            sibling = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "--no-index", sibling_relative],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(target.returncode, 0, target.stderr)
            self.assertEqual(sibling.returncode, 1, sibling.stdout)

    def test_control_characters_are_rejected_from_managed_paths(self) -> None:
        for relative in (
            ".agents/skills/project-harness/references/bad\nname.md",
            ".agents/skills/project-harness/references/bad\rname.md",
            ".agents/skills/project-harness/references/bad\x00name.md",
            ".agents/skills/project-harness/references/bad\x7fname.md",
        ):
            with self.subTest(relative=repr(relative)):
                with self.assertRaisesRegex(harness_state.StateError, "control characters"):
                    harness_state.portable_path_key(relative)

    def test_transaction_precondition_failure_does_not_change_local_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            application = harness_apply.build_application(root, minimal_plan(root))
            exclude = root / ".git" / "info" / "exclude"
            before = exclude.read_bytes()
            target = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("concurrent user file\n", encoding="utf-8")

            with self.assertRaisesRegex(
                harness_transaction.TransactionError, "create target appeared before apply"
            ):
                harness_apply.apply_application(application)

            self.assertEqual(exclude.read_bytes(), before)
            self.assertFalse((root / ".harness" / "manifest.json").exists())
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn(".agents/skills/project-harness/SKILL.md", status.stdout)

    def test_mid_apply_project_rollback_does_not_change_local_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            application = harness_apply.build_application(root, minimal_plan(root))
            exclude = root / ".git" / "info" / "exclude"
            before = exclude.read_bytes()
            original_write = harness_state.atomic_write_bytes
            failed = False

            def fail_once(path: Path, data: bytes, *, mode: int | None = None) -> None:
                nonlocal failed
                if Path(path) == (root / "AGENTS.md").resolve() and not failed:
                    failed = True
                    raise OSError("injected target failure")
                original_write(Path(path), data, mode=mode)

            with mock.patch.object(harness_state, "atomic_write_bytes", side_effect=fail_once):
                with self.assertRaises(harness_transaction.TransactionError):
                    harness_apply.apply_application(application)

            self.assertTrue(failed)
            self.assertEqual(exclude.read_bytes(), before)
            self.assertFalse((root / ".harness" / "manifest.json").exists())
            self.assertIsNone(harness_state.transaction_status(root))

    def test_failed_apply_preserves_external_exclude_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            application = harness_apply.build_application(root, minimal_plan(root))
            exclude = root / ".git" / "info" / "exclude"

            def fail_after_external_edit(*_args, **_kwargs):
                with exclude.open("a", encoding="utf-8") as stream:
                    stream.write("# external edit\n")
                raise harness_transaction.TransactionError("injected preparation failure")

            with mock.patch.object(
                harness_transaction, "prepare_transaction", side_effect=fail_after_external_edit
            ):
                with self.assertRaisesRegex(
                    harness_transaction.TransactionError, "injected preparation failure"
                ):
                    harness_apply.apply_application(application)

            self.assertIn("# external edit", exclude.read_text(encoding="utf-8"))
            self.assertFalse((root / ".harness" / "manifest.json").exists())

    def test_old_local_protection_marker_is_preserved_without_blocking_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            protection = harness_workspace.plan_local_protection(
                root, "git-repository", [".agents/skills/project-harness/SKILL.md"]
            )
            harness_workspace.apply_local_protection(
                root, protection, [".agents/skills/project-harness/SKILL.md"]
            )
            exclude = root / ".git" / "info" / "exclude"
            before = (exclude.read_bytes(), exclude.stat().st_mtime_ns)

            report = validate_harness.Validator(root).run()

            self.assertFalse(report["valid"])
            self.assertEqual(
                report["validationLayers"]["workspaceOwnership"]["status"], "blocked"
            )
            self.assertTrue(any("missing .harness/manifest.json" in error for error in report["errors"]))
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            self.assertTrue(validate_harness.Validator(root).run()["valid"])
            self.assertEqual((exclude.read_bytes(), exclude.stat().st_mtime_ns), before)

    def test_unmanaged_tracked_control_file_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            (root / ".harness").mkdir()
            (root / ".harness" / "legacy.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(root), "add", ".harness/legacy.json"],
                check=True,
                capture_output=True,
            )

            legacy = root / ".harness" / "legacy.json"
            before = (legacy.read_bytes(), legacy.stat().st_mtime_ns)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            self.assertEqual((legacy.read_bytes(), legacy.stat().st_mtime_ns), before)
            self.assertTrue(validate_harness.Validator(root).run()["valid"])


class ApplyContinuationTests(unittest.TestCase):
    def test_tracked_managed_files_update_only_while_owned_hashes_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            subprocess.run(
                ["git", "-C", str(root), "add", ".agents", ".harness", "AGENTS.md"],
                check=True, capture_output=True,
            )
            index = root / ".git" / "index"
            index_before = (index.read_bytes(), index.stat().st_mtime_ns)
            changed_plan = minimal_plan(root, skill_suffix="\nReviewed update\n")
            harness_apply.apply_application(harness_apply.build_application(root, changed_plan))
            self.assertTrue(validate_harness.Validator(root).run()["valid"])
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), index_before)
            target = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            target.write_text("user edit\n", encoding="utf-8")
            manifest_path = root / ".harness" / "manifest.json"
            before = (manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns)
            with self.assertRaisesRegex(harness_apply.PlanError, "modified"):
                harness_apply.build_application(root, changed_plan)
            self.assertEqual(target.read_text(encoding="utf-8"), "user edit\n")
            self.assertEqual((manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns), before)
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), index_before)

    def test_modified_managed_file_refuses_update_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = harness_apply.build_application(root, minimal_plan(root))
            harness_apply.apply_application(initial)
            instruction_before = (root / "AGENTS.md").read_bytes()
            skill = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            skill.write_text("user modification\n", encoding="utf-8")

            with self.assertRaises(harness_apply.PlanError):
                harness_apply.build_application(
                    root, minimal_plan(root, skill_suffix="\nUpdated\n")
                )

            self.assertEqual((root / "AGENTS.md").read_bytes(), instruction_before)
            self.assertEqual(skill.read_text(encoding="utf-8"), "user modification\n")


class TopologyContractTests(unittest.TestCase):
    @staticmethod
    def add_boundary(plan: dict, identifier: str, *, depends_on: list[str] | None = None) -> None:
        boundary = copy.deepcopy(plan["topology"]["boundaries"][0])
        boundary["id"] = identifier
        boundary["name"] = identifier.replace("-", " ").title()
        boundary["decisionAreaIds"] = [identifier]
        boundary["dependsOn"] = list(depends_on or [])
        plan["topology"]["boundaries"].append(boundary)

    def test_four_static_boundaries_remain_modular_with_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            for identifier in ("contract-surface", "data-flow", "quality-review"):
                self.add_boundary(plan, identifier)
            classification = plan["topology"]["classification"]
            classification.update(
                {
                    "class": "modular",
                    "materialBoundaryCount": 4,
                    "dependencyShape": "static-dag",
                }
            )

            warnings = harness_topology.validate_contract(
                plan["topology"], plan["capabilityPolicies"]
            )

            self.assertEqual(len(warnings), 1)
            self.assertIn("four or more", warnings[0])

    def test_coordinated_topology_requires_repository_level_recurrence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            self.add_boundary(plan, "contract-surface")
            plan["topology"]["classification"].update(
                {
                    "class": "coordinated",
                    "materialBoundaryCount": 2,
                    "dependencyShape": "static-dag",
                }
            )

            with self.assertRaisesRegex(harness_topology.TopologyError, "recurring coordination"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["classification"].update(
                {
                    "recurringCoordination": True,
                    "coordinationReasons": ["cross-contract-verification"],
                }
            )
            for boundary in plan["topology"]["boundaries"]:
                boundary["types"] = ["contract"]
            with self.assertRaisesRegex(
                harness_topology.TopologyError, "references at least two contract boundaries"
            ):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["skills"].append(
                {
                    "name": "contract-sync",
                    "scope": "cross-boundary",
                    "boundaryRefs": ["project-core", "contract-surface"],
                }
            )
            harness_topology.validate_contract(plan["topology"], plan["capabilityPolicies"])

    def test_scope_containment_distinguishes_literals_from_recursive_prefixes(self) -> None:
        self.assertTrue(harness_topology.scope_contains("src/model.py", "src/model.py"))
        self.assertFalse(harness_topology.scope_contains("src/model.py", "src/model.py/**"))
        self.assertFalse(harness_topology.scope_contains("src/model", "src/model/**"))
        self.assertTrue(harness_topology.scope_contains("src/model/**", "src/model"))
        self.assertTrue(harness_topology.scope_contains("src/model/**", "src/model/item.py"))
        self.assertTrue(harness_topology.scope_contains("src/model/**", "src/model/nested/**"))

    def test_case_only_writer_scopes_conflict_portably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            self.add_boundary(plan, "contract-surface")
            plan["topology"]["classification"].update(
                {
                    "class": "modular",
                    "materialBoundaryCount": 2,
                    "dependencyShape": "static-dag",
                }
            )
            plan["topology"]["executionPhases"] = [
                {
                    "id": "implementation",
                    "order": 0,
                    "concurrencyGroups": [{"id": "parallel", "order": 0}],
                }
            ]
            plan["topology"]["boundaries"][0]["writeScopes"] = ["Src/Model/**"]
            plan["topology"]["boundaries"][1]["writeScopes"] = ["src/model/**"]
            plan["topology"]["agents"] = [
                {
                    "name": "upper_writer",
                    "scope": "boundary",
                    "boundaryRefs": ["project-core"],
                    "fileAccess": [
                        {
                            "scope": "Src/Model/**",
                            "mode": "write",
                            "phase": "implementation",
                            "concurrencyGroup": "parallel",
                        }
                    ],
                },
                {
                    "name": "lower_writer",
                    "scope": "boundary",
                    "boundaryRefs": ["contract-surface"],
                    "fileAccess": [
                        {
                            "scope": "src/model/**",
                            "mode": "write",
                            "phase": "implementation",
                            "concurrencyGroup": "parallel",
                        }
                    ],
                },
            ]

            with self.assertRaisesRegex(harness_topology.TopologyError, "concurrent writers"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

    def test_generation_plan_rejects_runtime_task_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan["taskExecution"] = {"class": "coordinated"}
            path = root / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")

            with self.assertRaisesRegex(harness_apply.PlanError, "runtime-only"):
                harness_apply.load_plan(path)

    def test_generation_plan_rejects_nested_runtime_role_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan["topology"]["skills"][0]["runtimeRole"] = "integrator"

            with self.assertRaisesRegex(harness_apply.PlanError, "runtime-only"):
                harness_apply.build_application(root, plan)

    def test_dependency_order_and_structural_interaction_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            self.add_boundary(plan, "contract-surface", depends_on=["project-core"])
            plan["topology"]["boundaries"][0]["interactsWith"] = ["contract-surface"]
            plan["topology"]["boundaries"][1]["interactsWith"] = ["project-core"]
            plan["topology"]["classification"].update(
                {
                    "class": "modular",
                    "materialBoundaryCount": 2,
                    "dependencyShape": "static-dag",
                }
            )
            harness_topology.validate_contract(plan["topology"], plan["capabilityPolicies"])

            plan["topology"]["boundaries"][0]["dependsOn"] = ["contract-surface"]
            with self.assertRaisesRegex(harness_topology.TopologyError, "acyclic"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

    def test_decision_area_ids_are_unique_across_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            self.add_boundary(plan, "contract-surface")
            plan["topology"]["classification"].update(
                {
                    "class": "modular",
                    "materialBoundaryCount": 2,
                    "dependencyShape": "static-dag",
                }
            )
            plan["topology"]["boundaries"][1]["decisionAreaIds"] = ["project-core"]

            with self.assertRaisesRegex(
                harness_topology.TopologyError, "assigned to multiple boundaries"
            ):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

    def test_dependency_shape_matches_declared_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            self.add_boundary(plan, "contract-surface", depends_on=["project-core"])
            plan["topology"]["classification"].update(
                {
                    "class": "modular",
                    "materialBoundaryCount": 2,
                    "dependencyShape": "independent",
                }
            )
            with self.assertRaisesRegex(harness_topology.TopologyError, "empty dependsOn"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["boundaries"][1]["dependsOn"] = []
            plan["topology"]["classification"]["dependencyShape"] = "cyclic-contract"
            with self.assertRaisesRegex(harness_topology.TopologyError, "cycle in interactsWith"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["boundaries"][0]["interactsWith"] = ["contract-surface"]
            plan["topology"]["boundaries"][1]["interactsWith"] = ["project-core"]
            harness_topology.validate_contract(plan["topology"], plan["capabilityPolicies"])

    def test_coordination_reasons_require_supporting_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            plan["topology"]["classification"].update(
                {
                    "class": "coordinated",
                    "dependencyShape": "dynamic",
                    "recurringCoordination": True,
                    "coordinationReasons": ["dynamic-allocation"],
                }
            )
            with self.assertRaisesRegex(harness_topology.TopologyError, "supervisor"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["collaborationPatterns"] = ["supervisor"]
            harness_topology.validate_contract(plan["topology"], plan["capabilityPolicies"])

    def test_concurrent_writers_with_overlapping_scopes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            self.add_boundary(plan, "contract-surface")
            plan["topology"]["classification"].update(
                {
                    "class": "modular",
                    "materialBoundaryCount": 2,
                    "dependencyShape": "static-dag",
                }
            )
            plan["topology"]["executionPhases"] = [
                {
                    "id": "implementation",
                    "order": 0,
                    "concurrencyGroups": [{"id": "parallel", "order": 0}],
                }
            ]
            plan["topology"]["boundaries"][0]["writeScopes"] = ["src/**"]
            plan["topology"]["boundaries"][1]["writeScopes"] = ["src/contracts/**"]
            plan["topology"]["agents"] = [
                {
                    "name": "core_writer",
                    "scope": "boundary",
                    "boundaryRefs": ["project-core"],
                    "fileAccess": [
                        {
                            "scope": "src/**",
                            "mode": "write",
                            "phase": "implementation",
                            "concurrencyGroup": "parallel",
                        }
                    ],
                },
                {
                    "name": "contract_writer",
                    "scope": "boundary",
                    "boundaryRefs": ["contract-surface"],
                    "fileAccess": [
                        {
                            "scope": "src/contracts/**",
                            "mode": "write",
                            "phase": "implementation",
                            "concurrencyGroup": "parallel",
                        }
                    ],
                },
            ]

            with self.assertRaisesRegex(harness_topology.TopologyError, "concurrent writers"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

    def test_persistent_quality_policy_cannot_use_runtime_task_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            evidence = plan["project"]["evidence"]
            plan["topology"]["qualityPatternPolicies"] = [
                {
                    "id": "safety-review",
                    "name": "independent-safety-review",
                    "justificationSource": "runtime-task-risk",
                    "evidence": evidence,
                    "boundaryRefs": ["project-core"],
                    "budget": {"maxReviewers": 1},
                    "stoppingCondition": "Stop after one review.",
                    "failurePolicy": "Stop before mutation.",
                }
            ]

            with self.assertRaisesRegex(harness_topology.TopologyError, "repository-evidence"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

    def test_repository_quality_and_routing_policies_are_reference_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            evidence = copy.deepcopy(plan["project"]["evidence"])
            plan["topology"]["collaborationPatterns"] = ["producer-reviewer"]
            plan["topology"]["qualityPatternPolicies"] = [
                {
                    "id": "completeness-check",
                    "name": "completeness-critic",
                    "justificationSource": "repository-evidence",
                    "evidence": evidence,
                    "boundaryRefs": ["project-core"],
                    "budget": {"maxRounds": 1},
                    "stoppingCondition": "Stop after one independent completeness pass.",
                    "failurePolicy": "Report unresolved omissions and stop.",
                }
            ]
            plan["topology"]["routingPolicies"] = [
                {
                    "id": "release-review",
                    "evidence": evidence,
                    "taskCategories": ["release-review"],
                    "activeBoundaryRefs": ["project-core"],
                    "recommendedExecutionClass": "delegated",
                    "collaborationPatterns": ["producer-reviewer"],
                    "qualityPolicyRefs": ["completeness-check"],
                    "capabilityPolicyRef": "direct-default",
                }
            ]

            application = harness_apply.build_application(root, plan)

            self.assertTrue(application["report"]["valid"])
            manifest = json.loads(application["manifestText"])
            self.assertEqual(
                manifest["topology"]["routingPolicies"][0]["qualityPolicyRefs"],
                ["completeness-check"],
            )

    def test_routing_categories_are_global_and_direct_routes_do_not_collaborate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            evidence = copy.deepcopy(plan["project"]["evidence"])
            route = {
                "id": "first-route",
                "evidence": evidence,
                "taskCategories": ["release-review"],
                "activeBoundaryRefs": ["project-core"],
                "recommendedExecutionClass": "direct",
                "collaborationPatterns": [],
                "qualityPolicyRefs": [],
                "capabilityPolicyRef": "direct-default",
            }
            plan["topology"]["routingPolicies"] = [route, {**route, "id": "second-route"}]
            with self.assertRaisesRegex(harness_topology.TopologyError, "globally assigned"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["routingPolicies"] = [route]
            plan["topology"]["collaborationPatterns"] = ["supervisor"]
            route["collaborationPatterns"] = ["supervisor"]
            with self.assertRaisesRegex(harness_topology.TopologyError, "direct execution"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

    def test_quality_budget_keys_and_relations_are_pattern_specific(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            evidence = copy.deepcopy(plan["project"]["evidence"])
            policy = {
                "id": "dry-review",
                "name": "loop-until-dry",
                "justificationSource": "repository-evidence",
                "evidence": evidence,
                "boundaryRefs": ["project-core"],
                "budget": {"maxRounds": 2, "zeroFindingRounds": 1, "maxAngles": 4},
                "stoppingCondition": "Stop after one zero-finding round or two total rounds.",
                "failurePolicy": "Report unresolved findings and stop.",
            }
            plan["topology"]["qualityPatternPolicies"] = [policy]
            with self.assertRaisesRegex(harness_topology.TopologyError, "exactly"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            policy["budget"] = {"maxRounds": 1, "zeroFindingRounds": 2}
            with self.assertRaisesRegex(harness_topology.TopologyError, "must not exceed"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            policy["budget"] = {"maxRounds": 2, "zeroFindingRounds": 1}
            harness_topology.validate_contract(plan["topology"], plan["capabilityPolicies"])

    def test_ordered_overlapping_writers_require_and_accept_a_verified_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            self.add_boundary(plan, "contract-surface")
            plan["topology"]["classification"].update(
                {
                    "class": "modular",
                    "materialBoundaryCount": 2,
                    "dependencyShape": "static-dag",
                }
            )
            for boundary in plan["topology"]["boundaries"]:
                boundary["writeScopes"] = ["shared/**"]
            plan["topology"]["executionPhases"] = [
                {
                    "id": "design",
                    "order": 0,
                    "concurrencyGroups": [{"id": "producer", "order": 0}],
                },
                {
                    "id": "implementation",
                    "order": 1,
                    "concurrencyGroups": [{"id": "consumer", "order": 0}],
                },
            ]
            plan["topology"]["agents"] = [
                {
                    "name": "schema_designer",
                    "scope": "boundary",
                    "boundaryRefs": ["project-core"],
                    "fileAccess": [
                        {
                            "scope": "shared/**",
                            "mode": "write",
                            "phase": "design",
                            "concurrencyGroup": "producer",
                        }
                    ],
                },
                {
                    "name": "migration_builder",
                    "scope": "boundary",
                    "boundaryRefs": ["contract-surface"],
                    "fileAccess": [
                        {
                            "scope": "shared/migrations/**",
                            "mode": "write",
                            "phase": "implementation",
                            "concurrencyGroup": "consumer",
                        }
                    ],
                },
            ]

            with self.assertRaisesRegex(harness_topology.TopologyError, "verified handoff"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["handoffs"] = [
                {
                    "fromAgent": "schema_designer",
                    "toAgent": "migration_builder",
                    "scope": "shared/migrations/generated/**",
                    "fromPhase": "design",
                    "fromConcurrencyGroup": "producer",
                    "toPhase": "implementation",
                    "toConcurrencyGroup": "consumer",
                    "precondition": "The design is frozen and hashed.",
                    "verification": "The consumer verifies the frozen hash.",
                }
            ]
            with self.assertRaisesRegex(
                harness_topology.TopologyError, "complete overlapping scope"
            ):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            plan["topology"]["handoffs"][0]["scope"] = "shared/migrations/**"
            harness_topology.validate_contract(plan["topology"], plan["capabilityPolicies"])

    def test_required_runtime_capability_requires_probe_and_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            policy = plan["capabilityPolicies"][0]
            policy.update(
                {
                    "semanticMode": "deterministic-orchestration",
                    "requiredCapabilities": ["parallel-delegation"],
                    "preferredRuntimeMapping": "runtime-native",
                }
            )

            with self.assertRaisesRegex(harness_topology.TopologyError, "probe"):
                harness_topology.validate_contract(
                    plan["topology"], plan["capabilityPolicies"]
                )

            policy["probe"] = {"mode": "runtime-check"}
            policy["fallback"] = {
                "semanticMode": "one-shot-delegation",
                "implementation": "Primary-agent-controlled sequential delegation.",
                "preserves": ["input", "output", "verification"],
            }
            harness_topology.validate_contract(plan["topology"], plan["capabilityPolicies"])

    def test_golden_evaluation_uses_stable_decision_area_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = minimal_plan(Path(directory))
            report = evaluate_topology.evaluate(
                plan,
                {
                    "expectedClass": "minimal",
                    "minimumMaterialBoundaries": 1,
                    "maximumMaterialBoundaries": 1,
                    "maximumAgents": 0,
                    "requiredDecisionAreaIds": ["project-core"],
                    "forbiddenAgents": ["frontend_agent", "backend_agent"],
                    "acceptableCollaborationPatterns": [],
                },
            )

            self.assertTrue(report["valid"])
            self.assertEqual(report["validationScope"], "topology-contract")
            self.assertFalse(report["evidenceValidated"])
            self.assertEqual(report["coverage"], 1.0)

    def test_modular_and_coordinated_golden_fixtures_are_evidence_bound(self) -> None:
        fixtures = (
            ("modular-expert-pool", "modular-expert-pool"),
            ("coordinated-cross-contract", "coordinated-cross-contract"),
        )
        for project_name, fixture_name in fixtures:
            with self.subTest(fixture=fixture_name):
                plan = json.loads(
                    (REPO_ROOT / "tests" / "fixtures" / f"{fixture_name}-topology.json").read_text(
                        encoding="utf-8"
                    )
                )
                golden = json.loads(
                    (REPO_ROOT / "tests" / "fixtures" / f"{fixture_name}-golden.json").read_text(
                        encoding="utf-8"
                    )
                )
                report = evaluate_topology.evaluate(plan, golden)
                self.assertTrue(report["valid"], report)
                root = REPO_ROOT / "tests" / "fixtures" / project_name
                for label, evidence in harness_topology.iter_evidence(plan["topology"]):
                    harness_apply.validate_evidence(root, evidence, label)

    def test_applied_manifest_uses_project_local_contract_without_runtime_task_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            manifest = json.loads(
                (root / ".harness" / "manifest.json").read_text(encoding="utf-8")
            )

            self.assertEqual(manifest["schemaVersion"], harness_metadata.MANIFEST_SCHEMA_VERSION)
            self.assertEqual(manifest["workspace"]["scope"], "project-local")
            self.assertEqual(manifest["generator"]["version"], harness_metadata.HARNESS_VERSION)
            self.assertNotIn("taskExecution", manifest)
            self.assertEqual(manifest["topology"]["classification"]["class"], "minimal")

    def test_current_workflow_checks_tracked_and_untracked_cleanliness(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "codex-v9.6.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("git diff --exit-code", workflow)
        self.assertIn(
            "git status --porcelain=v1 --untracked-files=all",
            workflow,
        )


class ValidatorTests(unittest.TestCase):
    def test_installed_validation_rejects_reserved_evidence_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(
                harness_apply.build_application(root, minimal_plan(root))
            )
            manifest_path = root / ".harness" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["project"]["evidence"] = [
                {
                    "path": ".harness/manifest.json",
                    "sha256": "0" * 64,
                    "claim": "Reserved metadata must never be accepted as evidence.",
                }
            ]
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )

            report = validate_harness.Validator(root).run()

            self.assertFalse(report["valid"])
            self.assertTrue(
                any("reserved control namespace" in error for error in report["errors"]),
                report["errors"],
            )

    def test_validation_accepts_git_observation_changes_without_relabeling_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(
                harness_apply.build_application(root, minimal_plan(root))
            )
            manifest_path = root / ".harness" / "manifest.json"
            before = (manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns)
            (root / "nested-project" / ".git").mkdir(parents=True)

            report = validate_harness.Validator(root).run()

            self.assertTrue(report["valid"], report)
            self.assertEqual(report["validationLayers"]["rootContext"]["status"], "passed")
            self.assertEqual(
                report["validationLayers"]["workspaceOwnership"]["status"], "passed"
            )
            self.assertEqual(
                report["validationLayers"]["managedOwnership"]["status"], "passed"
            )
            self.assertEqual((manifest_path.read_bytes(), manifest_path.stat().st_mtime_ns), before)

    def test_validation_report_separates_static_checks_from_live_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(
                harness_apply.build_application(root, minimal_plan(root))
            )

            report = validate_harness.Validator(root).run()

            self.assertTrue(report["valid"])
            self.assertTrue(
                all(
                    layer["status"] == "passed"
                    for layer in report["validationLayers"].values()
                )
            )
            self.assertEqual(
                report["externalCapabilities"]["customAgentDiscovery"]["status"],
                "not-tested",
            )
            self.assertEqual(
                report["externalCapabilities"]["harnessBenefitAttribution"]["status"],
                "not-measured",
            )

    def test_missing_manifest_blocks_dependent_validation_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = validate_harness.Validator(Path(directory)).run()

            self.assertFalse(report["valid"])
            self.assertEqual(
                report["validationLayers"]["manifestContract"]["status"], "failed"
            )
            self.assertEqual(
                report["validationLayers"]["managedOwnership"]["status"], "blocked"
            )

    def test_manifest_rejects_case_only_managed_path_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(
                harness_apply.build_application(root, minimal_plan(root))
            )
            manifest_path = root / ".harness" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            original = next(
                entry
                for entry in manifest["managedFiles"]
                if entry["path"] == ".agents/skills/project-harness/SKILL.md"
            )
            duplicate = copy.deepcopy(original)
            duplicate["path"] = ".agents/skills/project-harness/skill.md"
            manifest["managedFiles"].append(duplicate)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = validate_harness.Validator(root).run()

            self.assertFalse(report["valid"])
            self.assertTrue(
                any("portable path collision" in error for error in report["errors"])
            )

    def test_invalid_agent_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan["topology"]["executionPhases"] = [
                {
                    "id": "review",
                    "order": 0,
                    "concurrencyGroups": [{"id": "contract", "order": 0}],
                }
            ]
            plan["topology"]["agents"] = [
                {
                    "name": "contract_reviewer",
                    "path": ".codex/agents/contract_reviewer.toml",
                    "skills": ["project-harness"],
                    "responsibility": "Review project contracts independently.",
                    "whyDelegate": "Independent review reduces confirmation bias.",
                    "evidence": list(plan["project"]["evidence"]),
                    "scope": "boundary",
                    "boundaryRefs": ["project-core"],
                    "fileAccess": [
                        {
                            "scope": "pyproject.toml",
                            "mode": "read",
                            "phase": "review",
                            "concurrencyGroup": "contract",
                        }
                    ],
                }
            ]
            plan["artifacts"].append(
                {
                    "path": ".codex/agents/contract_reviewer.toml",
                    "mode": "0644",
                    "content": (
                        'name = "contract_reviewer"\n'
                        'description = "Review project contracts."\n'
                        'developer_instructions = """Use project-harness and report evidence.\n\n'
                        f'{harness_teamplay.AGENT_BLOCK}\n'
                        f'{harness_agent_contract.render(plan["topology"]["agents"][0], plan["topology"])}\n'
                        '"""\n'
                    ),
                }
            )
            harness_apply.apply_application(harness_apply.build_application(root, plan))
            agent = root / ".codex" / "agents" / "contract_reviewer.toml"
            agent.write_text('name = "contract_reviewer"\n', encoding="utf-8")
            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            for entry in manifest["managedFiles"]:
                if entry["path"] == ".codex/agents/contract_reviewer.toml":
                    entry["sha256"] = harness_state.digest_bytes(agent.read_bytes())
            (root / ".harness" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            report = validate_harness.Validator(root).run()

            self.assertFalse(report["valid"])
            self.assertTrue(any("missing description" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
