"""Native bundle integrity, transactional ownership and unchanged session launch."""
from argparse import Namespace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import urllib.error

from harness_cli import distribution as dist, native_package as package, native_ui, project, uninstall
from test_cli_distribution import source

VERSION = '0.21.1-beta'


def fixture(root, platform='windows-x86_64'):
    suffix = '.exe' if platform.startswith('windows-') else ''
    names = ['bin/codex' + suffix, 'bin/codex-code-mode-host' + suffix, 'codex-path/rg' + suffix,
             'UPSTREAM_LICENSE', 'UPSTREAM_NOTICE']
    names += ['codex-resources/codex-command-runner.exe', 'codex-resources/codex-windows-sandbox-setup.exe'] if suffix else [
              'codex-resources/bwrap', 'codex-resources/zsh/bin/zsh']
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('fixture ' + name).encode())
    (root / 'codex-package.json').write_text(json.dumps({'layoutVersion': 1, 'target': package.TARGETS[platform],
        'entrypoint': 'bin/codex' + suffix, 'resourcesDir': 'codex-resources', 'pathDir': 'codex-path'}))
    files, directories = package.inventory(root)
    (root / 'harness-ui.json').write_text(json.dumps({'schema': 1, 'version': VERSION, 'directIntegrationVersion': 1,
        'platform': platform, 'target': package.TARGETS[platform], 'upstreamCommit': package.UPSTREAM,
        'extensionSha256': 'a' * 64, 'files': files, 'directories': sorted(directories)}))


def archive(root, path):
    with tarfile.open(path, 'w:gz') as bundle:
        for file in sorted(root.rglob('*')):
            if file.is_file():
                bundle.add(file, arcname=file.relative_to(root).as_posix(), recursive=False)


class NativeUiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / 'bundle'
        fixture(self.bundle)
        self.archive = self.root / 'native.tar.gz'
        archive(self.bundle, self.archive)

    def test_missing_changed_added_and_incompatible_bundles_are_rejected(self):
        package.verify(self.bundle, VERSION, 'windows-x86_64')
        entry = self.bundle / 'codex-resources/codex-command-runner.exe'
        original = entry.read_bytes()
        for mutation in ('changed', 'deleted'):
            if mutation == 'changed':
                entry.write_text('changed')
            else:
                entry.unlink()
            with self.assertRaisesRegex(ValueError, 'receipt'):
                package.verify(self.bundle, VERSION, 'windows-x86_64')
            entry.write_bytes(original)
        (self.bundle / 'unknown').write_text('user content')
        with self.assertRaises(ValueError):
            package.verify(self.bundle, VERSION, 'windows-x86_64')
        with self.assertRaises(ValueError):
            package.verify(self.bundle, '0.22.0-beta', 'windows-x86_64')

    def test_unsafe_tar_members_never_escape_staging(self):
        for index, (name, kind) in enumerate([('../escape', tarfile.REGTYPE), ('C:/escape', tarfile.REGTYPE),
                                              ('linked', tarfile.SYMTYPE)]):
            bad = self.root / f'bad-{index}.tar.gz'
            with tarfile.open(bad, 'w:gz') as bundle:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.linkname = '../outside'
                bundle.addfile(entry)
            with self.assertRaises(ValueError):
                package.extract(bad, self.root / f'unpacked-{index}')
        self.assertFalse((self.root / 'escape').exists())

    def test_install_reuse_and_confirmed_uninstall_share_owned_files(self):
        data = self.root / 'tool'
        dist.install_tool(source(self.root / 'source', VERSION, commit=None), data, self.root / 'commands', sys.executable)
        with mock.patch.object(native_ui, 'platform_key', return_value='windows-x86_64'):
            binary = native_ui.ensure(data, VERSION, archive=self.archive)
            before = binary.stat().st_mtime_ns
            with mock.patch.object(native_ui, 'fetch', side_effect=AssertionError('Unexpected download')):
                self.assertEqual(native_ui.ensure(data, VERSION), binary)
            self.assertEqual(binary.stat().st_mtime_ns, before)
        with mock.patch.object(uninstall, '_path_action', return_value={'state': 'preserved'}):
            plan = uninstall.prepare(data)
            self.assertIn(binary, plan['files'])
            self.assertEqual(uninstall.remove(plan)['state'], 'uninstalled')
        self.assertFalse(data.exists())
        self.assertTrue(self.bundle.exists())

    def test_failed_install_preserves_existing_tool_and_changed_bundle(self):
        data = self.root / 'tool'
        dist.install_tool(source(self.root / 'source', VERSION, commit=None), data, self.root / 'commands', sys.executable)
        before = (data / 'active.json').read_bytes()
        with mock.patch.object(native_ui, 'platform_key', return_value='windows-x86_64'):
            binary = native_ui.ensure(data, VERSION, archive=self.archive)
            binary.write_text('user-modified')
            with self.assertRaises(ValueError):
                native_ui.ensure(data, VERSION, archive=self.archive)
        self.assertEqual(binary.read_text(), 'user-modified')
        self.assertEqual((data / 'active.json').read_bytes(), before)

    def test_staging_failure_removes_only_new_empty_parents(self):
        data = self.root / 'tool'
        dist.install_tool(source(self.root / 'source', VERSION, commit=None), data, self.root / 'commands', sys.executable)
        with mock.patch.object(native_ui, 'platform_key', return_value='windows-x86_64'), \
                mock.patch('shutil.copytree', side_effect=OSError('copy interrupted')):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                native_ui.ensure(data, VERSION, archive=self.archive)
        self.assertFalse((data / 'native-ui').exists())
        self.assertEqual(dist.installed_status(data)['version'], VERSION)

    def test_native_resume_argument_and_environment_are_preserved(self):
        from types import SimpleNamespace
        env = {'PATH': 'original project environment', 'HARNESS_ROUTER_MODE': 'auto'}
        args = SimpleNamespace(command='resume', project=self.root, codex_binary=None,
                               last=False, session_id='example-id', reload_harness=False)
        with mock.patch.object(project.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run, \
             mock.patch.object(project, '_codex_command', return_value=['codex']), \
             mock.patch.object(project, 'codex_environment', return_value=env):
            self.assertEqual(project._compat_conversation(args), 0)
        self.assertEqual(run.call_args.args[0], ['codex', '--cd', str(self.root), 'resume', '--', 'example-id'])
        self.assertEqual(run.call_args.kwargs['env'], env)
        self.assertNotIn('--sandbox', run.call_args.args[0])

    def test_native_package_module_no_longer_launches_conversations(self):
        self.assertFalse(hasattr(native_ui, 'run'))
        # Registration and interpreter settings are tested through the owned
        # sidecar transaction in test_codex_integration, not launch mocks.

    def test_release_redirect_does_not_forward_the_credential(self):
        redirect = urllib.error.HTTPError(native_ui.API + '/releases/assets/1', 302, 'redirect',
            {'Location': 'https://release-assets.githubusercontent.com/signed'}, None)
        opener = mock.Mock()
        opener.open.side_effect = redirect
        with mock.patch.object(native_ui.urllib.request, 'build_opener', return_value=opener), \
                mock.patch.object(native_ui.urllib.request, 'urlopen', return_value=io.BytesIO(b'verified later')) as follow:
            native_ui._download(native_ui.API + '/releases/assets/1', self.root / 'download', 100, token='PRIVATE')
        self.assertEqual(follow.call_args.args, ('https://release-assets.githubusercontent.com/signed',))
        self.assertEqual(follow.call_args.kwargs, {'timeout': 60})


if __name__ == '__main__':
    unittest.main()
