from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.agents/skills/harness/scripts')]

import harness_apply
import harness_external_skills as external
import harness_frontmatter
import validate_harness
from harness_cli import main as cli
from test_harness_tools import minimal_plan


class ExternalSkillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='harness-external-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.source = self.base / 'upstream/skills/sample-analysis'
        self.source.mkdir(parents=True)
        self.content = '---\nname: sample-analysis\ndescription: Analyze the selected sample.\nlicense: MIT\nmetadata:\n  version: "1.2"\n---\n\nRead references/procedure.md.\n'
        (self.source / 'SKILL.md').write_text(self.content, encoding='utf-8')
        (self.source / 'references').mkdir()
        (self.source / 'references/procedure.md').write_text('A domain procedure.\n', encoding='utf-8')

    def test_preview_and_import_preserve_metadata_resources_and_license(self):
        license_file = self.base / 'upstream/LICENSE'
        license_file.write_text('Fixture license notice.\n', encoding='utf-8')
        kwargs = {'upstream': 'https://github.com/example/skills', 'revision': 'a' * 40, 'license_file': license_file}
        preview = external.add(self.root, self.source, dry_run=True, **kwargs)
        self.assertEqual(preview['status'], 'preview')
        self.assertEqual(list(self.root.iterdir()), [])
        report = external.add(self.root, self.source, **kwargs)
        target = self.root / report['path']
        self.assertEqual((target / 'SKILL.md').read_bytes(), (self.source / 'SKILL.md').read_bytes())
        self.assertEqual((target / 'UPSTREAM-LICENSE.txt').read_bytes(), license_file.read_bytes())
        self.assertEqual(external.verify(self.root, self.source.name)['status'], 'unchanged')
        receipt = json.loads((target / external.RECEIPT).read_text())
        self.assertEqual(receipt['revision'], 'a' * 40)
        self.assertIn('not network-verified', receipt['provenance'])
        self.assertNotIn(str(self.base), json.dumps(receipt))
        with self.assertRaises(harness_frontmatter.FrontmatterError):
            harness_frontmatter.parse((target / 'SKILL.md').read_text())

    def test_existing_skill_and_case_collision_are_preserved(self):
        target = self.root / '.agents/skills/SAMPLE-ANALYSIS'
        target.mkdir(parents=True)
        with self.assertRaises(ValueError):
            external.add(self.root, self.source)
        self.assertTrue(target.is_dir())
        self.assertEqual(list(target.iterdir()), [])

    def test_foreign_skill_survives_generator_apply_and_noop(self):
        report = external.add(self.root, self.source)
        target = self.root / report['path']
        before = {p.relative_to(target).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in target.rglob('*') if p.is_file()}
        plan = minimal_plan(self.root)
        harness_apply.apply_application(harness_apply.build_application(self.root, plan))
        self.assertTrue(validate_harness.Validator(self.root).run()['valid'])
        result = harness_apply.apply_application(harness_apply.build_application(self.root, plan))
        self.assertEqual(result['writes'], 0)
        self.assertEqual(before, {p.relative_to(target).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in target.rglob('*') if p.is_file()})
        manifest = json.loads((self.root / '.harness/manifest.json').read_text())
        self.assertNotIn('sample-analysis', json.dumps(manifest))

    def test_discovery_never_hashes_or_reads_the_import_receipt(self):
        report = external.add(self.root, self.source)
        (self.root / report['path'] / external.RECEIPT).write_text('malformed receipt')
        with mock.patch.object(external, '_files', side_effect=AssertionError('inventory must not hash')):
            result = external.inventory(self.root)
        self.assertEqual(result['skills'][0]['name'], 'sample-analysis')
        self.assertTrue(result['skills'][0]['importReceiptPresent'])
        self.assertEqual(result['skills'][0]['runtimeLoading'], 'not-tested')

    def test_selected_verification_detects_edits_additions_and_deletions(self):
        report = external.add(self.root, self.source)
        target = self.root / report['path']
        (target / 'SKILL.md').write_text(self.content + '\nEdited\n')
        (target / 'references/procedure.md').unlink()
        (target / 'added.txt').write_text('new')
        result = external.verify(self.root, self.source.name)
        self.assertEqual(result['changedFiles'], ['SKILL.md', 'added.txt', 'references/procedure.md'])
        self.assertEqual(result['status'], 'changed')

    def test_bad_inputs_fail_before_project_writes(self):
        metadata_root = self.root / '.git'
        metadata_root.mkdir()
        with self.assertRaises(ValueError):
            external.add(metadata_root, self.source)
        self.assertEqual(list(metadata_root.iterdir()), [])
        metadata_root.rmdir()
        for kwargs in ({'upstream': 'https://github.com/a/b'}, {'upstream': 'https://github.com/a/b', 'revision': 'main'},
                       {'revision': 'a' * 40}, {'license_file': self.base / 'absent'}):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, OSError)):
                external.add(self.root, self.source, **kwargs)
            self.assertEqual(list(self.root.iterdir()), [])
        for content in (self.content.replace('name: sample-analysis', 'name: harness'),
                        self.content.replace('license: MIT', 'name: duplicate'),
                        self.content.replace('license: MIT', '<<: *defaults')):
            (self.source / 'SKILL.md').write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                external.add(self.root, self.source)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_limits_are_import_limits_not_project_file_limits(self):
        (self.source / 'SKILL.md').write_text(self.content + '\U0001f600' * 40000, encoding='utf-8')
        self.assertEqual(external.metadata(self.source / 'SKILL.md')['name'], 'sample-analysis')
        with mock.patch.object(external, 'MAX_BYTES', 10), self.assertRaises(ValueError):
            external.add(self.root, self.source)
        self.assertEqual(list(self.root.iterdir()), [])

    @unittest.skipIf(os.name == 'nt', 'Linux symlink permissions differ from Windows')
    def test_links_and_concurrent_empty_destination_are_preserved(self):
        (self.source / 'outside').symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            external.add(self.root, self.source)
        (self.source / 'outside').unlink()
        original = external._publish
        def concurrent(stage, destination):
            destination.mkdir()
            return original(stage, destination)
        with mock.patch.object(external, '_publish', side_effect=concurrent), self.assertRaises(OSError):
            external.add(self.root, self.source)
        self.assertEqual(list((self.root / '.agents/skills/sample-analysis').iterdir()), [])

    def test_failed_publication_cleans_stage_without_an_installed_skill(self):
        with mock.patch.object(external, '_publish', side_effect=OSError('fixture failure')), self.assertRaises(OSError):
            external.add(self.root, self.source)
        self.assertFalse((self.root / '.agents/skills/sample-analysis').exists())
        self.assertEqual(list((self.root / '.agents').glob('.harness-import-*')), [])

    def test_source_change_before_publication_is_rejected(self):
        original = external._files
        def changed(path):
            result = original(path)
            if path == self.source:
                (self.source / 'SKILL.md').write_text(self.content + 'changed')
            return result
        with mock.patch.object(external, '_files', side_effect=changed), self.assertRaises(ValueError):
            external.add(self.root, self.source)
        self.assertFalse((self.root / '.agents/skills/sample-analysis').exists())

    def test_unreadable_source_tree_is_not_silently_truncated(self):
        def denied(*args, **kwargs):
            kwargs['onerror'](PermissionError('unreadable source reference'))
        with mock.patch.object(external.os, 'walk', side_effect=denied), self.assertRaises(PermissionError):
            external.add(self.root, self.source)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_distribution_requires_external_runtime_and_guidance(self):
        from harness_cli import distribution
        from test_cli_distribution import source
        fixture = source(self.base / 'distribution', '0.22.0-beta')
        snapshot = {path.relative_to(fixture).as_posix(): path.read_bytes() for path in fixture.rglob('*') if path.is_file()}
        distribution._source_info(snapshot)
        for relative in ('harness_cli/skills.py', '.agents/skills/harness/scripts/harness_external_skills.py',
                         '.agents/skills/harness/references/external-skills.md', '.agents/skills/harness/references/contract-review.md',
                         '.agents/skills/harness/references/scientific-workflows.md'):
            with self.subTest(path=relative), self.assertRaises(distribution.DistributionError):
                distribution._source_info({path: data for path, data in snapshot.items() if path != relative})

    def test_cli_json_add_list_and_changed_exit_status(self):
        def invoke(*arguments):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = cli.main(['--no-update-check', 'skills', *arguments, '--project', str(self.root), '--json'], source_root=ROOT)
            return status, json.loads(output.getvalue())
        with mock.patch.object(cli, '_environment'):
            self.assertEqual(invoke('add', '--source', str(self.source))[1]['status'], 'added')
            self.assertEqual(len(invoke('list')[1]['skills']), 1)
            path = self.root / '.agents/skills/sample-analysis/SKILL.md'
            path.write_text(self.content + 'edit')
            self.assertEqual(invoke('verify', '--name', 'sample-analysis')[0], 1)
