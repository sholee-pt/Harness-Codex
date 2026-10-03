"""A release must never attach new source bytes to a different existing tag."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest import mock

from build import release_publish
from build.artifacts import write_artifacts


class ReleasePublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root / 'dist'
        self.dist.mkdir()
        self.commit, self.tag = 'b' * 40, 'v0.33.0-beta'
        self.files = {'harness.py': b'# committed source\n', '_release.json': json.dumps({
            'version': self.tag[1:], 'commit': self.commit, 'runtime': 'codex'}).encode()}
        self.bootstraps = {'install_harness_codex.sh': b'VERSION=0.12.0-beta\n',
                           'install_harness_codex.ps1': b"$version = '0.12.0-beta'\n# Harness for Codex 0.12.0-beta Windows installer.\n"}
        write_artifacts(self.dist, self.tag[1:], self.commit, self.files, self.bootstraps)
        patcher = mock.patch.object(release_publish, 'collect_source', return_value=(
            self.tag[1:], self.commit, self.files.copy(), self.bootstraps))
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_missing_or_unrelated_assets_never_query_github(self):
        for name in ('SHA256SUMS', 'install_harness_codex.sh', f'harness-codex-{self.tag[1:]}-linux.tar.gz'):
            with self.subTest(name=name):
                path = self.dist / name
                content = path.read_bytes()
                path.unlink()
                with mock.patch.object(release_publish, 'gh') as gh, self.assertRaisesRegex(ValueError, 'exactly'):
                    self.publish()
                gh.assert_not_called()
                path.write_bytes(content)
        (self.dist / 'private-note.txt').write_text('must not upload')
        with mock.patch.object(release_publish, 'gh') as gh, self.assertRaisesRegex(ValueError, 'exactly'):
            self.publish()
        gh.assert_not_called()

    def test_checksums_and_immutable_source_are_both_required(self):
        bootstrap = self.dist / 'install_harness_codex.sh'
        bootstrap.write_bytes(bootstrap.read_bytes() + b'# changed\n')
        with mock.patch.object(release_publish, 'gh') as gh, self.assertRaisesRegex(ValueError, 'checksums'):
            self.publish()
        gh.assert_not_called()
        for path in self.dist.iterdir():
            path.unlink()
        write_artifacts(self.dist, self.tag[1:], self.commit, {**self.files, 'unexpected.txt': b'private'}, self.bootstraps)
        with mock.patch.object(release_publish, 'gh') as gh, self.assertRaisesRegex(ValueError, 'immutable source'):
            self.publish()
        gh.assert_not_called()

    def test_upload_uses_private_validated_snapshot_and_cleans_it(self):
        uploads = []
        def github(*arguments, **kwargs):
            if arguments[0] == 'api':
                (self.dist / 'install_harness_codex.sh').write_text('changed after validation')
                return json.dumps({'object': {'type': 'commit', 'sha': self.commit}})
            paths = [value for value in arguments if isinstance(value, Path)]
            uploads.extend(paths)
            for path in paths:
                self.assertTrue(path.is_file())
                if os.name == 'posix':
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            bootstrap = next(path for path in paths if path.name == 'install_harness_codex.sh')
            self.assertEqual(bootstrap.read_bytes(), b'VERSION=' + self.tag[1:].encode() + b'\n')
            return ''
        with mock.patch.object(release_publish, 'gh', side_effect=github):
            self.publish()
        self.assertTrue(uploads)
        self.assertTrue(all(not path.exists() for path in uploads))

    def test_self_consistent_asset_checksums_cannot_change_archive_permissions(self):
        path = self.dist / f'harness-codex-{self.tag[1:]}-linux.tar.gz'
        changed = io.BytesIO()
        with tarfile.open(path, 'r:gz') as original, tarfile.open(fileobj=changed, mode='w:gz') as output:
            for member in original:
                data = original.extractfile(member).read()
                member.mode = 0o777
                output.addfile(member, io.BytesIO(data))
        path.write_bytes(changed.getvalue())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        report_path = self.dist / 'build.json'
        report = json.loads(report_path.read_text())
        report['sha256'] = digest
        report_path.write_text(json.dumps(report))
        (self.dist / 'SHA256SUMS').write_text(f'{digest}  {path.name}\n' +
            report['bootstrapSha256'] + '  install_harness_codex.sh\n')
        with mock.patch.object(release_publish, 'gh') as gh, self.assertRaisesRegex(ValueError, 'permissions'):
            self.publish()
        gh.assert_not_called()
