"""Publication requires every declared platform and the exact source commit."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from build.native_ui.attach import attach
from test_native_ui import VERSION, archive, fixture


class NativeReleaseTests(unittest.TestCase):
    def test_linux_only_attachment_rejects_missing_extra_or_wrong_commit_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist, artifacts = root / 'dist', root / 'artifacts'
            dist.mkdir()
            artifacts.mkdir()
            (dist / 'build.json').write_text(json.dumps({'version': VERSION, 'commit': 'a' * 40,
                'developmentBuild': False, 'platforms': ['linux']}))
            (dist / 'SHA256SUMS').write_text('existing sums\n')
            before = {p.name: p.read_bytes() for p in dist.iterdir()}
            with self.assertRaisesRegex(ValueError, 'declared release platforms'):
                attach(dist, artifacts)
            bundle = root / 'linux'
            fixture(bundle, 'linux-x86_64')
            metadata = json.loads((bundle / 'harness-ui.json').read_text())
            name = f'harness-codex-ui-{VERSION}-linux-x86_64.tar.gz'
            for commit in ('b' * 40, 'a' * 40):
                metadata['harnessSourceCommit'] = commit
                (bundle / 'harness-ui.json').write_text(json.dumps(metadata))
                archive(bundle, artifacts / name)
                if commit.startswith('b'):
                    with self.assertRaisesRegex(ValueError, 'exact Harness commit'):
                        attach(dist, artifacts)
                    self.assertEqual({p.name: p.read_bytes() for p in dist.iterdir()}, before)
            extra = artifacts / f'harness-codex-ui-{VERSION}-windows-x86_64.tar.gz'
            extra.write_bytes(b'unverified Windows artifact')
            with self.assertRaisesRegex(ValueError, 'declared release platforms'):
                attach(dist, artifacts)
            self.assertEqual({p.name: p.read_bytes() for p in dist.iterdir()}, before)
            extra.unlink()
            with contextlib.redirect_stdout(io.StringIO()):
                attach(dist, artifacts)
            build = json.loads((dist / 'build.json').read_text())
            self.assertEqual(set(build['nativeUi']), {name})
            self.assertEqual(build['nativeUi'][name]['sha256'], hashlib.sha256((dist / name).read_bytes()).hexdigest())

    def test_both_platforms_and_exact_commit_are_required_before_attachment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist, artifacts = root / 'dist', root / 'artifacts'
            dist.mkdir()
            artifacts.mkdir()
            (dist / 'build.json').write_text(json.dumps({'version': VERSION, 'commit': 'a' * 40, 'developmentBuild': False}))
            (dist / 'SHA256SUMS').write_text('existing sums\n')
            for platform in ('linux-x86_64', 'windows-x86_64'):
                bundle = root / platform
                fixture(bundle, platform)
                metadata = json.loads((bundle / 'harness-ui.json').read_text())
                metadata['harnessSourceCommit'] = 'a' * 40 if platform.startswith('linux') else 'b' * 40
                (bundle / 'harness-ui.json').write_text(json.dumps(metadata))
                archive(bundle, artifacts / f'harness-codex-ui-{VERSION}-{platform}.tar.gz')
            before = {p.name: p.read_bytes() for p in dist.iterdir()}
            with self.assertRaisesRegex(ValueError, 'exact Harness commit'):
                attach(dist, artifacts)
            self.assertEqual({p.name: p.read_bytes() for p in dist.iterdir()}, before)
            bundle = root / 'windows-x86_64'
            metadata['harnessSourceCommit'] = 'a' * 40
            (bundle / 'harness-ui.json').write_text(json.dumps(metadata))
            archive(bundle, artifacts / f'harness-codex-ui-{VERSION}-windows-x86_64.tar.gz')
            with contextlib.redirect_stdout(io.StringIO()):
                attach(dist, artifacts)
            build = json.loads((dist / 'build.json').read_text())
            self.assertEqual(len(build['nativeUi']), 2)
            for name, record in build['nativeUi'].items():
                self.assertEqual(hashlib.sha256((dist / name).read_bytes()).hexdigest(), record['sha256'])
                self.assertIn(record['sha256'] + '  ' + name, (dist / 'SHA256SUMS').read_text())
