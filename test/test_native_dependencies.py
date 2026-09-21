"""Transient build downloads recover without accepting incomplete or changed assets."""
import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from build.native_ui import dependencies


class Response(io.BytesIO):
    def __init__(self, body, *, length=None):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body) if length is None else length)}


class NativeDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'asset'
        self.url = 'https://github.com/openai/codex/releases/download/fixture/asset'

    def error(self, status):
        return urllib.error.HTTPError(self.url, status, 'fixture', {}, None)

    def test_504_and_interrupted_body_retry_from_empty_file(self):
        partial = Response(b'partial')
        partial.read = unittest.mock.Mock(side_effect=[b'partial', TimeoutError('interrupted')])
        with patch.object(dependencies.urllib.request, 'urlopen', side_effect=[self.error(504), partial, Response(b'complete')]) as fetch, \
                patch.object(dependencies.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            dependencies.download(self.url, self.path)
        self.assertEqual(self.path.read_bytes(), b'complete')
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10])

    def test_retry_limit_leaves_no_partial_file(self):
        with patch.object(dependencies.urllib.request, 'urlopen', side_effect=[self.error(504) for _ in range(5)]) as fetch, \
                patch.object(dependencies.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(urllib.error.HTTPError):
                dependencies.download(self.url, self.path)
        self.assertEqual(fetch.call_count, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10, 20, 40])
        self.assertFalse(self.path.exists())

    def test_retries_refresh_cached_gateway_errors_without_changing_asset_identity(self):
        url = self.url + '?existing=value#fragment'
        requests = []
        def fetch(request, **kwargs):
            requests.append(request)
            if isinstance(request, str):
                self.assertEqual(request, url)
                raise self.error(504)
            parts = dependencies.urllib.parse.urlsplit(request.full_url)
            self.assertEqual((parts.scheme, parts.netloc, parts.path, parts.fragment),
                             ('https', 'github.com', '/openai/codex/releases/download/fixture/asset', 'fragment'))
            self.assertEqual(request.get_header('Cache-control'), 'no-cache')
            self.assertEqual(request.get_header('Pragma'), 'no-cache')
            query = dependencies.urllib.parse.parse_qs(parts.query)
            self.assertEqual(query['existing'], ['value'])
            self.assertEqual(len(query['harness_retry']), 1)
            if len(requests) == 2:
                raise self.error(504)
            return Response(b'complete')
        with patch.object(dependencies.urllib.request, 'urlopen', side_effect=fetch), \
                patch.object(dependencies.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            dependencies.download(url, self.path)
        self.assertEqual(self.path.read_bytes(), b'complete')
        self.assertNotEqual(requests[1].full_url, requests[2].full_url)

    def test_permanent_http_and_tls_errors_are_not_retried(self):
        for error in (self.error(403), self.error(404), urllib.error.URLError('certificate verify failed')):
            with self.subTest(error=error), patch.object(dependencies.urllib.request, 'urlopen', side_effect=error) as fetch, \
                    patch.object(dependencies.time, 'sleep') as sleep:
                with self.assertRaises(urllib.error.URLError):
                    dependencies.download(self.url, self.path)
                self.assertEqual(fetch.call_count, 1)
                sleep.assert_not_called()
                self.assertFalse(self.path.exists())

    def test_truncated_content_length_and_wrapped_timeout_are_retried(self):
        with patch.object(dependencies.urllib.request, 'urlopen', side_effect=[
                Response(b'short', length=30), urllib.error.URLError(TimeoutError()), Response(b'whole')]), \
                patch.object(dependencies.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            dependencies.download(self.url, self.path)
        self.assertEqual(self.path.read_bytes(), b'whole')

    def test_size_limit_cleans_file_without_retry(self):
        with patch.object(dependencies, 'MAX_DOWNLOAD_BYTES', 3), \
                patch.object(dependencies.urllib.request, 'urlopen', return_value=Response(b'large')) as fetch, \
                patch.object(dependencies.time, 'sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'download bound'):
                dependencies.download(self.url, self.path)
        self.assertFalse(self.path.exists())
        self.assertEqual(fetch.call_count, 1)
        sleep.assert_not_called()

    def test_existing_file_is_preserved_without_network_access(self):
        self.path.write_bytes(b'existing')
        with patch.object(dependencies.urllib.request, 'urlopen') as fetch:
            with self.assertRaises(FileExistsError):
                dependencies.download(self.url, self.path)
        self.assertEqual(self.path.read_bytes(), b'existing')
        fetch.assert_not_called()

    def test_setup_rejects_changed_manifest_archive_or_bindings_without_environment_export(self):
        stem = 'ptrcomp_sandbox_release_x86_64-unknown-linux-musl'
        archive, binding = 'librusty_v8_' + stem + '.a.gz', 'src_binding_' + stem + '.rs'
        sums = 'rusty_v8_' + stem + '.sha256'
        bodies = {archive: b'archive', binding: b'bindings'}
        bodies[sums] = ''.join(f'{hashlib.sha256(body).hexdigest()}  {name}\n' for name, body in bodies.items()).encode()
        trusted = self.root / 'third_party/v8/rusty_v8_1_2_3_release_manifests.sha256'
        trusted.parent.mkdir(parents=True)
        trusted.write_text(f'{hashlib.sha256(bodies[sums]).hexdigest()}  {sums}\n')
        environment = self.root / 'github-env'
        environment.write_bytes(b'existing\n')
        for index, corrupt in enumerate((sums, archive, binding)):
            def fetch(url, **kwargs):
                name = url.rsplit('/', 1)[1]
                return Response(b'changed' if name == corrupt else bodies[name])
            with self.subTest(corrupt=corrupt), patch.object(dependencies.subprocess, 'check_output', return_value='1.2.3\n'), \
                    patch.object(dependencies.urllib.request, 'urlopen', side_effect=fetch), \
                    patch.dict(dependencies.os.environ, {'GITHUB_ENV': str(environment)}), \
                    patch.object(dependencies.time, 'sleep') as sleep:
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    dependencies.setup(self.root, 'x86_64-unknown-linux-musl', self.root / f'output-{index}')
                self.assertEqual(environment.read_bytes(), b'existing\n')
                sleep.assert_not_called()
