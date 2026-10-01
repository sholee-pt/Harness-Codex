"""Mount changes preserve owned bytes and bind only known installation locations."""
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import posixpath
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from harness_cli import distribution as dist, footprint, installation_paths as locations, maintenance, shell
from test_cli_distribution import source


class InstallationPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.mount = self.base / 'first mount'
        self.data, self.bin = self.mount / 'share/tool', self.mount / 'bin'
        self.source = source(self.base / 'source', '0.30.1-beta')
        dist.install_tool(self.source, self.data, self.bin, sys.executable)

    def move(self):
        new = self.base / 'second mount'
        self.mount.rename(new)
        self.data, self.bin = new / 'share/tool', new / 'bin'
        return new

    def snapshot(self):
        return {p.relative_to(self.data): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.data.rglob('*') if p.is_file()}

    def test_current_and_legacy_metadata_bind_without_writes_or_hash_changes(self):
        for legacy in (False, True):
            if legacy:
                active = json.loads((self.data / 'active.json').read_bytes())
                active.pop('pathOrigin', None)
                (self.data / 'active.json').write_text(json.dumps(active))
            before = self.snapshot()
            if not legacy:
                self.move()
            state = dist.installed_status(self.data)
            self.assertEqual(state['binDir'], str(self.bin))
            self.assertEqual(state['python'], str(Path(sys.executable).resolve()))
            self.assertIn(str(self.data / 'launcher.py'), state['launchers'])
            self.assertEqual(self.snapshot(), before)
            dist._write_json(self.data / 'active.json', {k: v for k, v in state.items()
                             if k not in {'dataRoot', 'sourceRoot', 'releasePath', 'release_root'}})
            self.assertEqual(json.loads((self.data / 'active.json').read_bytes())['binDir'], str(self.mount / 'bin'))

    def test_moved_installation_still_rejects_changed_files_and_layout(self):
        self.move()
        path = self.data / 'launcher.py'
        original = path.read_bytes()
        path.write_bytes(original + b'# user edit\n')
        with self.assertRaisesRegex(ValueError, 'launcher was changed'):
            dist.installed_status(self.data)
        path.write_bytes(original)
        renamed = self.data.with_name('another-tool')
        self.data.rename(renamed)
        with self.assertRaisesRegex(ValueError, 'layout changed'):
            dist.installed_status(renamed)

    def test_integration_views_preserve_canonical_bytes_and_external_paths(self):
        original = {'schema': 1, 'mode': 'auto', 'profiles': str(self.mount / 'profiles.json')}
        dist._write_json(self.data / 'codex-relay.json', original)
        before = (self.data / 'codex-relay.json').read_bytes()
        new = self.move()
        bound = dist._read_json(self.data / 'codex-relay.json')
        self.assertEqual(bound['profiles'], str(new / 'profiles.json'))
        dist._write_json(self.data / 'codex-relay.json', bound)
        self.assertEqual((self.data / 'codex-relay.json').read_bytes(), before)
        outsider = str(self.base / 'other-home/file')
        self.assertEqual(locations.binding(self.data).path(outsider), outsider)

    def test_runtime_receipt_survives_mount_change_and_tool_removal(self):
        runtime = self.mount / 'share/tool-runtime'
        prefix = runtime / 'envs/harness'
        prefix.mkdir(parents=True)
        (runtime / footprint.MARKER).write_bytes(footprint.marker(self.data))
        (prefix / 'keep.txt').write_text('runtime')
        registration = self.mount / '.conda/environments.txt'
        registration.parent.mkdir()
        other = str(self.base / 'unrelated-environment') + '\r\n'
        registration.write_bytes((str(prefix) + '\r\n' + other).encode())
        with mock.patch.object(sys, 'prefix', str(prefix)), mock.patch.object(footprint, 'user_home', return_value=self.mount):
            footprint.record(runtime, self.data)
        before = (runtime / footprint.RECEIPT).read_bytes()
        new = self.move()
        runtime = new / 'share/tool-runtime'
        reference = dist._read_json(self.data / 'runtime.json')
        plan = footprint.inspect(reference, self.data)
        self.assertEqual(plan['root'], str(runtime))
        self.assertEqual(plan['condaRegistration'], str(new / '.conda/environments.txt'))
        self.assertEqual((runtime / footprint.RECEIPT).read_bytes(), before)
        (self.data / 'active.json').unlink()
        self.assertEqual(footprint.inspect(reference, self.data)['root'], str(runtime))
        marker = (runtime / footprint.MARKER).read_bytes()
        (runtime / footprint.MARKER).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            footprint.inspect(reference, self.data)
        (runtime / footprint.MARKER).write_bytes(marker)
        self.assertEqual(footprint.cleanup(plan), [])
        self.assertEqual((new / '.conda/environments.txt').read_bytes(), other.encode())

    @unittest.skipUnless(os.name == 'posix', 'POSIX executable and HOME semantics')
    def test_entrypoint_and_home_path_survive_a_real_move(self):
        shell.register_path(self.bin, home=self.mount)
        new = self.move()
        command = 'source "$HOME/.bashrc"; harness-codex --version'
        result = subprocess.run(['/bin/bash', '-c', command], env={**os.environ, 'HOME': str(new)}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('fake-harness --version', result.stdout)
        before = self.snapshot()
        self.assertEqual(locations.repair_entrypoints(self.data)['writes'], 0)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_entrypoint_repair_resumes_after_interruption_and_preserves_edits(self):
        # Exercise the POSIX byte transition even on a Windows test host; retain
        # native filesystem/locking primitives rather than mocking file writes.
        mock_os = SimpleNamespace(**{**vars(os), 'name': 'posix'})
        patch = mock.patch.object(locations, 'os', mock_os)
        patch.start()
        self.addCleanup(patch.stop)
        entry = self.bin / 'harness-codex'
        old = ('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -B ' + shlex.quote(str(self.data / 'launcher.py')) + ' "$@"\n').encode()
        entry.write_bytes(old)
        active = dist._read_json(self.data / 'active.json')
        active['launchers'][str(entry)] = hashlib.sha256(old).hexdigest()
        dist._write_json(self.data / 'active.json', active)
        self.move()
        replace = shell._replace_profile
        def fail(path, before, after):
            if path.name == 'active.json':
                raise KeyboardInterrupt()
            return replace(path, before, after)
        with mock.patch.object(shell, '_replace_profile', side_effect=fail), self.assertRaises(KeyboardInterrupt):
            locations.repair_entrypoints(self.data)
        with self.assertRaisesRegex(ValueError, 'repair is pending'):
            dist.installed_status(self.data)
        entry = self.bin / 'harness-codex'
        saved = entry.read_bytes()
        entry.write_bytes(saved + b'# user edit\n')
        with self.assertRaisesRegex(ValueError, 'concurrent edits preserved'):
            locations.repair_entrypoints(self.data)
        entry.write_bytes(saved)
        self.assertTrue(locations.repair_entrypoints(self.data)['repaired'])
        self.assertFalse((self.data / '.entrypoint-migration.json').exists())
        dist.installed_status(self.data)


class HookExecutionTests(unittest.TestCase):
    def test_portable_hook_command_stays_identical_across_home_mounts(self):
        with tempfile.TemporaryDirectory() as temporary:
            commands = []
            for name in ('first mount', 'second mount'):
                home = Path(temporary) / name
                args = [str(home / '.local/runtime/bin/python'), '-B', str(home / '.local/tool/launcher.py'), '--no-update-check', 'maintenance', '--hook']
                with mock.patch.object(maintenance, 'user_home', return_value=home), \
                        mock.patch.object(maintenance, 'os', SimpleNamespace(name='posix')):
                    commands.append(maintenance._hook_command(args, portable=True))
            self.assertEqual(commands[0], commands[1])
            self.assertIn('${HOME}', commands[0])
            self.assertNotIn('mount', commands[0])

    def test_probe_uses_real_entrypoint_without_project_or_observation_writes(self):
        root = Path(__file__).resolve().parents[1]
        arguments = [sys.executable, '-B', str(root / 'harness.py'), '--no-update-check', 'maintenance', '--hook']
        command = subprocess.list2cmdline(arguments) if os.name == 'nt' else shlex.join(arguments)
        with tempfile.TemporaryDirectory() as temporary:
            maintenance.probe_hook(command, temporary)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_failed_probe_never_starts_native_trust(self):
        from harness_cli import hook_trust
        root = Path(__file__).resolve().parents[1]
        with mock.patch.object(maintenance, 'hook_command', return_value='missing-command'), \
                mock.patch.object(maintenance, 'install_hooks', return_value={'path': str(root / 'hooks.json')}), \
                mock.patch.object(maintenance, 'probe_hook', side_effect=ValueError('entrypoint failed')), \
                mock.patch.object(hook_trust, 'trust') as trust:
            report = hook_trust.prepare(root, root)
        self.assertEqual(report['status'], 'manual-review-required')
        self.assertIn('entrypoint failed', report['warning'])
        trust.assert_not_called()


class ShellEntrypointTests(unittest.TestCase):
    def test_real_shell_resolves_moved_layout_and_preserves_literal_arguments(self):
        bash = shutil.which('bash') or ('C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else None)
        if not bash or not Path(bash).is_file():
            self.skipTest('Bash is unavailable')
        class Location(PurePosixPath):
            def is_file(self):
                return False  # Fresh launcher generation; no active metadata yet.
        def shell_path(path):
            if os.name != 'nt':
                return path.as_posix()
            return subprocess.check_output([bash, '-c', 'cygpath -u "$1"', 'fixture', str(path)], text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "old home $literal's"
            binary = first / '.local/bin'
            root = first / '.local/share/tool'
            python = first / '.local/runtime/bin/python'
            for directory in (binary, root, python.parent):
                directory.mkdir(parents=True)
            python.write_bytes(b'#!/bin/sh\nprintf "%s\\n" "$0" "$@"\n')
            python.chmod(0o755)
            with mock.patch.object(locations, 'Path', Location), \
                    mock.patch.object(locations, 'checked_path', side_effect=Location), \
                    mock.patch.object(locations, 'os', SimpleNamespace(path=posixpath)), \
                    mock.patch('harness_cli.paths.user_home', return_value=Location(shell_path(first))):
                payload = locations.shell_entry(shell_path(root), shell_path(binary), shell_path(python), ('_codex',))
            (binary / 'codex').write_bytes(payload)
            second = first.with_name('new mount prefix')
            first.rename(second)
            command = shell_path(second / '.local/bin/codex')
            result = subprocess.run([bash, command, 'literal $HOME; task', '--help'], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertEqual(lines[1:], ['-B', shell_path(second / '.local/share/tool/launcher.py'), '_codex', 'literal $HOME; task', '--help'])
            self.assertNotIn('old home', result.stdout)
