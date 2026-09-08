"""Exercise registry preservation without changing the test user's real PATH."""
from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness_cli import windows_path


class Registry:
    HKEY_CURRENT_USER = 1
    KEY_READ, KEY_QUERY_VALUE, KEY_SET_VALUE = 1, 2, 4
    REG_SZ, REG_EXPAND_SZ = 1, 2

    def __init__(self, value=None):
        self.value = value
        self.writes = []
        self.created = 0

    def OpenKey(self, *args):
        return nullcontext(self)

    def QueryValueEx(self, key, name):
        if self.value is None:
            raise FileNotFoundError()
        return self.value

    def CreateKeyEx(self, *args):
        self.created += 1
        return nullcontext(self)

    def SetValueEx(self, key, name, reserved, kind, value):
        self.writes.append((name, kind, value))
        self.value = (value, kind)


class WindowsPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.binary = Path(temp.name) / 'command bin'
        self.registry = Registry(('C:\\user tools;%LOCALAPPDATA%\\Other;', 2))
        self.notify = mock.Mock(return_value=True)

    def register(self, **kwargs):
        return windows_path.register_path(self.binary, registry=self.registry, broadcast=self.notify, **kwargs)

    def test_preserves_raw_existing_value_type_and_is_idempotent(self):
        before = self.registry.value
        self.assertEqual(self.register()['writes'], 1)
        self.assertEqual(self.registry.value, (before[0] + str(self.binary), before[1]))
        self.assertEqual(self.register()['writes'], 0)
        self.assertEqual(len(self.registry.writes), 1)
        self.notify.assert_called_once()

    def test_unregister_keeps_other_entries_kind_and_rejects_stale_preview(self):
        self.registry.value = ('C:\\first;' + str(self.binary) + ';%USERPROFILE%\\tools', 1)
        preview = windows_path.unregister_path(self.binary, registry=self.registry, dry_run=True)
        self.assertFalse(self.registry.writes)
        original = self.registry.value
        self.registry.value = ('concurrent edit', 1)
        with self.assertRaisesRegex(ValueError, 'changed after'):
            windows_path.unregister_path(self.binary, registry=self.registry, expected=preview)
        self.assertFalse(self.registry.writes)
        self.registry.value = original
        result = windows_path.unregister_path(self.binary, registry=self.registry, broadcast=self.notify, expected=preview)
        self.assertEqual(result['writes'], 1)
        self.assertEqual(self.registry.value, ('C:\\first;%USERPROFILE%\\tools', 1))
        self.notify.assert_called_once()

    def test_unregister_preserves_user_path_expressions_and_missing_value(self):
        for value in (None, ('%HARNESS_TEST_BIN%', 2)):
            self.registry.value = value
            with mock.patch.dict(os.environ, {'HARNESS_TEST_BIN': str(self.binary)}):
                result = windows_path.unregister_path(self.binary, registry=self.registry, broadcast=self.notify)
            self.assertEqual(result['state'], 'preserved')
            self.assertEqual(self.registry.value, value)
            self.assertFalse(self.registry.writes)
        self.notify.assert_not_called()

    def test_absent_path_is_created_without_an_empty_search_entry(self):
        self.registry.value = None
        self.register()
        self.assertEqual(self.registry.value, (str(self.binary), 2))

    def test_duplicate_case_trailing_separator_and_variable_are_preserved(self):
        for value in (str(self.binary).upper() + '\\', '%HARNESS_TEST_BIN%', '"' + str(self.binary) + '"'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {'HARNESS_TEST_BIN': str(self.binary)}):
                self.registry.value = ('C:\\first;' + value, 1)
                self.assertEqual(self.register()['writes'], 0)
                self.assertEqual(self.registry.created, 0)
        self.notify.assert_not_called()

    def test_dry_run_never_creates_registry_key_or_notifies(self):
        before = self.registry.value
        self.assertEqual(self.register(dry_run=True)['state'], 'would-update')
        self.assertEqual(self.registry.value, before)
        self.assertEqual(self.registry.created, 0)
        self.notify.assert_not_called()

    def test_invalid_type_and_size_are_refused_before_writes(self):
        for value in ((b'bytes', 1), ('text', 7), ('x' * 32760, 2)):
            self.registry.value = value
            with self.assertRaises(ValueError):
                self.register()
        self.assertFalse(self.registry.writes)

    def test_unsafe_new_directory_is_refused(self):
        for value in ('bad;entry', 'bad%VAR%', 'bad\nentry', 'bad"entry'):
            self.binary = self.binary.parent / value
            with self.assertRaises(ValueError):
                self.register()
        self.assertEqual(self.registry.created, 0)

    def test_concurrent_change_is_preserved(self):
        original = self.registry.CreateKeyEx
        def changing(*args):
            self.registry.value = ('concurrent user change', 1)
            return original(*args)
        self.registry.CreateKeyEx = changing
        with self.assertRaisesRegex(ValueError, 'changed during'):
            self.register()
        self.assertEqual(self.registry.value, ('concurrent user change', 1))
        self.assertFalse(self.registry.writes)

    def test_notification_timeout_does_not_invalidate_registered_path(self):
        self.notify.return_value = False
        result = self.register()
        self.assertFalse(result['notified'])
        self.assertEqual(result['writes'], 1)


if __name__ == '__main__':
    unittest.main()
