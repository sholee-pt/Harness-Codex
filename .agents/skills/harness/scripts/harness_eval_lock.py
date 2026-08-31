#!/usr/bin/env python3
"""Small cross-platform advisory lock used by the local evaluation store."""

from __future__ import annotations

import os
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")
        if file.tell() == 0:
            file.write(b"\0")
            file.flush()
        deadline = time.monotonic() + self.timeout
        while not self._try_lock(file):
            if time.monotonic() >= deadline:
                file.close()
                raise LockError(f"timed out waiting for evaluation lock: {self.path.name}")
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
