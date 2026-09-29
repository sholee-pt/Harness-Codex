"""Selective native trust cleanup without changing user configuration."""
import unittest

from harness_cli import hook_state


class HookStateTests(unittest.TestCase):
    def record(self, before, after):
        saved = {'owner': 'harness-maintenance-v1', 'command': 'owned-command'}
        pending = hook_state.begin_trust(saved, before, {'owned': {'trusted_hash': 'new', 'enabled': True}})
        return hook_state.finish_trust(pending, after, ['owned'])['trust']

    def test_removes_added_state_and_preserves_other_tables_and_comments(self):
        before = b'# user\nmodel = "native"\n'
        after = before + b'\n[hooks.state.owned]\ntrusted_hash = "new"\nenabled = true\n'
        current = after + b'\n[hooks.state.other]\nenabled = false\n# keep\n'
        result, warnings = hook_state.restore_trust(current, self.record(before, after))
        self.assertEqual(result, before + b'\n\n[hooks.state.other]\nenabled = false\n# keep\n')
        self.assertEqual(warnings, [])

    def test_restores_previous_user_state_without_rewriting_other_configuration(self):
        before = b'[hooks.state."owned"]\nenabled = false\ntrusted_hash = "old"\n'
        after = b'[hooks.state."owned"]\nenabled = true\ntrusted_hash = "new"\n'
        current = after + b'\n[unrelated]\nvalue = 1\n'
        result, warnings = hook_state.restore_trust(current, self.record(before, after))
        self.assertEqual(result, before + b'\n[unrelated]\nvalue = 1\n')
        self.assertEqual(warnings, [])

    def test_later_user_edits_and_deletions_are_preserved(self):
        after = b'[hooks.state.owned]\ntrusted_hash = "new"\nenabled = true\n'
        records = self.record(b'', after)
        for current in (after.replace(b'true', b'false'), after + b'# user comment\n', b''):
            result, warnings = hook_state.restore_trust(current, records)
            self.assertEqual(result, current)
            self.assertEqual(bool(warnings), bool(current))

    def test_repeated_updates_keep_original_baseline_but_rebase_user_edits(self):
        before = b'[hooks.state.owned]\nenabled = false\n'
        after = b'[hooks.state.owned]\ntrusted_hash = "new"\nenabled = true\n'
        records = self.record(before, after)
        saved = {'owner': 'harness-maintenance-v1', 'command': 'owned-command', 'trust': records}
        pending = hook_state.begin_trust(saved, after, {'owned': {'trusted_hash': 'next', 'enabled': True}})
        self.assertEqual(pending['trust']['owned']['before'], before.decode())
        edited = after.replace(b'true', b'false')
        pending = hook_state.begin_trust(saved, edited, {'owned': {'trusted_hash': 'next', 'enabled': True}})
        self.assertEqual(pending['trust']['owned']['before'], edited.decode())

    def test_unconfirmed_write_remains_recorded_for_manual_review(self):
        saved = {'owner': 'harness-maintenance-v1', 'command': 'owned-command'}
        pending = hook_state.begin_trust(saved, b'', {'owned': {'trusted_hash': 'new', 'enabled': True}})
        current = b'[hooks.state.owned]\ntrusted_hash = "new"\nenabled = true\n'
        result, warnings = hook_state.restore_trust(current, pending['trust'])
        self.assertEqual(result, current)
        self.assertEqual(len(warnings), 1)

    def test_inline_layout_is_refused_before_native_mutation(self):
        saved = {'owner': 'harness-maintenance-v1', 'command': 'owned-command'}
        with self.assertRaisesRegex(ValueError, 'layout'):
            hook_state.begin_trust(saved, b'[hooks]\nstate = {owned = {enabled = false}}\n', {'owned': {'enabled': True}})

    def test_header_like_multiline_content_cannot_authorize_unrelated_changes(self):
        before = b'message = """\n[hooks.state.owned]\n"""\n'
        after = before + b'\n[hooks.state.owned]\ntrusted_hash = "new"\nenabled = true\n'
        records = self.record(before, after)
        result, warnings = hook_state.restore_trust(after, records)
        self.assertEqual(result, before + b'\n')
        self.assertEqual(warnings, [])
