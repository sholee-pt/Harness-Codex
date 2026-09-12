"""Public bootstrap entrypoint, pipe input and fail-before-install cases."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'installer/install_harness_codex.sh'


@unittest.skipUnless(os.name == 'posix', 'Public installer uses Linux shell tools')
class PublicBootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.archive = self.root / 'payload.tar.gz'
        self.sums = self.root / 'sums'
        self.marker = self.root / 'installed'
        curl = self.bin / 'curl'
        curl.write_text('''#!/bin/sh
url=; output=
while [ "$#" -gt 0 ]; do
  case "$1" in https://*) url=$1;; -o) shift; output=$1;; esac
  shift
done
case "$url" in
  */SHA256SUMS) cp "$TEST_SUMS" "$output" ;;
  */harness-codex-0.11.0-beta-linux.tar.gz) cp "$TEST_ARCHIVE" "$output" ;;
  *) exit 87 ;;
esac
''')
        curl.chmod(0o755)
        self.env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.root),
                    'TMPDIR': str(self.root), 'TEST_SUMS': str(self.sums),
                    'TEST_ARCHIVE': str(self.archive), 'TEST_MARKER': str(self.marker)}

    def make_archive(self, *, unsafe=False, linked=False):
        with tarfile.open(self.archive, 'w:gz') as archive:
            name = '../escape' if unsafe else 'harness-codex-0.11.0-beta/install.sh'
            data = b'#!/bin/sh\nprintf installed > "$TEST_MARKER"\n'
            info = tarfile.TarInfo(name)
            if linked:
                info.type = tarfile.SYMTYPE
                info.linkname = '/tmp/outside'
            else:
                info.size = len(data)
            archive.addfile(info, None if linked else io.BytesIO(data))
        self.sums.write_text(hashlib.sha256(self.archive.read_bytes()).hexdigest() + '  harness-codex-0.11.0-beta-linux.tar.gz\n')

    def invoke(self, *arguments):
        return subprocess.run(['/bin/sh', '-s', '--', *arguments], input=SCRIPT.read_text(),
                              env=self.env, capture_output=True, text=True, timeout=30)

    def test_piped_script_installs_and_cleans_only_its_temporary_directory(self):
        self.make_archive()
        unrelated = self.root / 'keep'
        unrelated.write_text('user')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text(), 'installed')
        self.assertEqual(unrelated.read_text(), 'user')
        self.assertEqual(list(self.root.glob('harness-codex-install.*')), [])

    def test_checksum_failure_never_executes_payload(self):
        self.make_archive()
        self.sums.write_text('0' * 64 + '  harness-codex-0.11.0-beta-linux.tar.gz\n')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_traversal_and_links_are_rejected_before_extraction(self):
        for options in [{'unsafe': True}, {'linked': True}]:
            with self.subTest(options=options):
                self.make_archive(**options)
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertFalse(self.marker.exists())
                self.assertFalse((self.root / 'escape').exists())

    def test_help_and_invalid_options_need_no_download(self):
        before = list(self.root.iterdir())
        self.assertEqual(self.invoke('--help').returncode, 0)
        for options in [('--agent', 'claude'), ('--bin-dir',), ('--unknown',), ('--branch', 'codex/v9.6')]:
            self.assertNotEqual(self.invoke(*options).returncode, 0)
        self.assertEqual(list(self.root.iterdir()), before)


BASH = (shutil.which("bash") if os.name != "nt" else
        next((str(path) for path in (Path("C:/Program Files/Git/bin/bash.exe"),)
              if path.is_file()), None))


@unittest.skipUnless(BASH and os.name == 'posix', "Source shell installer targets Linux; native Windows installer is tested separately")
class SourceInstallerTests(unittest.TestCase):
    def test_stage_output_keeps_conda_noise_and_receipts_in_log_and_preserves_failures(self):
        for failure, existing in (("", False), ("", True), ("env", False), ("create", False), ("run", True)):
            with self.subTest(failure=failure, existing=existing), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                fake_conda = base / "fake-conda"
                if existing:
                    (base / 'data').mkdir()
                    (base / 'data/active.json').write_text('{}')  # Legacy installation selects its existing named environment.
                fake_conda.write_text('''#!/usr/bin/env bash
if [[ "$1" == "$HARNESS_TEST_FAIL" ]]; then
  printf 'dependency failure detail\\n' >&2
  exit 23
fi
case "$1" in
  env)
    printf 'advisory warning, not an error\\n' >&2
    if [[ "$HARNESS_TEST_EXISTING" == yes ]]; then printf '{"envs":["/fixture/harness"]}\\n'; else printf '{"envs":[]}\\n'; fi ;;
  create) mkdir -p -- "$HARNESS_TEST_PREFIX/conda-meta" "$HARNESS_TEST_PREFIX/bin"; touch "$HARNESS_TEST_PREFIX/conda-meta/history"; printf '#!/bin/sh\\nexit 0\\n' > "$HARNESS_TEST_PREFIX/bin/python"; chmod +x "$HARNESS_TEST_PREFIX/bin/python"; printf 'Channels: conda-forge\\nDownloading and Extracting Packages\\n'; printf 'advisory warning, not an error\\n' >&2 ;;
  run)
    if [[ " $* " == *" /bin/sh "* ]]; then printf '%s\\n' "$HARNESS_TEST_PREFIX"; exit 0; fi
    printf '{"treeHash":"internal-receipt","branch":null}\\n'
    printf '{"state":"unchanged","writes":0}\\n'
    printf 'Installed harness-codex in /fixture/bin. PATH registration skipped; invoke the command by its full path.\\n'
    printf '%s\\n' "$@" > "$HARNESS_TEST_ARGUMENTS" ;;
esac
''', encoding="utf-8")
                fake_conda.chmod(0o755)
                selected_prefix = base / ('legacy/harness' if existing else 'data-runtime/envs/harness')
                if existing:
                    (selected_prefix / 'conda-meta').mkdir(parents=True)
                    (selected_prefix / 'conda-meta/history').write_text('fixture')
                    (selected_prefix / 'bin').mkdir()
                    (selected_prefix / 'bin/python').write_text('#!/bin/sh\nexit 0\n')
                    (selected_prefix / 'bin/python').chmod(0o755)
                arguments = base / "arguments"
                environment = {**os.environ, "CONDA_EXE": fake_conda.as_posix(), "TMPDIR": base.as_posix(),
                               "HARNESS_TEST_FAIL": failure, "HARNESS_TEST_EXISTING": "yes" if existing else "no",
                               "HARNESS_TEST_ARGUMENTS": arguments.as_posix(), "HARNESS_TEST_PREFIX": selected_prefix.as_posix()}
                for name in ("BASH_ENV", "ENV"):
                    environment.pop(name, None)
                result = subprocess.run([BASH, str(ROOT / "installer/install.sh"), "--data-dir", (base / 'data').as_posix(), "--no-modify-path", "--auto-update", "off"],
                                        env=environment, capture_output=True, text=True, timeout=30)
                logs = list(base.glob("harness-codex-install-log.*"))
                self.assertEqual(len(logs), 1, result.stdout + result.stderr)
                log = logs[0].read_text()
                self.assertIn(logs[0].name, result.stdout + result.stderr)
                self.assertNotIn('"treeHash"', result.stdout)
                self.assertNotIn("Downloading and Extracting", result.stdout)
                self.assertNotIn("advisory warning", result.stdout)
                if failure:
                    self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
                    self.assertNotIn("Installation complete", result.stdout)
                    self.assertIn("failed (exit 23)", result.stderr)
                    self.assertIn("dependency failure detail", result.stderr)
                    self.assertIn("dependency failure detail", log)
                    if failure != "run":
                        self.assertFalse(arguments.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertRegex(result.stdout, r"\[3/3\].*: done \(\d+s\)")
                    self.assertIn("Installed harness-codex in /fixture/bin", result.stdout)
                    self.assertIn("PATH registration skipped", result.stdout)
                    self.assertIn('"treeHash":"internal-receipt"', log)
                    self.assertIn('"writes":0', log)
                    self.assertIn("advisory warning", log)
                    self.assertIn("--no-modify-path", arguments.read_text())
                    self.assertEqual("Reusing the existing" in result.stdout, existing)
                if os.name == "posix":
                    self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)

    def test_unpacked_source_installer_rejects_claude_before_conda(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            marker = base / "conda-was-called"
            fake_conda = base / "fake-conda"
            fake_conda.write_text('#!/usr/bin/env bash\nprintf called > "$HARNESS_TEST_CONDA_MARKER"\nexit 23\n',
                                  encoding="utf-8")
            fake_conda.chmod(0o755)
            environment = {**os.environ, "CONDA_EXE": fake_conda.as_posix(),
                           "HARNESS_TEST_CONDA_MARKER": marker.as_posix()}
            for name in ("BASH_ENV", "ENV"):
                environment.pop(name, None)
            for arguments in (("--agent", "claude"), ("--agent=claude",),
                              ("--runtime", "claude"), ("--runtime=claude",)):
                with self.subTest(arguments=arguments):
                    result = subprocess.run([BASH, str(ROOT / "installer/install.sh"), *arguments],
                                            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("Claude integration is not implemented", result.stderr)
                    self.assertFalse(marker.exists())
            for arguments in (("--agent", "claude", "--runtime", "codex"),
                              ("--runtime=codex", "--agent=claude"),
                              ("--agent=claude", "--agent=codex")):
                result = subprocess.run([BASH, str(ROOT / "installer/install.sh"), *arguments],
                                        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Conflicting", result.stderr)
                self.assertFalse(marker.exists())
            help_result = subprocess.run([BASH, str(ROOT / "installer/install.sh"), "--help"],
                                         env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(help_result.returncode, 0)
            self.assertNotIn("--agent", help_result.stdout)
            self.assertNotIn("--runtime", help_result.stdout)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()

@unittest.skipUnless(os.name == 'posix', 'Requires a Linux controlling terminal')
class InstallerTerminalTests(unittest.TestCase):
    def test_timer_and_confirmed_child_bash_activation(self):
        import pty
        import select
        import signal
        import time
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            fake = base / 'conda'
            fake.write_text("""#!/usr/bin/env bash
case "$1" in
 env) printf '{"envs":[]}\\n' ;;
 create) mkdir -p "$3/conda-meta" "$3/bin"; touch "$3/conda-meta/history"; printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/python"; chmod +x "$3/bin/python"; sleep 1.4 ;;
 run) printf 'Installed harness-codex in fixture.\\n' ;;
esac
""")
            fake.chmod(0o755)
            marker = base / 'child-read-bashrc'
            (base / '.bashrc').write_text('printf loaded > "$HOME/child-read-bashrc"\nexit 7\n')
            env = {**os.environ, 'CONDA_EXE': str(fake), 'HOME': str(base), 'TMPDIR': str(base),
                   'TERM': 'xterm', 'PATH': '/usr/bin:/bin'}
            for key in ('BASH_ENV', 'ENV'):
                env.pop(key, None)
            pid, terminal = pty.fork()
            if pid == 0:
                os.execve('/bin/bash', ['/bin/bash', str(ROOT / 'installer/install.sh'),
                          '--data-dir', str(base / 'data'), '--auto-update', 'off'], env)
            output = bytearray()
            status = None
            answered = False
            deadline = time.monotonic() + 20
            try:
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([terminal], [], [], 0.2)
                    if ready:
                        try:
                            data = os.read(terminal, 65536)
                        except OSError:
                            break
                        if not data:
                            break
                        output.extend(data)
                        if not answered and b'[Enter/yes opens, no skips]' in output:
                            os.write(terminal, b'\n')
                            answered = True
                    done, state = os.waitpid(pid, os.WNOHANG)
                    if done:
                        status = state
                        break
                if status is None:
                    done, state = os.waitpid(pid, os.WNOHANG)
                    if done:
                        status = state
                    else:
                        os.kill(pid, signal.SIGKILL)
                        os.waitpid(pid, 0)
                        self.fail('Installer terminal fixture timed out: ' + output.decode(errors='replace'))
            finally:
                os.close(terminal)
            text = output.decode(errors='replace')
            self.assertEqual(os.waitstatus_to_exitcode(status), 0, text)
            self.assertIn('  1s', text)
            self.assertTrue(answered, text)
            self.assertEqual(marker.read_text(), 'loaded')
            self.assertIn('Harness remains installed', text)
            self.assertEqual(list(base.glob('harness-codex-progress-*')), [])
