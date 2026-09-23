"""Bounded Linux CI memory preparation and diagnostics; never changes build results."""
from __future__ import annotations

import argparse
import json
import mmap
import os
from pathlib import Path
import platform
import shutil
import subprocess
import threading
import time

GIB = 1024 ** 3


def memory():
    entries = (line.split() for line in Path('/proc/meminfo').read_text().splitlines())
    return {parts[0].rstrip(':'): int(parts[1]) * 1024 for parts in entries
            if parts[0] in {'MemTotal:', 'MemAvailable:', 'SwapTotal:', 'SwapFree:'}}


def swap_bytes(values, free):
    # Small hosted runners need a buffer for the large TUI test link. Keep the
    # existing 25 GiB test-build disk reserve after allocating that buffer.
    needed = max(0, 8 * GIB - values['SwapTotal']) if values['MemTotal'] < 12 * GIB else 0
    if needed:
        # Linux reserves the first page for the swap header. mkswap also needs
        # at least ten pages; disk capacity is not the usable swap capacity.
        needed = max(10, (needed + mmap.PAGESIZE - 1) // mmap.PAGESIZE + 1) * mmap.PAGESIZE
    if free < 25 * GIB + needed:
        raise ValueError('Native CI needs 25 GiB free after any additional swap allocation')
    return needed


def prepare(root):
    if platform.system() != 'Linux' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise ValueError('Resource preparation is restricted to disposable GitHub-hosted Linux runners')
    if not root.is_absolute() or root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ValueError('RUNNER_TEMP must be an existing absolute directory without links')
    values = memory()
    report(root)
    needed = swap_bytes(values, shutil.disk_usage(root).free)
    if needed:
        path = root / 'harness-native.swap'
        # Exclusive creation preserves any unrelated file or replacement link.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        for command in (['fallocate', '-l', str(needed), str(path)],
                        ['sudo', '-n', 'chown', '0:0', str(path)],
                        ['sudo', '-n', 'mkswap', str(path)], ['sudo', '-n', 'swapon', str(path)]):
            subprocess.run(command, check=True, timeout=120)
        actual = memory()['SwapTotal']
        if actual < 8 * GIB:
            report(root)
            raise ValueError(f'Native CI swap activation could not be verified: {actual} usable bytes; required {8 * GIB}')
    report(root)
    return needed


def report(root):
    try:
        value = {'nativeResources': {'time': time.time(), 'memoryBytes': memory(),
                                     'diskFreeBytes': shutil.disk_usage(root).free}}
        for name, filename in (('memoryPressure', '/proc/pressure/memory'), ('memoryEvents', '/sys/fs/cgroup/memory.events')):
            path = Path(filename)
            if path.is_file():
                value['nativeResources'][name] = path.read_text()[:2048]
        print(json.dumps(value), flush=True)
    except (OSError, ValueError):
        print('{"nativeResources": "unavailable"}', flush=True)


def run(root, command):
    if not command:
        raise ValueError('A native build command is required')
    stop = threading.Event()
    def sample():
        while not stop.wait(60):
            report(root)
    report(root)
    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        return subprocess.run(command, check=False).returncode
    finally:
        stop.set()
        thread.join(timeout=2)
        report(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(os.environ['RUNNER_TEMP'])
    if args.action == 'prepare':
        prepare(root)
    else:
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        result = run(root, command)
        raise SystemExit(128 - result if result < 0 else result)
