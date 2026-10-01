"""External retrieval stays explicit, bounded, local and independently removable."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness_cli import graft, graft_sources, main

REPO = Path(__file__).resolve().parents[1]


class ExternalSourcesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.external = self.base / 'library'
        self.external.mkdir()
        (self.external / 'model.py').write_text('def predict():\n    return 42\n')
        patch = mock.patch.dict(os.environ, {'HARNESS_GRAFT_HOME': str(self.base / 'state')})
        patch.start()
        self.addCleanup(patch.stop)
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={}):
            self.execute('enable', '--package', str(self.base / 'package'))

    def execute(self, *args):
        options = main.build_parser(REPO).parse_args(['graft', *args, '--project', str(self.root)])
        return graft.execute(options, REPO)

    def test_add_query_refresh_remove_and_preserve_original_and_primary_index(self):
        original = (self.external / 'model.py').read_bytes()
        self.execute('add', str(self.external / 'model.py'), '--name', 'library')
        calls = []
        def invoke(source, root, cache, settings, action, **kw):
            calls.append((root, kw))
            if root == self.root:
                return {'text': 'project result', 'hits': 1, 'refreshed': False}
            return {'text': 'library/model.py:1 predict', 'hits': 1, 'refreshed': False}
        with mock.patch.object(graft, '_invoke', side_effect=invoke), mock.patch('harness_cli.jev.enabled', return_value=False):
            result = self.execute('query', 'predict')
            self.assertIn(str(self.external / 'model.py'), result['text'])
            self.assertFalse(calls[-1][1]['advice'])
            snapshot = graft.storage(self.root) / 'external/source/library/model.py'
            stamp = snapshot.stat().st_mtime_ns
            self.execute('query', 'predict')
            self.assertEqual(snapshot.stat().st_mtime_ns, stamp)
            (self.external / 'model.py').write_bytes(original + b'# changed\n')
            self.execute('query', 'predict')
            self.assertEqual(snapshot.read_bytes(), original + b'# changed\n')
            self.execute('remove', 'library')
            calls.clear()
            self.execute('query', 'predict')
            self.assertEqual(len(calls), 1)
        self.assertEqual((self.external / 'model.py').read_bytes(), original + b'# changed\n')
        self.assertFalse((self.root / 'library').exists())

    def test_invalid_sources_do_not_change_settings(self):
        path = graft.storage(self.root) / 'settings.json'
        before = path.read_bytes()
        for location, label in ((self.root, 'bad'), (self.base, 'bad'), (self.external, '../bad')):
            with self.assertRaises(ValueError):
                self.execute('add', str(location), '--name', label)
            self.assertEqual(path.read_bytes(), before)
        secret = self.external / '.env'
        secret.write_text('secret')
        with self.assertRaises(ValueError):
            self.execute('add', str(secret), '--name', 'secret')
        (self.external / 'huge.py').write_bytes(b'x' * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            self.execute('add', str(self.external), '--name', 'large')
        self.assertEqual(path.read_bytes(), before)

    def test_failed_snapshot_promotion_preserves_previous_bytes_and_can_retry(self):
        files = graft_sources.collect(self.root, {'library': str(self.external)})
        folder = graft.storage(self.root) / 'external'
        tree = graft_sources.snapshot(folder, files)
        original = (tree / 'library/model.py').read_bytes()
        (self.external / 'model.py').write_text('def changed(): pass\n')
        changed = graft_sources.collect(self.root, {'library': str(self.external)})
        from harness_cli import project_installer
        replace = project_installer.os.replace
        def fail(source, target):
            if Path(source).name.startswith('.harness-install-stage-'):
                raise OSError('fixture promotion failure')
            return replace(source, target)
        with mock.patch.object(project_installer.os, 'replace', side_effect=fail), self.assertRaises(OSError):
            graft_sources.snapshot(folder, changed)
        self.assertEqual((tree / 'library/model.py').read_bytes(), original)
        graft_sources.snapshot(folder, changed)
        self.assertEqual((tree / 'library/model.py').read_text(), 'def changed(): pass\n')

    def test_missing_source_preserves_primary_result_without_stale_external_hits(self):
        self.execute('add', str(self.external / 'model.py'), '--name', 'library')
        (self.external / 'model.py').unlink()
        with mock.patch.object(graft, '_invoke', return_value={'text': 'primary', 'hits': 1}), mock.patch('harness_cli.jev.enabled', return_value=False):
            result = self.execute('query', 'predict')
        self.assertIn('primary', result['text'])
        self.assertIn('externalWarning', result)
        self.assertNotIn('externalHits', result)

    def test_relocated_skill_adopts_static_ownership_but_not_old_executable_or_sources(self):
        from harness_cli import workspace_context as context
        import shutil
        with mock.patch.object(context, 'probe', return_value='not-applicable'):
            context.refresh(self.root, ['codex'])
        graft._record_skill(self.root)
        self.execute('add', str(self.external), '--name', 'library')
        moved = self.base / 'new-mount'
        shutil.move(str(self.root), str(moved))
        self.root = moved
        with mock.patch.object(graft.shutil, 'which', return_value='/new-node'), mock.patch.object(graft, '_invoke', return_value={}) as invoke:
            self.execute('enable', '--package', str(self.base / 'new-package'))
        settings = invoke.call_args.args[3]
        self.assertEqual(settings['node'], '/new-node')
        self.assertEqual(settings['package'], str(self.base / 'new-package'))
        self.assertNotIn('externalSources', settings)
        self.assertTrue(self.execute('status')['skillInstalled'])

    def test_legacy_adoption_requires_explicit_choice_and_never_accepts_modified_content(self):
        import shutil
        moved = self.base / 'legacy-mount'
        shutil.move(str(self.root), str(moved))
        self.root = moved
        with mock.patch.object(graft.shutil, 'which', return_value='/node'), mock.patch.object(graft, '_invoke', return_value={}):
            with self.assertRaisesRegex(ValueError, 'user-owned or modified'):
                self.execute('enable', '--package', str(self.base / 'package'))
            self.execute('enable', '--package', str(self.base / 'package'), '--adopt-skill')
            (self.root / graft.SKILL_PATH).write_text('User changed this')
            with self.assertRaisesRegex(ValueError, 'user-owned or modified'):
                self.execute('enable', '--package', str(self.base / 'package'), '--adopt-skill')

    def test_directory_alias_is_allowed_but_nested_links_are_not_followed(self):
        import subprocess
        link = self.base / 'alias'
        if os.name == 'nt':
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(self.external)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.addCleanup(lambda: link.rmdir() if os.path.lexists(link) else None)
        else:
            link.symlink_to(self.external, target_is_directory=True)
            self.addCleanup(lambda: link.unlink(missing_ok=True))
        self.assertEqual(graft_sources.select(self.root, link), self.external)
        # Selecting a broader directory must not silently follow that same link.
        container = self.base / 'external-container'
        container.mkdir()
        nested = container / 'nested'
        if os.name == 'nt':
            subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(nested), str(self.external)], check=True, capture_output=True)
            self.addCleanup(lambda: nested.rmdir() if os.path.lexists(nested) else None)
        else:
            nested.symlink_to(self.external, target_is_directory=True)
            self.addCleanup(lambda: nested.unlink(missing_ok=True))
        with self.assertRaisesRegex(ValueError, 'nested link'):
            graft_sources.collect(self.root, {'selected': str(container)})
