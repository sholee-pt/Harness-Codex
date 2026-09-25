"""Static instruction budgets are advisory and never claim runtime savings."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_harness_tools import harness_apply, harness_plan_builder, harness_teamplay, minimal_plan
import harness_change_discipline
import harness_instruction_audit as audit

ROOT = Path(__file__).resolve().parents[1]


class InstructionAuditTests(unittest.TestCase):
    def test_required_writer_contract_is_not_a_duplicate_suggestion(self):
        body = harness_teamplay.AGENT_BLOCK + '\n\n' + harness_change_discipline.WRITER_BLOCK
        content = 'developer_instructions = ' + json.dumps(body)
        report = audit.summarize({f'.codex/agents/writer_{i}.toml': content for i in range(2)})
        self.assertEqual(report['duplicateParagraphs'], [])
        self.assertEqual(report['characters'], 2 * len(content))

    def test_shared_paragraphs_are_reported_without_raw_text_or_contract_duplicates(self):
        paragraph = 'Project-specific source evidence must be checked before changing the existing evaluator. ' * 3
        body = paragraph + '\n\n' + harness_teamplay.PROJECT_BLOCK
        report = audit.summarize({'AGENTS.md': body, 'AGENTS.override.md': body})
        self.assertEqual(len(report['duplicateParagraphs']), 1)
        self.assertEqual(report['duplicateParagraphs'][0]['paths'], ['AGENTS.md', 'AGENTS.override.md'])
        self.assertNotIn(paragraph, json.dumps(report))
        self.assertEqual(report['bytes'], 2 * len(body.encode()))
        self.assertIn('not measured', report['measurement'])

    def test_discovery_metadata_and_unparsed_agent_are_separate_surfaces(self):
        report = audit.summarize({'.agents/skills/example/SKILL.md': '---\nname: example\ndescription: 설명\n---\nBody',
                                  '.codex/agents/invalid.toml': 'developer_instructions = 42'})
        self.assertEqual(report['discoveryDescriptionCharacters'], 2)
        self.assertEqual({item['kind'] for item in report['surfaces']}, {'on-demand-skill', 'unparsed-instructions'})

    def test_doctor_inventory_is_bounded_and_preserves_project_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'AGENTS.md').write_bytes(b'x' * (audit.MAX_FILE_BYTES + 1))
            before = (root / 'AGENTS.md').stat().st_mtime_ns
            report = audit.inspect(root, {'managedFiles': [{'path': '../outside/SKILL.md'}]})
            self.assertEqual(len(report['skipped']), 2)
            self.assertEqual(report['files'], 0)
            self.assertEqual(before, (root / 'AGENTS.md').stat().st_mtime_ns)

    def test_materialized_guidance_is_idempotent_and_legacy_contract_still_applies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = minimal_plan(root)
            # Existing installations remain supported without the new advice.
            harness_apply.apply_application(harness_apply.build_application(root, plan))
            draft = json.loads((ROOT / '.agents/skills/harness/references/minimal-draft-plan.json').read_text())
            materialized = harness_plan_builder.materialize_plan(draft)
            text = materialized['artifacts'][0]['content']
            self.assertEqual(text.count(harness_teamplay.WORKFLOW_GUIDANCE), 1)
            repeat = copy.deepcopy(materialized)
            repeat['authoringContractVersion'] = draft['authoringContractVersion']
            self.assertEqual(harness_plan_builder.materialize_plan(repeat), materialized)


if __name__ == '__main__':
    unittest.main()
