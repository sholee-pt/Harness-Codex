from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness_apply  # noqa: E402
import harness_state  # noqa: E402
import inventory  # noqa: E402
import validate_harness  # noqa: E402


def minimal_plan(*, skill_suffix: str = "") -> dict:
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
        "schemaVersion": 1,
        "project": {
            "summary": "Fixture project",
            "evidence": ["pyproject.toml"],
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
                    "evidence": ["pyproject.toml"],
                }
            ],
        },
        "artifacts": [
            {"path": ".agents/skills/project-harness/SKILL.md", "content": skill_content}
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
            self.write_manifest(root, schema_version=2)

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

            self.assertEqual(migrated["schemaVersion"], 2)
            self.assertEqual(migrated["instructionFile"], "AGENTS.md")
            self.assertIn("rationale", migrated["project"])
            self.assertEqual(harness_state.status_report(root)["counts"], {"unchanged": 1})

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

    @staticmethod
    def write_manifest(root: Path, schema_version: int) -> None:
        manifest = {
            "schemaVersion": schema_version,
            "generator": {"name": "Harness", "version": "1.0.0", "runtime": "codex"},
            "project": {"summary": "Fixture project", "evidence": []},
            "topology": {"patterns": [], "agents": [], "skills": []},
            "managedFiles": [],
        }
        if schema_version == 2:
            manifest["instructionFile"] = "AGENTS.md"
            manifest["project"]["rationale"] = {"summary": "Fixture rationale", "uncertainties": []}
        (root / ".harness" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class ApplyTests(unittest.TestCase):
    def test_dry_run_is_no_write_and_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan()

            application = harness_apply.build_application(root, plan)

            self.assertFalse((root / ".harness" / "manifest.json").exists())
            self.assertTrue(all(item["action"] == "create" for item in application["report"]["actions"]))

            harness_apply.apply_application(application)
            first_manifest = (root / ".harness" / "manifest.json").read_bytes()
            second = harness_apply.build_application(root, plan)
            self.assertTrue(all(item["action"] == "unchanged" for item in second["report"]["actions"]))
            harness_apply.apply_application(second)
            self.assertEqual((root / ".harness" / "manifest.json").read_bytes(), first_manifest)
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_apply_uses_active_agents_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("base instructions\n", encoding="utf-8")
            (root / "AGENTS.override.md").write_text("override instructions\n", encoding="utf-8")

            application = harness_apply.build_application(root, minimal_plan())
            harness_apply.apply_application(application)

            self.assertEqual((root / "AGENTS.md").read_text(encoding="utf-8"), "base instructions\n")
            self.assertIn("$project-harness", (root / "AGENTS.override.md").read_text(encoding="utf-8"))
            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["instructionFile"], "AGENTS.override.md")
            self.assertTrue(validate_harness.Validator(root).run()["valid"])

    def test_modified_managed_file_refuses_update_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = harness_apply.build_application(root, minimal_plan())
            harness_apply.apply_application(initial)
            instruction_before = (root / "AGENTS.md").read_bytes()
            skill = root / ".agents" / "skills" / "project-harness" / "SKILL.md"
            skill.write_text("user modification\n", encoding="utf-8")

            with self.assertRaises(harness_apply.PlanError):
                harness_apply.build_application(root, minimal_plan(skill_suffix="\nUpdated\n"))

            self.assertEqual((root / "AGENTS.md").read_bytes(), instruction_before)
            self.assertEqual(skill.read_text(encoding="utf-8"), "user modification\n")


class ValidatorTests(unittest.TestCase):
    def test_invalid_agent_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan()
            plan["topology"]["agents"] = [
                {
                    "name": "contract_reviewer",
                    "path": ".codex/agents/contract_reviewer.toml",
                    "skills": ["project-harness"],
                    "responsibility": "Review project contracts independently.",
                    "whyDelegate": "Independent review reduces confirmation bias.",
                    "evidence": ["pyproject.toml"],
                }
            ]
            plan["artifacts"].append(
                {
                    "path": ".codex/agents/contract_reviewer.toml",
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
