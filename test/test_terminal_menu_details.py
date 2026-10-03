from __future__ import annotations

from contextlib import contextmanager, nullcontext
import io
import os
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

from harness_cli import presentation, terminal_menu


class Terminal(io.StringIO):
    def isatty(self):
        return True

    def fileno(self):
        return 0


class TerminalMenuDetails(unittest.TestCase):
    def menu(self, labels, keys, *, summary=(), back=True, size=(40, 8), on_read=None, plain_answer=''):
        output, frames, inputs = Terminal(), [], iter(keys)
        position = 0
        def read():
            nonlocal position
            text = output.getvalue()
            frames.append(re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text[position:]).replace('\r', ''))
            position = len(text)
            if on_read:
                on_read(len(frames))
            return next(inputs)
        progress = presentation.Progress('settings', stream=output)
        with mock.patch.object(sys, 'stdin', Terminal()), mock.patch.dict(os.environ, {'TERM': 'xterm', 'NO_COLOR': '1'}), \
                mock.patch.object(terminal_menu, 'keyboard', return_value=nullcontext(read)), \
                mock.patch.object(terminal_menu.shutil, 'get_terminal_size', side_effect=lambda *a, **kw: os.terminal_size(size)), \
                mock.patch.object(progress, 'ask', return_value=plain_answer):
            choice = terminal_menu.choose(progress, 'Model and permissions', labels, back=back, summary=summary)
        self.assertFalse(progress.paused)
        self.assertNotIn('\x1b[1;36m', output.getvalue())
        return choice, frames

    def test_narrow_details_preserve_distinct_models_and_permission_summary(self):
        labels = ['Provider catalog reasoning model (model-fast)', 'Provider catalog reasoning model (model-quality)']
        choice, frames = self.menu(labels, ['\t', '\t', '\t', 'down', '\t', '\r'],
                                   summary=['Model: current-model', 'Permissions: workspace-write / on-request'])
        self.assertEqual(choice, 1)
        self.assertIn('…', frames[0])
        self.assertIn('1/3', frames[0])
        text = ''.join(''.join(frame.splitlines()) for frame in frames)
        for expected in ('model-fast', 'model-quality', 'Permissions: workspace-write / on-request'):
            self.assertIn(expected, text)
        for frame in frames:
            for hint in ('Up/Down: select', 'Enter: accept', 'Ctrl+C: cancel', 'Left: back', 'Tab:'):
                self.assertIn(hint, frame)
            self.assertLessEqual(len(frame.strip().splitlines()), 7)
            self.assertTrue(all(len(line) <= 39 for line in frame.splitlines()))

    def test_details_pages_do_not_change_selection_and_left_still_goes_back(self):
        labels = ['Long description ' * 20, 'Another model']
        choice, frames = self.menu(labels, ['\t', '\t', '\r'])
        self.assertEqual(choice, 0)
        self.assertIn('Tab: next/list', frames[-1])
        choice, _ = self.menu(labels, ['\t', 'left'])
        self.assertEqual(choice, -1)

    def test_detail_navigation_updates_selection_and_ignores_escape(self):
        choice, frames = self.menu(['First model', 'Second model'], ['\t', 'down', '\x1b', '\r'])
        self.assertEqual(choice, 1)
        self.assertIn('Second model', frames[-1])
        self.assertNotIn('First model', frames[-1])

    def test_small_resize_preserves_selection_in_plain_fallback(self):
        size = [40, 8]
        def resize(count):
            size[:] = [20, 6]
        choice, frames = self.menu(['First', 'Second'], ['down'], size=size, on_read=resize)
        self.assertEqual(choice, 1)
        self.assertEqual(len(frames), 1)
        choice, frames = self.menu(['First', 'Second'], [], size=(20, 6), plain_answer='1')
        self.assertEqual(choice, 1)
        self.assertEqual(frames, [])

    def test_small_fallback_restores_keyboard_before_full_text_input(self):
        output, raw = Terminal(), [False]
        progress = presentation.Progress('settings', stream=output)
        @contextmanager
        def keyboard():
            raw[0] = True
            try:
                yield mock.Mock(side_effect=AssertionError('Small screen must use plain input'))
            finally:
                raw[0] = False
        def answer(prompt):
            self.assertFalse(raw[0])
            self.assertIn('Provider catalog model (complete-identifier)', output.getvalue())
            self.assertIn('Permissions: workspace-write / on-request', output.getvalue())
            self.assertIn('b: back', prompt)
            return 'b'
        with mock.patch.object(sys, 'stdin', Terminal()), mock.patch.dict(os.environ, {'TERM': 'xterm'}), \
                mock.patch.object(terminal_menu, 'keyboard', keyboard), mock.patch.object(progress, 'ask', side_effect=answer), \
                mock.patch.object(terminal_menu.shutil, 'get_terminal_size', return_value=os.terminal_size((20, 6))):
            self.assertEqual(terminal_menu.choose(progress, 'Model', ['Provider catalog model (complete-identifier)'], back=True,
                                                 summary=['Permissions: workspace-write / on-request']), -1)

    def test_unicode_wrap_preserves_wide_and_combining_characters(self):
        value = '한글 e\u0301 中文'
        rows = terminal_menu.wrapped_rows(value, 4)
        self.assertEqual(rows, ['한글', ' e\u0301 ', '中文'])
        self.assertEqual(''.join(rows), value)
        self.assertEqual(terminal_menu.clipped_row('한글ABC', 6), '한글A…')
        self.assertEqual(terminal_menu.wrapped_rows('한글\n\nA\tB', 4), ['한글', '', 'A B'])
        with self.assertRaises(ValueError):
            terminal_menu.wrapped_rows('한글', 1)

    def test_plain_fallback_keeps_full_text_and_normalizes_eof_to_cancellation(self):
        output = Terminal()
        progress = presentation.Progress('settings', stream=output)
        with mock.patch.object(sys, 'stdin', Terminal()), mock.patch.dict(os.environ, {'TERM': 'dumb'}), \
                mock.patch.object(progress, 'ask', side_effect=EOFError):
            with self.assertRaisesRegex(KeyboardInterrupt, 'Terminal input closed'):
                terminal_menu.choose(progress, 'Model', ['A complete model identifier'], summary=['Permissions: read-only / on-request'])
        self.assertIn('A complete model identifier', output.getvalue())
        self.assertIn('Permissions: read-only / on-request', output.getvalue())
        self.assertNotIn('\x1b', output.getvalue())

    @unittest.skipUnless(os.name == 'posix', 'POSIX pseudoterminal')
    def test_narrow_details_work_over_real_pseudoterminal(self):
        import fcntl
        import pty
        import select
        import struct
        import subprocess
        import termios
        import time
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 8, 40, 0, 0))
        environment = {**os.environ, 'TERM': 'xterm', 'NO_COLOR': '1', 'COLUMNS': '40', 'LINES': '8'}
        script = ('from harness_cli.presentation import Progress; from harness_cli.terminal_menu import choose; '
                  'print("SELECTED:", choose(Progress("probe"), "Model", '
                  '["Provider catalog reasoning model (model-fast)", "Provider catalog reasoning model (model-quality)"], back=True))')
        process = subprocess.Popen([sys.executable, '-B', '-c', script], cwd=Path(__file__).resolve().parents[1], env=environment,
                                   stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        data, stage, deadline = b'', 0, time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        block = os.read(master, 8192)
                    except OSError:
                        break
                    data += block
                    if stage == 0 and b'Tab: details' in data:
                        os.write(master, b'\x1b[B\t')
                        stage = 1
                    elif stage == 1 and b'Tab: next/list' in data:
                        os.write(master, b'\r')
                        stage = 2
                if process.poll() is not None and b'SELECTED:' in data:
                    break
            self.assertEqual(process.wait(timeout=2), 0)
            text = re.sub(rb'\x1b\[[0-9;]*[A-Za-z]', b'', data).replace(b'\r', b'').replace(b'\n', b'')
            self.assertIn(b'model-quality', text)
            self.assertIn(b'Left: back', text)
            self.assertIn(b'Ctrl+C: cancel', text)
            self.assertIn(b'SELECTED: 1', text)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)


if __name__ == '__main__':
    unittest.main()
