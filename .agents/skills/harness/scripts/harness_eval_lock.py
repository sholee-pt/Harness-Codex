#!/usr/bin/env python3
"""Crash-released advisory locks shared by local stores and project transactions."""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
import hashlib
import tempfile
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import IO


class LockError(TimeoutError):
    pass


class FileLock:
    """Hold an OS advisory lock on byte zero without deleting the lock file."""

    def __init__(self, path: Path, *, timeout: float = 10.0, poll_interval: float = 0.05):
        if timeout <= 0 or poll_interval <= 0:
            raise ValueError("lock timeout and poll interval must be positive")
        self.path = path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._file: IO[bytes] | None = None

    def _try_lock(self, file: IO[bytes]) -> bool:
        if os.name == "nt":
            import msvcrt

            file.seek(0)
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return False
            return True

        import fcntl

        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def acquire(self) -> "FileLock":
        for part in (self.path, *self.path.parents):
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
                raise ValueError("Lock paths must not contain links or reparse points")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")
        if file.tell() == 0:
            file.write(b"\0")
            file.flush()
        deadline = time.monotonic() + self.timeout
        while not self._try_lock(file):
            if time.monotonic() >= deadline:
                file.close()
                raise LockError(f"timed out waiting for Harness lock: {self.path.name}")
            time.sleep(self.poll_interval)
        self._file = file
        return self

    def release(self) -> None:
        file = self._file
        if file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()
            self._file = None

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


_held = threading.local()


@contextmanager
def project_lock(root: Path):
    # Outside the project: removing a harness must not unlink a live lock inode.
    key = hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()
    user = hashlib.sha256(os.path.normcase(str(Path.home().resolve())).encode()).hexdigest()[:16]
    default = Path(tempfile.gettempdir()) / ("harness-project-locks-" + user)
    base = Path(os.environ.get("HARNESS_LOCK_HOME", str(default))).expanduser()
    base = base.parent.resolve() / base.name
    path = base / (key + ".lock")
    held = getattr(_held, "paths", None)
    if held is None:
        held = _held.paths = set()
    if path in held:
        yield
        return
    with FileLock(path):
        held.add(path)
        try:
            yield
        finally:
            held.remove(path)


def project_locked(function):
    @wraps(function)
    def locked(root, *args, **kwargs):
        with project_lock(root):
            return function(root, *args, **kwargs)
    return locked
