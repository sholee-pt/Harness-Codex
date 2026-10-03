"""A release must never attach new source bytes to a different existing tag."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from build import release_publish


class ReleasePublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root / 'dist'
        self.dist.mkdir()
        self.commit, self.tag = 'b' * 40, 'v0.33.0-beta'
        (self.dist / 'build.json').write_text(json.dumps({'version': self.tag[1:], 'commit': self.commit,
            'developmentBuild': False, 'platforms': ['linux']}))
        self.notes = self.root / 'notes.md'
        self.notes.write_text('Verified release\n')

    def publish(self):
        with contextlib.redirect_stdout(io.StringIO()):
            release_publish.publish(self.dist, self.commit, self.tag, self.notes, 'sholee-pt/Harness-Codex')

    def test_mismatching_existing_tag_refuses_publication_without_moving_tag(self):
        with mock.patch.object(release_publish, 'gh', return_value=json.dumps({'object': {'type': 'commit', 'sha': 'c' * 40}})) as gh:
            with self.assertRaisesRegex(ValueError, 'another source commit'):
                self.publish()
        self.assertEqual(gh.call_count, 1)
        self.assertTrue(all(call.args[0] == 'api' and 'POST' not in call.args for call in gh.call_args_list))

    def test_existing_lightweight_or_annotated_tag_is_resolved_to_commit(self):
        for kind in ('commit', 'tag'):
            direct = json.dumps({'object': {'type': 'commit', 'sha': self.commit}})
            responses = [direct, ''] if kind == 'commit' else [json.dumps({'object': {'type': kind, 'sha': 'a' * 40}}), direct, '']
            with self.subTest(kind=kind), mock.patch.object(release_publish, 'gh', side_effect=responses) as gh:
                self.publish()
                self.assertEqual(gh.call_count, len(responses))
                self.assertIn('/git/ref/tags/' + self.tag, gh.call_args_list[0].args[1])
                if kind == 'tag':
                    self.assertIn('/git/tags/' + 'a' * 40, gh.call_args_list[1].args[1])
                self.assertIn('--verify-tag', gh.call_args.args)
                self.assertFalse(any('POST' in call.args for call in gh.call_args_list))

    def test_nested_annotations_follow_only_exact_objects_not_same_named_branch(self):
        responses = [json.dumps({'object': {'type': 'tag', 'sha': identity * 40}}) for identity in ('a', 'c')]
        responses += [json.dumps({'object': {'type': 'commit', 'sha': self.commit}}), '']
        with mock.patch.object(release_publish, 'gh', side_effect=responses) as gh:
            self.publish()
        endpoints = [call.args[1] for call in gh.call_args_list[:-1]]
        self.assertEqual(endpoints, ['repos/sholee-pt/Harness-Codex/' + suffix for suffix in (
            'git/ref/tags/' + self.tag, 'git/tags/' + 'a' * 40, 'git/tags/' + 'c' * 40)])

    def test_cyclic_annotation_refuses_publication_without_writes(self):
        with mock.patch.object(release_publish, 'gh', return_value=json.dumps({'object': {'type': 'tag', 'sha': 'a' * 40}})) as gh:
            with self.assertRaisesRegex(ValueError, 'bounded exact commit'):
                self.publish()
        self.assertEqual(gh.call_count, 2)
        self.assertTrue(all(call.args[0] == 'api' and 'POST' not in call.args for call in gh.call_args_list))

    def test_absent_tag_is_created_at_exact_commit_then_rechecked(self):
        with mock.patch.object(release_publish, 'gh', side_effect=[None, '{}', json.dumps({'object': {'type': 'commit', 'sha': self.commit}}), '']) as gh:
            self.publish()
        self.assertIn('sha=' + self.commit, gh.call_args_list[1].args)
        self.assertIn('ref=refs/tags/' + self.tag, gh.call_args_list[1].args)
        self.assertIn('--verify-tag', gh.call_args.args)

    def test_mismatching_local_build_never_queries_or_writes_github(self):
        (self.dist / 'build.json').write_text('{}')
        with mock.patch.object(release_publish, 'gh') as gh, self.assertRaises(ValueError):
            self.publish()
        gh.assert_not_called()
