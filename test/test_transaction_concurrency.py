"""Concurrent preparation, rollback and explicit recovery must keep ownership."""
import os
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from test_harness_tools import harness_state, harness_transaction as transaction


class TransactionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / 'project'
        self.root.mkdir()
        patch = mock.patch.dict(os.environ, {'HARNESS_LOCK_HOME': str(self.root.parent / 'locks')})
        patch.start()
        self.addCleanup(patch.stop)

    def prepare(self, *names):
        outputs = {f'.agents/skills/{name}/SKILL.md': name for name in names}
        return transaction.prepare_transaction(self.root, outputs, dict.fromkeys(outputs, 'create'),
                                               {}, {}, dict.fromkeys(outputs, 0o644), [])

    def test_other_preparation_cannot_replace_journal_during_failed_apply(self):
        first = self.prepare('alpha', 'beta')
        attempted, finished = threading.Event(), threading.Event()
        result, errors = [], []
        def prepare_second():
            attempted.set()
            try:
                result.append(self.prepare('gamma'))
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()
        worker = threading.Thread(target=prepare_second)
        write = harness_state.atomic_write_bytes
        def fail_second(path, data, **kwargs):
            if path == self.root / '.agents/skills/alpha/SKILL.md':
                write(path, data, **kwargs)
                worker.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.wait(.15))
                return
            if path == self.root / '.agents/skills/beta/SKILL.md':
                raise OSError('injected second write failure')
            write(path, data, **kwargs)
        try:
            with mock.patch.object(harness_state, 'atomic_write_bytes', side_effect=fail_second):
                with self.assertRaisesRegex(transaction.TransactionError, 'was rolled back.*removed=1'):
                    transaction.apply_transaction(self.root, first)
        finally:
            if worker.ident is not None:
                worker.join(timeout=12)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(result), 1)
        self.assertFalse((self.root / '.agents/skills/alpha/SKILL.md').exists())
        self.assertEqual(transaction.load_journal(self.root)['transactionId'], result[0]['transactionId'])
        transaction.apply_transaction(self.root, result[0])
        self.assertIsNone(harness_state.transaction_status(self.root))

    def test_stale_handle_cannot_apply_recover_or_clean_a_new_transaction(self):
        first = self.prepare('alpha')
        transaction.recover_transaction(self.root)
        second = self.prepare('beta')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for action in (lambda: transaction.apply_transaction(self.root, first),
                       lambda: transaction.recover_transaction(self.root, expected_id=first['transactionId']),
                       lambda: transaction._cleanup_transaction(self.root, first),
                       lambda: transaction._write_journal(self.root, first)):
            with self.assertRaisesRegex(transaction.TransactionError, 'ownership changed'):
                action()
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        transaction.apply_transaction(self.root, second)

    def test_recovery_rechecks_later_targets_after_each_restoration(self):
        paths = ['.agents/skills/alpha/SKILL.md', '.agents/skills/beta/SKILL.md']
        for relative in paths:
            target = self.root / relative
            target.parent.mkdir(parents=True)
            target.write_bytes(b'original')
        outputs = dict.fromkeys(paths, 'updated')
        modes = {path: harness_state.current_mode(self.root / path) for path in paths}
        journal = transaction.prepare_transaction(self.root, outputs, dict.fromkeys(paths, 'update'),
            dict.fromkeys(paths, harness_state.digest_bytes(b'original')), modes, modes, [])
        for relative in paths:
            (self.root / relative).write_bytes(b'updated')
        write = harness_state.atomic_write_bytes
        def external_edit_after_first_restore(path, data, **kwargs):
            write(path, data, **kwargs)
            if path == self.root / paths[1]:
                (self.root / paths[0]).write_bytes(b'external edit during recovery')
        with mock.patch.object(harness_state, 'atomic_write_bytes', side_effect=external_edit_after_first_restore):
            with self.assertRaisesRegex(transaction.TransactionError, 'changed during recovery'):
                transaction.recover_transaction(self.root)
        self.assertEqual((self.root / paths[0]).read_bytes(), b'external edit during recovery')
        self.assertEqual((self.root / paths[1]).read_bytes(), b'original')
        self.assertEqual(transaction.load_journal(self.root)['transactionId'], journal['transactionId'])
        (self.root / paths[0]).write_bytes(b'updated')
        self.assertEqual(transaction.recover_transaction(self.root)['restored'], 1)
        self.assertIsNone(harness_state.transaction_status(self.root))

    def test_same_id_with_a_changed_contract_cannot_be_overwritten(self):
        journal = self.prepare('alpha')
        path = transaction.journal_path(self.root)
        changed = json.loads(path.read_text())
        changed['operations'][0]['desiredSha256'] = 'f' * 64
        path.write_text(json.dumps(changed))
        before = path.read_bytes()
        with self.assertRaisesRegex(transaction.TransactionError, 'contract changed'):
            transaction._write_journal(self.root, journal)
        self.assertEqual(path.read_bytes(), before)

    def test_default_project_lock_does_not_require_home_writes(self):
        import harness_eval_lock
        from unittest.mock import patch
        environment = {key: value for key, value in os.environ.items() if key != 'HARNESS_LOCK_HOME'}
        with patch.dict(os.environ, environment, clear=True), patch.object(harness_eval_lock.tempfile, 'gettempdir', return_value=str(self.root.parent)):
            with transaction.project_lock(self.root):
                with transaction.project_lock(self.root):
                    self.assertEqual(list(self.root.iterdir()), [])
            self.assertEqual(len(list(self.root.parent.glob('harness-project-locks-*/*.lock'))), 1)


if __name__ == '__main__':
    unittest.main()
