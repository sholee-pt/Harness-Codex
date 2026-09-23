"""CI capacity checks preserve files, failed commands and the existing test scope."""
import os
from pathlib import Path
import subprocess
import tempfile
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
            self.assertEqual(resources.prepare(self.root), 4 * resources.GIB)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[0].args[0], ['fallocate', '-l', str(4 * resources.GIB), str(self.root / 'harness-native.swap')])
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
        with mock.patch.object(resources.subprocess, 'run', side_effect=[mock.Mock(), mock.Mock(), subprocess.CalledProcessError(1, 'swapon')]):
            with self.assertRaises(subprocess.CalledProcessError):
                resources.prepare(self.root)

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
