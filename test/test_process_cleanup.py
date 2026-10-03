"""Owned descendants must stop even when their process-group leader exited first."""
import asyncio
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from harness_cli import auto_relay, configuration, management_relay, presentation


@unittest.skipUnless(os.name == 'posix', 'POSIX owned process groups')
class ExitedLeaderCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.heartbeat, self.pids = self.root / 'heartbeat', self.root / 'pids.json'
        self.processes = []
        original_spawn = asyncio.create_subprocess_exec
        async def spawn(*args, **kwargs):
            process = await original_spawn(*args, **kwargs)
            self.processes.append(process)
            return process
        patch = mock.patch('asyncio.create_subprocess_exec', side_effect=spawn)
        patch.start()
        self.addCleanup(patch.stop)
        child = ('import signal, time\nfrom pathlib import Path\n'
                 'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                 'path = Path(' + repr(str(self.heartbeat)) + ')\n'
                 'while True:\n path.write_text(str(time.monotonic_ns())); time.sleep(.01)\n')
        self.script = self.root / 'harness.py'
        self.script.write_text('import json, os, subprocess, sys, time\nfrom pathlib import Path\n'
            'child = subprocess.Popen([sys.executable, "-c", ' + repr(child) + '])\n'
            'while not Path(' + repr(str(self.heartbeat)) + ').exists(): time.sleep(.01)\n'
            'Path(' + repr(str(self.pids)) + ').write_text(json.dumps([os.getpid(), child.pid]))\n')

    def tearDown(self):
        if self.pids.exists():
            try:
                os.killpg(json.loads(self.pids.read_text())[0], signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def ready(self):
        for _ in range(200):
            if self.pids.exists() and self.processes and self.processes[-1].returncode is not None:
                self.assertEqual(self.processes[-1].returncode, 0)
                return
            await asyncio.sleep(.01)
        self.fail('The child fixture did not start')

    async def assert_stopped(self):
        await asyncio.sleep(.05)
        before = self.heartbeat.read_bytes()
        await asyncio.sleep(.1)
        self.assertEqual(self.heartbeat.read_bytes(), before, 'A descendant kept running after cleanup')

    async def test_management_timeout_stops_a_child_after_the_cli_parent_exited(self):
        controls = management_relay.Controls(SimpleNamespace(env=dict(os.environ)), None, None)
        controls.source = self.root
        task = asyncio.create_task(controls.cli(self.root, ['status'], timeout=.5))
        try:
            await self.ready()
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(task, 3)
            await self.assert_stopped()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await controls.close()

    def test_metadata_close_stops_descendants_without_waiting_on_a_pipe_lock(self):
        server = configuration.Server([sys.executable, '-B', str(self.script)], self.root,
                                      presentation.Progress('Fixture', stream=io.StringIO()))
        server.process.wait(timeout=2)
        self.assertEqual(server.process.returncode, 0)
        failures = []
        def close():
            try:
                server.close()
            except Exception as error:
                failures.append(error)
        closer = threading.Thread(target=close, daemon=True)
        closer.start()
        try:
            closer.join(timeout=5)
            self.assertFalse(closer.is_alive(), 'Metadata cleanup blocked on its inherited pipes')
            self.assertFalse(failures)
            self.assertFalse(any(thread.is_alive() for thread in server.readers))
            before = self.heartbeat.read_bytes()
            time.sleep(.1)
            self.assertEqual(self.heartbeat.read_bytes(), before)
        finally:
            self.tearDown()
            closer.join(timeout=2)

    async def test_relay_disconnect_stops_descendants_after_the_backend_exited(self):
        adapter = auto_relay.Relay(sys.executable, dict(os.environ), args=['-B', str(self.script)])
        adapter.args, adapter.cwd = ['-B', str(self.script)], str(self.root)
        owner = self
        class Socket:
            def __aiter__(self):
                return self
            async def __anext__(self):
                await owner.ready()
                raise StopAsyncIteration
            async def send(self, message):
                owner.fail('The fixture does not submit a Codex request')
            async def close(self, **kwargs):
                pass
        await asyncio.wait_for(adapter.session(Socket()), 3)
        self.assertIsNone(adapter.error)
        await self.assert_stopped()


if __name__ == '__main__':
    unittest.main()
