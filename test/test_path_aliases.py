"""Selected directory aliases share identity; managed descendants never follow links."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from harness_cli import codex_integration, graft, jev, lifecycle, main, paths, project, project_installer
from test_harness_tools import harness_apply, harness_plan_builder, harness_state, minimal_plan
import harness_checkpoint
import harness_eval_lock
import harness_eval_store
import harness_external_skills
import harness_maintenance
import harness_routing_evidence
import harness_relay_receipt
import harness_runtime_receipt
import harness_ops

REPO = Path(__file__).resolve().parents[1]


class PathAliasTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.physical = self.base / 'physical space 한글'
        self.physical.mkdir()
        self.alias = self.base / 'alias'
        self.link(self.alias, self.physical)
        self.root = self.physical / 'project'
        self.root.mkdir()
        self.selected = self.alias / 'project'
        environment = mock.patch.dict(os.environ, {'HARNESS_STATE_HOME': str(self.base / 'state'),
            'HARNESS_GRAFT_HOME': str(self.base / 'retrieval'), 'HARNESS_LOCK_HOME': str(self.base / 'locks')})
        environment.start()
        self.addCleanup(environment.stop)

    def link(self, link, target):
        if os.name == 'nt':
            result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.addCleanup(lambda: link.rmdir() if os.path.lexists(link) else None)
        else:
            link.symlink_to(target, target_is_directory=True)
            self.addCleanup(lambda: link.unlink(missing_ok=True))

    def test_cli_install_status_and_remove_use_one_physical_project(self):
        for selected in (self.selected, self.root):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main.main(['--no-update-check', 'init', '--install-only', '--project', str(selected)], source_root=REPO), 0)
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        before = (self.root / 'pyproject.toml').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main.main(['--no-update-check', 'status', '--project', str(self.selected), '--json'], source_root=REPO), 0)
        self.assertEqual(json.loads(output.getvalue())['state'], 'configured')
        lifecycle.remove_project(self.selected, source_root=REPO, include_generator=True, dry_run=False)
        self.assertFalse((self.root / '.agents/skills/harness').exists())
        self.assertFalse((self.root / '.harness/manifest.json').exists())
        self.assertEqual((self.root / 'pyproject.toml').read_bytes(), before)

    def test_source_installer_entry_through_alias_keeps_managed_sources_checked(self):
        source_alias = self.base / 'source-alias'
        self.link(source_alias, REPO)
        result = subprocess.run([sys.executable, '-B', str(source_alias / 'install.py'),
            '--root', str(self.selected), '--dry-run'], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['valid'])
        self.assertFalse((self.root / '.agents').exists())

    def test_selected_root_alias_and_metadata_aliases(self):
        direct = self.base / 'project-link'
        self.link(direct, self.root)
        for resolver in (paths.project_root, harness_state.workspace_root):
            self.assertEqual(resolver(direct), self.root)
            self.assertEqual(resolver(self.selected), self.root)
            with self.assertRaisesRegex(ValueError, 'existing directory'):
                resolver(self.selected / 'missing')
        metadata = self.physical / '.git'
        metadata.mkdir()
        hidden = self.base / 'metadata-alias'
        self.link(hidden, metadata)
        for resolver in (paths.project_root, harness_state.workspace_root):
            for selected in (hidden, metadata / '..' / 'project'):
                with self.subTest(selected=selected), self.assertRaisesRegex(ValueError, 'Git metadata'):
                    resolver(selected)

    def test_managed_directory_links_remain_rejected_without_target_writes(self):
        outside = self.base / 'outside'
        outside.mkdir()
        marker = outside / 'keep.txt'
        marker.write_text('unchanged')
        self.link(self.root / '.agents', outside)
        with self.assertRaisesRegex(project_installer.InstallError, 'symlink|reparse'):
            project_installer.install(self.selected)
        self.assertEqual(list(outside.iterdir()), [marker])
        self.assertEqual(marker.read_text(), 'unchanged')

    def test_goal_and_plan_parent_aliases_preserve_physical_meaning(self):
        goal = self.physical / 'goal.md'
        goal.write_text('Project goal', encoding='utf-8')
        self.assertEqual(project._goal_input(SimpleNamespace(goal_file=self.alias / goal.name), project_installer),
                         project._goal_input(SimpleNamespace(goal_file=goal), project_installer))
        output = self.alias / 'plan.json'
        harness_plan_builder._write_json_atomic(output, {'fixture': True})
        self.assertEqual(json.loads((self.physical / output.name).read_text()), {'fixture': True})
        nested = self.physical / 'nested'
        nested.mkdir()
        nested_alias = self.base / 'nested-alias'
        self.link(nested_alias, nested)
        for resolver in (paths.external_location, harness_state.external_location):
            self.assertEqual(resolver(nested_alias / '..' / 'new.json'), (self.base if os.name == 'nt' else self.physical) / 'new.json')

    def test_maintenance_routing_jev_and_graft_share_alias_identity(self):
        harness_apply.apply_application(harness_apply.build_application(self.root, minimal_plan(self.root)))
        store = self.physical / 'state'
        maintenance = harness_maintenance.Maintenance(self.selected, self.alias / 'state')
        maintenance.configure(mode='suggest')
        self.assertEqual(harness_maintenance.Maintenance(self.root, store).status()['mode'], 'suggest')
        routing = harness_routing_evidence.RoutingEvidence(self.selected, self.alias / 'state')
        routing.configure(enabled=True)
        self.assertTrue(harness_routing_evidence.RoutingEvidence(self.root, store).status()['enabled'])
        self.assertEqual(graft.storage(self.selected), graft.storage(self.root))
        self.assertEqual(jev._path(self.selected), jev._path(self.root))
        child = self.root / 'child'
        child.mkdir()
        self.assertEqual(harness_maintenance.find_root(self.selected / 'child'), self.root)

    def test_alias_lock_paths_and_home_identity_do_not_split_locks(self):
        with mock.patch.dict(os.environ, {'HARNESS_LOCK_HOME': str(self.alias / 'locks')}), \
                mock.patch.object(harness_eval_lock.Path, 'home', return_value=self.alias):
            with harness_eval_lock.project_lock(self.selected):
                held = set(harness_eval_lock._held.paths)
                with mock.patch.dict(os.environ, {'HARNESS_LOCK_HOME': str(self.physical / 'locks')}):
                    with harness_eval_lock.project_lock(self.root):
                        self.assertEqual(set(harness_eval_lock._held.paths), held)
        self.assertEqual(len(list((self.physical / 'locks').glob('*.lock'))), 1)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(harness_eval_lock.FileLock, '__enter__') as enter, \
                mock.patch.object(harness_eval_lock.FileLock, '__exit__'), mock.patch.object(harness_eval_lock.Path, 'home', return_value=self.alias):
            with harness_eval_lock.project_lock(self.root):
                first = set(harness_eval_lock._held.paths)
            with mock.patch.object(harness_eval_lock.Path, 'home', return_value=self.physical):
                with harness_eval_lock.project_lock(self.root):
                    self.assertEqual(set(harness_eval_lock._held.paths), first)
            self.assertEqual(enter.call_count, 2)

    def test_state_root_link_or_replacement_is_not_adopted(self):
        target = self.base / 'state-target'
        target.mkdir()
        linked = self.physical / 'linked-state'
        self.link(linked, target)
        with self.assertRaises(harness_eval_store.StoreError):
            harness_eval_store.EvaluationStore(self.alias / linked.name)
        owned = self.physical / 'owned-state'
        store = harness_eval_store.EvaluationStore(self.alias / owned.name)
        self.link(owned, target)
        with self.assertRaises(harness_eval_store.StoreError):
            store._initialize_root()
        self.assertEqual(list(target.iterdir()), [])

    def test_checkpoint_and_external_skill_inventory_accept_project_alias(self):
        (self.root / 'input.txt').write_text('fixture')
        plan = {'schemaVersion': 1, 'tasks': [{'id': 'one', 'dependsOn': [], 'inputs': ['input.txt'],
                'outputs': ['output.txt'], 'context': {}, 'checks': [['unused-command']]}]}
        harness_checkpoint.operate(self.selected, self.alias / 'checkpoint', plan, 'init', 'first', keep_days=1)
        self.assertEqual(harness_checkpoint.operate(self.root, self.physical / 'checkpoint', plan, 'status', 'first'),
                         harness_checkpoint.operate(self.selected, self.alias / 'checkpoint', plan, 'status', 'first'))
        self.assertEqual(harness_external_skills.inventory(self.selected), harness_external_skills.inventory(self.root))

    def test_path_alias_to_owned_codex_is_never_recorded_as_original(self):
        from build import build_release
        owned = self.physical / 'codex-bin'
        external = self.base / 'official-bin'
        owned.mkdir()
        external.mkdir()
        name = 'codex.exe' if os.name == 'nt' else 'codex'
        for folder in (owned, external):
            binary = folder / name
            binary.write_bytes(b'fixture')
            binary.chmod(0o755)
        selected_path = os.pathsep.join(map(str, (self.alias / 'codex-bin', external)))
        self.assertEqual(Path(codex_integration.original_codex(self.physical, path=selected_path)), external / name)
        # Release inputs use the same root boundary; output leaves remain protected.
        with mock.patch.object(build_release, 'collect_source', return_value=('fixture', 'commit', {}, {})) as source, \
                mock.patch.object(build_release, 'write_artifacts') as publish:
            build_release.build(self.selected, self.alias / 'dist')
            self.assertEqual(source.call_args.args[0], self.root)
            self.assertEqual(publish.call_args.args[0], self.physical / 'dist')
        output_link = self.base / 'dist-link'
        self.link(output_link, external)
        with self.assertRaises(ValueError):
            build_release.build(self.selected, output_link)

    @unittest.skipUnless(os.name == 'posix', 'POSIX file symlinks')
    def test_input_output_file_links_and_loops_are_rejected(self):
        target = self.base / 'precious.json'
        target.write_text('unchanged')
        linked = self.physical / 'plan.json'
        linked.symlink_to(target)
        for module in (harness_plan_builder, harness_relay_receipt, harness_runtime_receipt):
            with self.subTest(module=module.__name__), self.assertRaises(ValueError):
                module._write_json_atomic(self.alias / linked.name, {'changed': True})
        with self.assertRaises(ValueError):
            project._goal_input(SimpleNamespace(goal_file=self.alias / linked.name), project_installer)
        self.assertEqual(target.read_text(), 'unchanged')
        dangling = self.physical / 'hooks.json'
        dangling.symlink_to(self.base / 'missing-hooks.json')
        with self.assertRaises(ValueError):
            harness_ops.command_hooks_template(SimpleNamespace(output=str(dangling)))
        self.assertFalse((self.base / 'missing-hooks.json').exists())
        loop = self.base / 'loop'
        loop.symlink_to(loop)
        for resolver in (paths.project_root, harness_state.workspace_root):
            with self.assertRaisesRegex(ValueError, 'resolvable path'):
                resolver(loop)

    @unittest.skipUnless(os.name == 'posix', 'POSIX installer runtime layout')
    def test_shell_runtime_and_python_agree_on_parent_traversal(self):
        manager = self.base / 'conda-fixture'
        manager.write_text('#!/bin/bash\nset -eu\nif [[ "$1" == env ]]; then echo "{}"; elif [[ "$1" == create ]]; then\n'
            '  shift; [[ "$1" == --prefix ]]; prefix=$2\n'
            '  mkdir -p "$prefix/conda-meta" "$prefix/bin"; touch "$prefix/conda-meta/history"\n'
            '  printf "#!/bin/sh\\nexit 0\\n" > "$prefix/bin/python"; chmod +x "$prefix/bin/python"\nfi\n')
        manager.chmod(0o755)
        selected = self.alias / 'install' / 'child' / '..'
        expected = paths.storage_location(selected)
        environment = {**os.environ, 'CONDA_EXE': str(manager), 'HOME': str(self.alias)}
        command = 'set -eu; install_log=$1; shift; finish_step() { :; }; start_step() { :; }; source "$1" "${@:2}"; printf "%s\\n" "$data_directory" "$runtime_root"'
        result = subprocess.run(['bash', '-c', command, 'fixture', str(self.base / 'log'),
            str(REPO / 'harness_cli/prepare_conda.sh'), '--data-dir', str(selected)], env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(expected), str(expected) + '-runtime'])
        self.assertTrue(Path(str(expected) + '-runtime/envs/harness/conda-meta/history').is_file())


if __name__ == '__main__':
    unittest.main()
