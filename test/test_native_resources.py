"""CI capacity checks preserve files, failed commands and the existing test scope."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from build.native_ui import resources


class NativeResourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.enterContext(mock.patch.dict(os.environ, {'RUNNER_ENVIRONMENT': 'github-hosted'}))
        self.enterContext(mock.patch.object(resources.platform, 'system', return_value='Linux'))
        self.memory = self.enterContext(mock.patch.object(resources, 'memory', return_value={'MemTotal': 8 * resources.GIB, 'SwapTotal': 4 * resources.GIB}))
        self.enterContext(mock.patch.object(resources.shutil, 'disk_usage', return_value=mock.Mock(free=34 * resources.GIB)))
        self.enterContext(mock.patch.object(resources, 'report'))

    def test_small_runner_adds_only_missing_swap_and_large_runner_needs_none(self):
        self.memory.side_effect = [{'MemTotal': 8 * resources.GIB, 'SwapTotal': 4 * resources.GIB}, {'SwapTotal': 8 * resources.GIB}]
        with mock.patch.object(resources.subprocess, 'run') as run:
            self.assertEqual(resources.prepare(self.root), 4 * resources.GIB + resources.mmap.PAGESIZE)
        self.assertEqual(run.call_count, 4)
        self.assertEqual(run.call_args_list[0].args[0], ['fallocate', '-l', str(4 * resources.GIB + resources.mmap.PAGESIZE), str(self.root / 'harness-native.swap')])
        self.assertEqual(run.call_args_list[1].args[0], ['sudo', '-n', 'chown', '0:0', str(self.root / 'harness-native.swap')])
        self.assertEqual(run.call_args.args[0], ['sudo', '-n', 'swapon', str(self.root / 'harness-native.swap')])
        self.memory.side_effect = None
        for values in ({'MemTotal': 16 * resources.GIB, 'SwapTotal': 0}, {'MemTotal': 8 * resources.GIB, 'SwapTotal': 8 * resources.GIB}):
            self.memory.return_value = values
            with mock.patch.object(resources.subprocess, 'run') as run:
                self.assertEqual(resources.prepare(self.root), 0)
                run.assert_not_called()

    def test_insufficient_disk_rejects_before_allocating_or_calling_sudo(self):
        with mock.patch.object(resources.shutil, 'disk_usage', return_value=mock.Mock(free=28 * resources.GIB)):
            with mock.patch.object(resources.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, '25 GiB'):
                resources.prepare(self.root)
            run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unrelated_file_and_nonhosted_machines_are_preserved(self):
        path = self.root / 'harness-native.swap'
        path.write_bytes(b'keep')
        with mock.patch.object(resources.subprocess, 'run') as run, self.assertRaises(FileExistsError):
            resources.prepare(self.root)
        run.assert_not_called()
        self.assertEqual(path.read_bytes(), b'keep')
        with mock.patch.dict(os.environ, {'RUNNER_ENVIRONMENT': 'self-hosted'}), self.assertRaisesRegex(ValueError, 'disposable'):
            resources.prepare(self.root)

    def test_failed_swap_activation_never_continues_build(self):
        with mock.patch.object(resources.subprocess, 'run', side_effect=[mock.Mock(), mock.Mock(), mock.Mock(), subprocess.CalledProcessError(1, 'swapon')]):
            with self.assertRaises(subprocess.CalledProcessError):
                resources.prepare(self.root)

    def test_usable_swap_excludes_header_and_keeps_the_disk_reserve(self):
        for page in (4096, 65536):
            for existing in (3 * resources.GIB - page, 8 * resources.GIB - 1):
                with self.subTest(page=page, existing=existing), mock.patch.object(resources.mmap, 'PAGESIZE', page):
                    values = {'MemTotal': 8 * resources.GIB, 'SwapTotal': existing}
                    size = resources.swap_bytes(values, 40 * resources.GIB)
                    usable = size // page * page - page
                    self.assertGreaterEqual(existing + usable, 8 * resources.GIB)
                    self.assertGreaterEqual(size, 10 * page)
                    with self.assertRaises(ValueError):
                        resources.swap_bytes(values, 25 * resources.GIB + size - 1)

    def test_prepare_verifies_actual_usable_bytes_instead_of_assuming_activation(self):
        before = {'MemTotal': 8 * resources.GIB, 'SwapTotal': 3 * resources.GIB - 4096}
        self.memory.return_value = before.copy()
        allocated = []
        def activate(command, **kwargs):
            if command[0] == 'fallocate':
                allocated.append(int(command[2]))
            if 'swapon' in command:
                self.memory.return_value = {**before, 'SwapTotal': before['SwapTotal'] + allocated[0] - 4096}
        with mock.patch.object(resources.mmap, 'PAGESIZE', 4096), mock.patch.object(resources.subprocess, 'run', side_effect=activate):
            resources.prepare(self.root)
        self.assertEqual(self.memory.return_value['SwapTotal'], 8 * resources.GIB)
        other = self.root / 'not-activated'
        other.mkdir()
        self.memory.return_value = before
        with mock.patch.object(resources.subprocess, 'run'), self.assertRaisesRegex(ValueError, 'usable bytes'):
            resources.prepare(other)

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('mkswap'), 'Real swap-header verification requires Linux mkswap')
    def test_real_mkswap_header_has_the_required_usable_capacity(self):
        # Format small temporary files without activating swap or requiring root.
        # last_page is the native-endian uint32 at offset 1028 in swap_header.
        for page in (4096, 65536):
            for missing in (16 * 1024 * 1024, 1):
                with self.subTest(page=page, missing=missing), mock.patch.object(resources.mmap, 'PAGESIZE', page):
                    existing = 8 * resources.GIB - missing
                    size = resources.swap_bytes({'MemTotal': 8 * resources.GIB, 'SwapTotal': existing}, 40 * resources.GIB)
                    path = self.root / f'swap-{page}-{missing}'
                    path.write_bytes(b'\0' * size)
                    path.chmod(0o600)
                    subprocess.run(['mkswap', '--pagesize', str(page), str(path)], check=True, capture_output=True, timeout=30)
                    with path.open('rb') as stream:
                        header = stream.read(page)
                    self.assertEqual(header[-10:], b'SWAPSPACE2')
                    self.assertGreaterEqual(existing + struct.unpack_from('=I', header, 1028)[0] * page, 8 * resources.GIB)

    def test_patch_evidence_handles_absent_checkout_and_retains_real_git_errors(self):
        bash = shutil.which('bash')
        if not bash and os.name == 'nt':
            candidate = Path(shutil.which('git')).parents[1] / 'bin/bash.exe'
            bash = str(candidate) if candidate.is_file() else None
        if not bash:
            self.skipTest('Bash is unavailable')
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/native-ui.yml').read_text()
        step = workflow.split('      - name: Preserve build and patch review evidence\n', 1)[1].split('      - uses:', 1)[0]
        script = textwrap.dedent(step.split('        run: |\n', 1)[1])
        def collect():
            return subprocess.run([bash, '-e', '-c', script], env={**os.environ, 'RUNNER_TEMP': self.root.as_posix()},
                                  text=True, capture_output=True, timeout=30)
        missing = collect()
        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertIn('unavailable', missing.stdout)
        self.assertFalse((self.root / 'codex-ui-patch.diff').exists())
        checkout = self.root / 'codex-ui'
        subprocess.run(['git', 'init', str(checkout)], check=True, capture_output=True, timeout=30)
        present = collect()
        self.assertEqual(present.returncode, 0, present.stderr)
        self.assertTrue((self.root / 'codex-ui-patch.diff').is_file())
        (checkout / '.git/config').write_text('invalid Git configuration')
        self.assertNotEqual(collect().returncode, 0)

    def test_command_failure_and_termination_are_not_converted_to_success(self):
        for code in (0, 7, -15):
            with mock.patch.object(resources.subprocess, 'run', return_value=mock.Mock(returncode=code)) as run:
                self.assertEqual(resources.run(self.root, ['cargo', 'nextest', 'run', '--locked']), code)
                run.assert_called_once_with(['cargo', 'nextest', 'run', '--locked'], check=False)
        with mock.patch.object(resources.subprocess, 'run', side_effect=OSError('not installed')):
            with self.assertRaises(OSError):
                resources.run(self.root, ['cargo'])

    def test_real_child_exit_is_preserved_without_resource_access(self):
        import sys
        self.assertEqual(resources.run(self.root, [sys.executable, '-B', '-c', 'raise SystemExit(17)']), 17)


if __name__ == '__main__':
    unittest.main()
