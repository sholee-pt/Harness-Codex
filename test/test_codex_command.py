"""Current named command and compatibility are verified with actual installs."""
from pathlib import Path
import sys
import tempfile
import unittest

from harness_cli import distribution as dist
from harness_cli.main import build_parser
from test_cli_distribution import source, files

ROOT = Path(__file__).resolve().parents[1]


class CodexCommandTests(unittest.TestCase):
    def test_fresh_install_owns_only_codex_command_and_repeats_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            src = source(base / 'source', version='9.7')
            data, binary = base / 'data', base / 'bin'
            result = dist.install_tool(src, data, binary, python_executable=sys.executable)
            self.assertEqual(result['command'], 'harness-codex')
            self.assertTrue((binary / 'harness-codex').is_file())
            self.assertFalse((binary / 'harness').exists())
            before = files(base)
            dist.install_tool(src, data, binary, python_executable=sys.executable)
            self.assertEqual(files(base), before)

    def test_config_and_legacy_alias_share_one_project_handler(self):
        parser = build_parser(ROOT)
        for name in ['config', 'configure']:
            args = parser.parse_args([name, '--project', 'selected', '--goal', 'purpose'])
            self.assertEqual(args.command, 'configure')
            self.assertEqual(args.goal, 'purpose')
        self.assertEqual(parser.prog, 'harness-codex')

    def test_existing_legacy_command_is_preserved_on_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data, binary = base / 'data', base / 'bin'
            old = source(base / 'old', version='9.6')
            dist.install_tool(old, data, binary, python_executable=sys.executable)
            original = (binary / 'harness').read_bytes()
            new = source(base / 'new', version='9.7', commit='b' * 40)
            dist.install_tool(new, data, binary, python_executable=sys.executable)
            self.assertEqual((binary / 'harness').read_bytes(), original)
            self.assertEqual(dist.installed_status(data)['version'], '9.7')
