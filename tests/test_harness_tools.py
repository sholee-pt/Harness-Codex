from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness_state  # noqa: E402
import inventory  # noqa: E402
import validate_harness  # noqa: E402


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


class StateTests(unittest.TestCase):
    def test_record_status_and_conflict_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            (root / "generated.txt").write_text("stable\n", encoding="utf-8")
            (root / "AGENTS.md").write_text(
                "User content\n\n<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n",
                encoding="utf-8",
            )
            self.write_manifest(root, runtime="codex")

            harness_state.record_manifest(root, "codex", ["generated.txt"], ["AGENTS.md"])
            clean = harness_state.status_report(root, "codex")
            self.assertEqual(clean["counts"], {"unchanged": 2})

            (root / "AGENTS.md").write_text(
                "Updated user content\n\n<!-- harness:begin -->\nManaged\n<!-- harness:end -->\n",
                encoding="utf-8",
            )
            outside_block_edit = harness_state.status_report(root, "codex")
            self.assertEqual(outside_block_edit["counts"], {"unchanged": 2})

            (root / "generated.txt").write_text("user edit\n", encoding="utf-8")
            modified = harness_state.status_report(root, "codex")
            self.assertEqual(modified["counts"], {"unchanged": 1, "modified": 1})

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
    def write_manifest(root: Path, runtime: str) -> None:
        manifest = {
            "schemaVersion": 1,
            "generator": {"name": "Harness", "version": "1.0.0", "runtime": runtime},
            "project": {"summary": "Fixture project", "evidence": []},
            "topology": {"patterns": [], "agents": [], "skills": []},
            "managedFiles": [],
        }
        (root / ".harness" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class ValidatorTests(unittest.TestCase):
    def create_valid_project(self, root: Path) -> None:
        (root / ".codex" / "agents").mkdir(parents=True)
        (root / ".agents" / "skills" / "project-harness").mkdir(parents=True)
        (root / ".harness").mkdir()
        (root / ".codex" / "agents" / "contract-reviewer.toml").write_text(
            'name = "contract-reviewer"\n'
            'description = "Review project contracts."\n'
            'developer_instructions = "Return evidence and do not edit files."\n',
            encoding="utf-8",
        )
        (root / ".agents" / "skills" / "project-harness" / "SKILL.md").write_text(
            "---\nname: project-harness\ndescription: Coordinate fixture work.\n---\n\n# Project Harness\n",
            encoding="utf-8",
        )
        (root / "AGENTS.md").write_text(
            "Existing instructions\n\n<!-- harness:begin -->\nUse project-harness.\n<!-- harness:end -->\n",
            encoding="utf-8",
        )
        manifest = {
            "schemaVersion": 1,
            "generator": {"name": "Harness", "version": "1.0.0", "runtime": "codex"},
            "project": {"summary": "Fixture project", "evidence": ["pyproject.toml"]},
            "topology": {
                "patterns": ["producer-reviewer"],
                "agents": [
                    {
                        "name": "contract-reviewer",
                        "path": ".codex/agents/contract-reviewer.toml",
                        "skills": ["project-harness"],
                    }
                ],
                "skills": [
                    {"name": "project-harness", "path": ".agents/skills/project-harness/SKILL.md"}
                ],
            },
            "managedFiles": [],
        }
        (root / ".harness" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        harness_state.record_manifest(
            root,
            "codex",
            [
                ".codex/agents/contract-reviewer.toml",
                ".agents/skills/project-harness/SKILL.md",
            ],
            ["AGENTS.md"],
        )

    def test_valid_codex_harness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_valid_project(root)
            report = validate_harness.Validator(root, "codex").run()
            self.assertTrue(report["valid"], report["errors"])

    def test_invalid_agent_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_valid_project(root)
            agent = root / ".codex" / "agents" / "contract-reviewer.toml"
            agent.write_text('name = "contract-reviewer"\n', encoding="utf-8")
            manifest = json.loads((root / ".harness" / "manifest.json").read_text(encoding="utf-8"))
            for entry in manifest["managedFiles"]:
                if entry["path"] == ".codex/agents/contract-reviewer.toml":
                    entry["sha256"] = harness_state.digest_bytes(agent.read_bytes())
            (root / ".harness" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            report = validate_harness.Validator(root, "codex").run()

            self.assertFalse(report["valid"])
            self.assertTrue(any("missing description" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
