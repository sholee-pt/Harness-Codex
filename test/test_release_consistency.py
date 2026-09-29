from __future__ import annotations

import argparse
import ast
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness_apply  # noqa: E402
import harness_eval  # noqa: E402
import harness_eval_schema2  # noqa: E402
import harness_eval_types  # noqa: E402
import harness_metadata  # noqa: E402
import harness_ops  # noqa: E402
import harness_runtime_receipt  # noqa: E402
import harness_runtime_receipt_schema1  # noqa: E402
import harness_state  # noqa: E402
import harness_teamplay  # noqa: E402
import harness_transaction  # noqa: E402


class ReleaseConsistencyTests(unittest.TestCase):
    def test_release_metadata_is_consistent(self) -> None:
        self.assertEqual(harness_metadata.HARNESS_VERSION, "0.26.0-beta")
        self.assertEqual(harness_metadata.AUTHORING_CONTRACT_VERSION, 3)
        self.assertEqual(harness_metadata.ARTIFACT_CONTRACT_VERSION, 2)
        self.assertIn('9.11', harness_metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS)
        self.assertIn('0.10.0-beta', harness_metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS)
        self.assertIn('0.11.0-beta', harness_metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS)
        self.assertNotIn('99.0.0-beta', harness_metadata.ARTIFACT_COMPATIBLE_GENERATOR_VERSIONS)
        self.assertIn('8.0', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertIn('8.1', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertIn('9.0', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertIn('9.1', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertIn('9.2', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertIn('9.3', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertIn('9.4', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertIn('9.5', harness_metadata.READABLE_EVALUATION_VERSIONS)
        self.assertEqual(harness_metadata.INVENTORY_SCHEMA_VERSION, 5)
        self.assertEqual(harness_metadata.ROOT_CONTEXT_SCHEMA_VERSION, 3)
        self.assertEqual(harness_apply.GENERATOR_VERSION, harness_metadata.HARNESS_VERSION)
        self.assertEqual(harness_state.GENERATOR_VERSION, harness_metadata.HARNESS_VERSION)
        self.assertEqual(harness_eval_types.HARNESS_VERSION, harness_metadata.HARNESS_VERSION)
        self.assertEqual(harness_apply.PLAN_SCHEMA_VERSION, harness_metadata.PLAN_SCHEMA_VERSION)
        self.assertEqual(harness_state.CURRENT_SCHEMA_VERSION, harness_metadata.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(
            harness_transaction.TRANSACTION_SCHEMA_VERSION,
            harness_metadata.TRANSACTION_SCHEMA_VERSION,
        )
        self.assertEqual(
            harness_eval_types.RUN_SCHEMA_VERSION,
            harness_metadata.EVALUATION_SCHEMA_VERSION,
        )
        self.assertEqual(
            harness_eval_schema2.ATTRIBUTION_ELIGIBLE_HARNESS_VERSIONS,
            {harness_metadata.HARNESS_VERSION},
        )
        self.assertEqual(harness_runtime_receipt.RECEIPT_SCHEMA_VERSION, 2)
        self.assertEqual(harness_runtime_receipt_schema1.RECEIPT_SCHEMA_VERSION, 1)
        self.assertEqual(
            harness_ops.OPS_EVENT_SCHEMA_VERSION,
            harness_metadata.OPERATIONS_EVENT_SCHEMA_VERSION,
        )

    def test_release_documents_and_workflow_match_current_version(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        versions = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        workflow_path = REPO_ROOT / ".github" / "workflows" / "codex-beta.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        current = harness_metadata.HARNESS_VERSION
        self.assertIn('Version-v' + current.replace('-', '--'), readme)
        self.assertIn('git clone --branch v' + current, readme)
        self.assertIn('| [`v' + current.replace('-beta', '‑beta') + '`](#harness-for-codex-v' + current.replace('.', '') + ')', versions)
        self.assertIn('This branch contains Harness for Codex v' + current, agents)
        self.assertEqual(workflow.splitlines()[0], 'name: Harness for Codex')
        self.assertIn("run-name: ${{ inputs.publish && 'Linux release' || 'Checks' }} · ${{ github.base_ref || github.ref_name }}", workflow)
        self.assertIn('- v' + current, workflow)
        self.assertEqual(sorted(workflow_path.parent.glob('codex-*.yml')), [workflow_path])

    def test_manifest_asset_uses_current_generator_and_stable_schemas(self) -> None:
        asset = json.loads(
            (REPO_ROOT / ".agents" / "skills" / "harness" / "assets" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(asset["generator"]["version"], harness_metadata.HARNESS_VERSION)
        self.assertEqual(asset["artifactContractVersion"], harness_metadata.ARTIFACT_CONTRACT_VERSION)
        self.assertEqual(asset["schemaVersion"], harness_metadata.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(
            asset["application"]["transactionSchemaVersion"],
            harness_metadata.TRANSACTION_SCHEMA_VERSION,
        )

    def test_current_version_literal_has_one_python_source(self) -> None:
        literal_assignments: list[tuple[str, str]] = []
        for path in SCRIPTS.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                    continue
                if node.value.value != harness_metadata.HARNESS_VERSION:
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"HARNESS_VERSION", "GENERATOR_VERSION"}:
                        literal_assignments.append((path.name, target.id))
        self.assertEqual(literal_assignments, [("harness_metadata.py", "HARNESS_VERSION")])

    def test_generated_templates_contain_runtime_teamplay_contracts(self) -> None:
        project = (
            REPO_ROOT / ".agents" / "skills" / "harness" / "assets" / "project-harness.md"
        ).read_text(encoding="utf-8")
        agent = (
            REPO_ROOT / ".agents" / "skills" / "harness" / "assets" / "agent.toml"
        ).read_text(encoding="utf-8")
        self.assertIn(harness_teamplay.PROJECT_BLOCK, project)
        self.assertIn(harness_teamplay.AGENT_BLOCK, agent)
        self.assertIn("Native subagent relay", project)
        self.assertIn("Return one structured coordination packet", agent)
        self.assertNotIn("Peer collaboration", agent)

    def test_existing_eval_cli_commands_are_unchanged(self) -> None:
        expected = {
            "run",
            "record-start",
            "record-complete",
            "annotate",
            "list",
            "inspect",
            "add-observation",
            "view",
            "inspect-observation",
            "export",
            "purge",
            "repair",
            "compare",
            "propose",
            "paired-run",
            "skill-selection-suite",
            "route-selection-suite",
            "change-discipline-suite",
        }
        parser = harness_eval.build_parser()
        choices: set[str] = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                choices.update(action.choices)
        self.assertEqual(choices, expected)


if __name__ == "__main__":
    unittest.main()
