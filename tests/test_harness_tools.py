from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness_apply  # noqa: E402
import harness_state  # noqa: E402
import harness_transaction  # noqa: E402
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
        f"{skill_suffix}"
    )
    return {
        "schemaVersion": 2,
        "project": {
            "summary": "Fixture project",
            "evidence": [evidence],
            "rationale": {
                "summary": "The project is small, so only the orchestrator is justified.",
                "uncertainties": [],
            },
        },
        "topology": {
            "patterns": [],
            "agents": [],
            "skills": [
                {
                    "name": "project-harness",
                    "path": ".agents/skills/project-harness/SKILL.md",
                    "purpose": "Coordinate repository-wide fixture work.",
                    "evidence": [evidence],
                }
            ],
        },
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

            self.assertEqual(result["activeRootInstruction"], "AGENTS.override.md")
            self.assertEqual(result["instructions"], ["AGENTS.md", "AGENTS.override.md"])


class StateTests(unittest.TestCase):
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
            self.assertEqual(migrated["generator"]["version"], "4.0.0")
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
    def test_dry_run_is_no_write_and_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)

            application = harness_apply.build_application(root, plan)

            self.assertFalse((root / ".harness" / "manifest.json").exists())
            self.assertTrue(all(item["action"] == "create" for item in application["report"]["actions"]))

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
                root / ".agents" / "skills" / "project-harness" / "SKILL.md",
                written_paths,
            )
            self.assertIn(root / ".harness" / "manifest.json", written_paths)
            self.assertNotIn(root / "AGENTS.md", written_paths)
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
                if Path(path) == root / "AGENTS.md" and not failed:
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
                if Path(path) == manifest and not failed:
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
            self.assertIn("$project-harness", (root / "AGENTS.override.md").read_text(encoding="utf-8"))
            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["instructionFile"], "AGENTS.override.md")
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

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


class ValidatorTests(unittest.TestCase):
    def test_invalid_agent_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            plan["topology"]["agents"] = [
                {
                    "name": "contract_reviewer",
                    "path": ".codex/agents/contract_reviewer.toml",
                    "skills": ["project-harness"],
                    "responsibility": "Review project contracts independently.",
                    "whyDelegate": "Independent review reduces confirmation bias.",
                    "evidence": list(plan["project"]["evidence"]),
                }
            ]
            plan["artifacts"].append(
                {
                    "path": ".codex/agents/contract_reviewer.toml",
                    "mode": "0644",
                    "content": (
                        'name = "contract_reviewer"\n'
                        'description = "Review project contracts."\n'
                        'developer_instructions = "Use project-harness and report evidence."\n'
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
