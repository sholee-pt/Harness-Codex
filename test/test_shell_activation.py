"""Consent-gated shell refresh preserves the project environment and CLI result."""
import argparse
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from harness_cli import shell
from harness_cli.presentation import JSON_MODE


class ShellActivationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (self.home / '.bashrc').write_bytes(b'# user startup\n')
        self.stack.enter_context(mock.patch.object(shell, 'os', SimpleNamespace(name='posix')))
        self.stack.enter_context(mock.patch.object(shell.Path, 'home', return_value=self.home))
        terminal = SimpleNamespace(isatty=lambda: True)
        self.stack.enter_context(mock.patch.object(shell, 'sys', SimpleNamespace(stdin=terminal, stdout=terminal, stderr=io.StringIO())))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(mock.patch.object(shell.shutil, 'which', return_value='/bin/bash'))
        self.launch = self.stack.enter_context(mock.patch.object(shell.subprocess, 'run', return_value=SimpleNamespace(returncode=0)))
        token = JSON_MODE.set(False)
        self.addCleanup(JSON_MODE.reset, token)

    def test_enter_reads_bashrc_in_project_child_without_mutating_parent(self):
        before = dict(os.environ)
        with mock.patch('builtins.input', return_value=''):
            shell.offer_activation(cwd=self.home)
        args, kwargs = self.launch.call_args
        self.assertEqual(args[0], ['/bin/bash', '--rcfile', str(self.home / '.bashrc'), '-i'])
        self.assertEqual(kwargs['cwd'], self.home)
        self.assertEqual(kwargs['env'].get('CONDA_PREFIX'), before.get('CONDA_PREFIX'))
        self.assertEqual(dict(os.environ), before)
        self.assertEqual((self.home / '.bashrc').read_bytes(), b'# user startup\n')

    def test_no_eof_and_interrupt_do_not_open_shell(self):
        for answer in ('no', EOFError(), KeyboardInterrupt()):
            with self.subTest(answer=answer), mock.patch('builtins.input', side_effect=[answer]):
                shell.offer_activation()
        self.launch.assert_not_called()

    def test_skip_json_and_redirected_input_do_not_prompt_or_launch(self):
        with mock.patch('builtins.input', side_effect=AssertionError('Unexpected prompt')):
            shell.offer_activation(mode='skip')
            JSON_MODE.set(True)
            shell.offer_activation()
            JSON_MODE.set(False)
            shell.sys.stdin = SimpleNamespace(isatty=lambda: False)
            shell.offer_activation(mode='shell')
        self.launch.assert_not_called()

    def test_explicit_shell_and_child_failure_preserve_successful_setup(self):
        self.launch.return_value.returncode = 4
        with mock.patch('builtins.input', side_effect=AssertionError('Unexpected prompt')):
            self.assertIsNone(shell.offer_activation(mode='shell'))
        self.assertIn('Harness remains configured', shell.sys.stderr.getvalue())

    def test_init_offer_follows_successful_integration_and_failure_never_opens_shell(self):
        from harness_cli import project
        parser = argparse.ArgumentParser()
        project.register_project_commands(parser.add_subparsers(dest='command', required=True))
        args = parser.parse_args(['init', '--project', str(self.home)])
        with mock.patch('harness_cli.codex_integration.install', return_value={'nextStep': 'Ready'}) as install, mock.patch('builtins.input', return_value=''):
            project._configure_integration(args, self.home)
            install.assert_called_once()
            self.launch.assert_called_once()
            self.launch.reset_mock()
            install.side_effect = ValueError('Integration failed')
            with self.assertRaisesRegex(ValueError, 'Integration failed'):
                project._configure_integration(args, self.home)
            self.launch.assert_not_called()
            args.no_codex_integration = True
            project._configure_integration(args, self.home)
            self.launch.assert_not_called()


@unittest.skipUnless(os.name == 'posix', 'Linux interactive shell integration')
class LiveShellActivationTests(unittest.TestCase):
    def test_real_bash_reads_startup_and_retains_project_environment(self):
        import pty
        import select
        import time
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = home / 'project with spaces'
            project.mkdir()
            (home / '.bashrc').write_text('printf "ACTIVATED:%s:%s\\n" "$CONDA_DEFAULT_ENV" "$PWD"\nexit 0\n')
            master, slave = pty.openpty()
            command = [sys.executable, '-B', '-c', 'from harness_cli.shell import offer_activation; import sys; offer_activation(mode="shell", cwd=sys.argv[1])', str(project)]
            child = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, env=os.environ | {'HOME': str(home), 'CONDA_DEFAULT_ENV': 'project-env'})
            os.close(slave)
            output = b''
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            block = os.read(master, 65536)
                        except OSError:
                            break
                        if not block:
                            break
                        output += block
                    elif child.poll() is not None:
                        break
                self.assertEqual(child.wait(timeout=3), 0, output.decode())
                self.assertIn(f'ACTIVATED:project-env:{project}'.encode(), output)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                os.close(master)
