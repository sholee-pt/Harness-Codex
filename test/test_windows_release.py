"""One-off Windows publication must preserve Linux assets and source identity."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from build.artifacts import write_artifacts
from build import windows_release as release
from test_native_ui import fixture, archive, VERSION

ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist, self.published = self.root / 'dist', self.root / 'published'
        self.published.mkdir()
        self.commit = 'b' * 40
        bootstraps = {name: (ROOT / 'installer' / name).read_bytes() for name in ('install_harness_codex.sh', 'install_harness_codex.ps1')}
        self.incoming = write_artifacts(self.dist, VERSION, self.commit, {'harness.py': b'fixture'}, bootstraps, platform='both')
        self.original = {key: value for key, value in self.incoming.items() if not key.startswith('windows')}
        self.linux_native = f'harness-codex-ui-{VERSION}-linux-x86_64.tar.gz'
        self.original.update(platforms=['linux'], nativeUi={self.linux_native: {'sha256': 'c' * 64, 'size': 123}})
        self.save_original()
        sums = release.checksums(self.dist / 'SHA256SUMS')
        self.old_sums = {key: value for key, value in sums.items() if key.endswith(('-linux.tar.gz', '.sh'))}
        self.old_sums[self.linux_native] = 'c' * 64
        self.save_sums()
        self.native = f'harness-codex-ui-{VERSION}-windows-x86_64.tar.gz'
        native_root = self.root / 'native'
        fixture(native_root)
        metadata = json.loads((native_root / 'harness-ui.json').read_text())
        metadata['harnessSourceCommit'] = self.commit
        (native_root / 'harness-ui.json').write_text(json.dumps(metadata))
        archive(native_root, self.dist / self.native)

    def save_original(self):
        (self.published / 'build.json').write_text(json.dumps(self.original))

    def save_sums(self):
        (self.published / 'SHA256SUMS').write_text(''.join(f'{value}  {name}\n' for name, value in self.old_sums.items()))

    def test_supplement_keeps_linux_metadata_and_repeat_is_idempotent(self):
        merged, sums, additions = release.prepare(self.dist, self.published, self.commit)
        for name, value in self.old_sums.items():
            self.assertEqual(sums[name], value)
        for key in ('commit', 'sha256', 'bootstrapSha256', 'artifact'):
            self.assertEqual(merged[key], self.original[key])
        self.assertEqual(merged['nativeUi'][self.linux_native], self.original['nativeUi'][self.linux_native])
        self.assertEqual(len(additions), 3)
        self.original, self.old_sums = merged, sums
        self.save_original()
        self.save_sums()
        self.assertEqual(release.prepare(self.dist, self.published, self.commit), (merged, sums, additions))

    def test_other_source_or_unpublished_native_release_is_rejected(self):
        for updates in ({'commit': 'd' * 40}, {'developmentBuild': True}, {'nativeUi': {}}, {'version': '0.1.0-beta'}):
            with self.subTest(updates=updates):
                saved = self.original.copy()
                self.original.update(updates)
                self.save_original()
                with self.assertRaises(ValueError):
                    release.prepare(self.dist, self.published, self.commit)
                self.original = saved
        self.save_original()

    def test_changed_existing_windows_binary_is_never_replaced(self):
        self.old_sums[self.native] = 'e' * 64
        self.save_sums()
        with self.assertRaisesRegex(ValueError, 'replacement refused'):
            release.prepare(self.dist, self.published, self.commit)

    def test_checksum_labels_cannot_hide_changed_zip_payload(self):
        name = f'harness-codex-{VERSION}-windows.zip'
        with zipfile.ZipFile(self.dist / name, 'w') as target:
            target.writestr(f'harness-codex-{VERSION}/harness.py', b'changed')
        self.incoming['windowsSha256'] = release.digest(self.dist / name)
        (self.dist / 'build.json').write_text(json.dumps(self.incoming))
        sums = release.checksums(self.dist / 'SHA256SUMS')
        sums[name] = self.incoming['windowsSha256']
        (self.dist / 'SHA256SUMS').write_text(''.join(f'{value}  {key}\n' for key, value in sums.items()))
        with self.assertRaisesRegex(ValueError, 'archive payload differs'):
            release.prepare(self.dist, self.published, self.commit)

    def test_mismatched_tag_cannot_start_remote_uploads(self):
        responses = [json.dumps({'isDraft': False, 'assets': [], 'body': ''}), json.dumps({'sha': 'f' * 40})]
        with mock.patch.object(release.subprocess, 'check_output', side_effect=responses) as gh:
            with self.assertRaisesRegex(ValueError, 'Release tag'):
                release.publish(self.dist, self.commit, 'sholee-pt/Harness-Codex')
        self.assertEqual(gh.call_count, 2)
        self.assertFalse(any('upload' in call.args[0] for call in gh.call_args_list))

    def test_notes_are_additive_and_authorization_is_not_persistent(self):
        original = 'Linux instructions. Windows releases remain paused.'
        once = release.notes(original, VERSION)
        self.assertEqual(release.notes(once, VERSION), once)
        self.assertIn('Linux instructions.', once)
        self.assertIn('Future releases default to Linux', once)
        workflow = (ROOT / '.github/workflows/windows-release.yml').read_text()
        for trigger in ('push:', 'pull_request:', 'workflow_run:', 'schedule:', 'workflow_call:'):
            self.assertNotIn('\n  ' + trigger, workflow)
        self.assertIn('\n  workflow_dispatch:', workflow)
        self.assertNotIn('windows-latest', (ROOT / '.github/workflows/codex-beta.yml').read_text())
