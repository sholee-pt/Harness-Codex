"""Direct native resolution and reversible ownership, without touching real PATH."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from harness_cli import codex_integration as integration, integration_path, native_ui, uninstall
from harness_cli import distribution as dist
from test_cli_distribution import source
from test_native_ui import fixture, archive, VERSION
from test_windows_path import Registry


class CodexIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = self.root / 'tool'
        self.src = source(self.root / 'source', VERSION, commit=None)
        dist.install_tool(self.src, self.data, self.root / 'commands', sys.executable)
        self.registry = Registry(('C:\\original;%USERPROFILE%\\tools;', 2))
        self.bundle = self.root / 'bundle'
        fixture(self.bundle)
        self.archive = self.root / 'native.tar.gz'
        archive(self.bundle, self.archive)
        self.patch = mock.patch.object(native_ui, 'platform_key', return_value='windows-x86_64')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.original = self.root / 'original' / 'codex.exe'
        self.original.parent.mkdir()
        self.original.write_bytes(b'original Codex sentinel')
        self.original_patch = mock.patch.object(integration, 'original_codex', return_value=str(self.original))
        self.original_patch.start()
        self.addCleanup(self.original_patch.stop)
        self.broadcast = mock.patch('harness_cli.windows_path._broadcast', return_value=True)
        self.broadcast.start()
        self.addCleanup(self.broadcast.stop)

    def install(self, **kw):
        return integration.install(self.data, self.src, archive=self.archive, registry=self.registry, **kw)

    def test_direct_binary_registration_reuses_without_writes_or_environment_mutation(self):
        environment = dict(os.environ)
        result = self.install(mode='auto')
        directory = Path(result['directory'])
        self.assertEqual(directory.name, 'bin')
        self.assertEqual(self.registry.value[0].split(';')[0], str(directory))
        receipt = integration.read(self.data)
        sidecar = self.data / next(iter(receipt['files']))
        settings = json.loads(sidecar.read_text())
        self.assertEqual(settings['mode'], 'auto')
        self.assertEqual(Path(settings['script']).parent.parent, Path(dist.installed_status(self.data)['sourceRoot']))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (sidecar, self.data / integration.RECEIPT, self.original)}
        self.install()
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}, before)
        self.assertEqual(len(self.registry.writes), 1)
        self.assertEqual(os.environ, environment)

    def test_failed_path_commit_restores_receipts_and_original_binary(self):
        before = self.registry.value
        with mock.patch.object(integration_path, 'apply', side_effect=ValueError('Concurrent PATH edit')):
            with self.assertRaisesRegex(ValueError, 'Concurrent'):
                self.install()
        self.assertIsNone(integration.read(self.data))
        self.assertEqual(self.registry.value, before)
        self.assertEqual(self.original.read_bytes(), b'original Codex sentinel')
        self.install()

    def test_legacy_launcher_dependent_package_cannot_be_registered_as_direct(self):
        metadata = self.bundle / 'harness-ui.json'
        value = json.loads(metadata.read_text())
        value.pop('directIntegrationVersion')
        metadata.write_text(json.dumps(value))
        archive(self.bundle, self.archive)
        before = self.registry.value
        with self.assertRaisesRegex(ValueError, 'retired Harness launcher'):
            self.install()
        self.assertEqual(self.registry.value, before)
        self.assertIsNone(integration.read(self.data))

    def test_update_keeps_running_version_files_and_moves_only_owned_path_entry(self):
        self.install(mode='auto')
        before = integration.read(self.data)
        previous_binary = Path(before['directory']) / 'codex.exe'
        previous_bytes = previous_binary.read_bytes()
        newer = source(self.root / 'next-source', '0.15.0-beta', commit=None)
        dist.install_tool(newer, self.data, self.root / 'commands', sys.executable)
        self.assertEqual(integration.status(self.data)['state'], 'upgrade-required')
        metadata = self.bundle / 'harness-ui.json'
        value = json.loads(metadata.read_text())
        value['version'] = '0.15.0-beta'
        metadata.write_text(json.dumps(value))
        archive(self.bundle, self.archive)
        result = integration.install(self.data, newer, archive=self.archive, registry=self.registry)
        self.assertEqual(result['mode'], 'auto')
        self.assertNotIn(before['directory'], self.registry.value[0].split(';'))
        self.assertEqual(previous_binary.read_bytes(), previous_bytes)
        self.assertEqual(len(integration.read(self.data)['files']), 2)
        self.assertEqual(self.original.read_bytes(), b'original Codex sentinel')

    def test_modified_settings_and_unknown_package_files_block_update_and_uninstall(self):
        self.install()
        value = integration.read(self.data)
        settings = self.data / next(iter(value['files']))
        settings.write_text('{}')
        before = self.registry.value
        with self.assertRaisesRegex(ValueError, 'Modified'):
            self.install()
        with self.assertRaises(ValueError):
            uninstall.prepare(self.data)
        self.assertEqual(self.registry.value, before)
        self.assertEqual(settings.read_text(), '{}')
        self.assertEqual(integration.status(self.data)['state'], 'invalid')

    def test_confirmed_removal_restores_original_resolution_and_preserves_project(self):
        before = self.registry.value
        self.install()
        project = self.root / 'project' / 'AGENTS.md'
        project.parent.mkdir()
        project.write_bytes(b'user and project harness')
        real_plan, real_apply = integration_path.plan, integration_path.apply
        with mock.patch.object(uninstall, '_path_action', return_value={'state': 'preserved'}), \
             mock.patch.object(integration_path, 'plan', side_effect=lambda *a, **kw: real_plan(*a, **kw, registry=self.registry)), \
             mock.patch.object(integration_path, 'apply', side_effect=lambda change: real_apply(change, registry=self.registry)):
            plan = uninstall.prepare(self.data)
            self.assertIn(self.data / integration.RECEIPT, plan['files'])
            self.assertEqual(uninstall.remove(plan)['state'], 'uninstalled')
        self.assertEqual(self.registry.value, before)
        self.assertEqual(self.original.read_bytes(), b'original Codex sentinel')
        self.assertEqual(project.read_bytes(), b'user and project harness')
        self.assertFalse(self.data.exists())

    def test_windows_concurrent_edit_and_unowned_equivalent_entry_are_preserved(self):
        directory = self.root / 'native' / 'bin'
        change = integration_path.plan(directory, registry=self.registry)
        self.registry.value = ('user concurrent PATH', 1)
        with self.assertRaisesRegex(ValueError, 'changed'):
            integration_path.apply(change, registry=self.registry)
        self.assertEqual(self.registry.value, ('user concurrent PATH', 1))
        self.registry.value = (str(directory).upper() + '\\', 2)
        with self.assertRaisesRegex(ValueError, 'ownership'):
            integration_path.plan(directory, registry=self.registry)

    @unittest.skipIf(os.name == 'nt', 'POSIX shell PATH semantics')
    def test_bash_registration_is_idempotent_and_uninstall_preserves_user_bytes(self):
        from harness_cli import shell
        home = self.root / 'home'
        home.mkdir()
        profile = home / '.bashrc'
        original = b'# User settings\r\nexport USER_SETTING=yes\r\n'
        profile.write_bytes(original)
        directory = self.root / 'native bin'
        integration_path.apply(integration_path.plan(directory, home=home))
        before = profile.stat().st_mtime_ns
        integration_path.apply(integration_path.plan(directory, previous=directory, home=home))
        self.assertEqual(profile.stat().st_mtime_ns, before)
        shell.register_path(self.root / 'commands', home=home)
        integration_path.apply(integration_path.plan(previous=directory, remove_tool=self.root / 'commands', home=home))
        self.assertEqual(profile.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
