"""Human-readable CLI reports and elapsed-time progress; JSON is opt-in."""
from __future__ import annotations

from contextvars import ContextVar
import json
import os
import shutil
import sys
import threading
import time

JSON_MODE = ContextVar('harness_json_output', default=False)


def clean(value) -> str:
    # Never let model/tool output inject terminal control sequences.
    return ''.join(c if c in '\n\t' or ord(c) >= 32 and not 127 <= ord(c) < 160 else '?' for c in str(value))


def report(value: dict, *, title='Harness', error=False) -> None:
    stream = sys.stderr if error else sys.stdout
    if JSON_MODE.get():
        print(json.dumps(value, indent=2, ensure_ascii=False), file=stream, flush=True)
        return
    state = value.get('state', value.get('installationStatus', value.get('status')))
    if state is None:
        state = 'valid' if value.get('valid') is True else 'needs attention' if value.get('valid') is False else value.get('mode', 'complete')
    print(f'{title}: {clean(state)}', file=stream)
    labels = {'version': 'Version', 'currentVersion': 'Current version', 'generatorVersion': 'Generator version', 'generator': 'Generator',
              'availableVersion': 'Available version', 'updateAvailable': 'Update available',
              'dryRun': 'Preview only', 'writes': 'Planned file writes', 'removes': 'Planned removals',
              'recoveryRequired': 'Recovery required', 'nextCommand': 'Next command', 'guidance': 'Guidance'}
    for key, label in labels.items():
        item = value.get(key)
        if item is not None and not isinstance(item, (dict, list)):
            print(f'  {label}: {clean(item)}', file=stream)
    for key, label in (('runtimeLoading', 'Runtime loading'), ('taskQuality', 'Task quality')):
        item = value.get('summary', {}).get(key)
        if item and item not in {'not-tested', 'not-measured'}:
            print(f'  {label}: {clean(item)}', file=stream)
    if value.get('summary'):
        print('  Check scope: project files and contracts. Live loading and task quality require separate evaluation.', file=stream)
    for kind in ('errors', 'warnings', 'upgradeRequirements'):
        for entry in value.get(kind, [])[:12]:
            print(f'  - {clean(entry)}', file=stream)
        if len(value.get(kind, [])) > 12:
            print('  More details: repeat with --json.', file=stream)
    # Removal previews must show their paths, not just a success label.
    for key in ('actions', 'operations', 'removalCandidates', 'files'):
        entries = value.get(key)
        if isinstance(entries, list):
            for item in entries[:20]:
                if isinstance(item, dict):
                    path = item.get('path', item.get('relativePath'))
                    if path:
                        print(f"  {clean(item.get('action', 'file'))}: {clean(path)}", file=stream)
                elif isinstance(item, str):
                    print(f'  {clean(item)}', file=stream)
            if len(entries) > 20:
                print(f'  ... {len(entries) - 20} more entries; use --json for the full preview.', file=stream)
    for key in ('removal', 'generatorInstallation'):
        if isinstance(value.get(key), dict):
            report(value[key], title=key, error=error)
    stream.flush()


class Progress:
    """An indeterminate timer, never an invented percentage of model work."""
    def __init__(self, label: str, *, stream=None, compact=False):
        self.stream = stream or sys.stderr
        self.label = label
        self.activity = ''
        self.compact = compact
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.tty = bool(self.stream.isatty()) and os.environ.get('TERM') != 'dumb'
        self.paused = False
        self.outcome = 'finished'

    def __enter__(self):
        self.line(self.label)
        if self.tty:
            self.thread = threading.Thread(target=self._animate, daemon=True)
            self.thread.start()
        return self

    def _animate(self):
        index = 0
        frames = '|/-\\'
        while not self.stop.wait(0.2):
            with self.lock:
                if not self.paused:
                    elapsed = int(time.monotonic() - self.started)
                    activity = self.activity or self.label
                    width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns - 1)
                    budget = max(1, width - len(f'  |   {elapsed}s'))
                    activity = clean(activity).replace('\n', ' ').replace('\t', ' ')
                    if len(activity) > budget:
                        activity = activity[:max(0, budget - 3)] + '...'
                    text = f'  {frames[index % 4]} {activity}  {elapsed}s'
                    self.stream.write('\r\033[2K' + clean(text))
                    self.stream.flush()
            index += 1

    def clear(self):
        if self.tty:
            self.stream.write('\r\033[2K')

    def line(self, message: str):
        with self.lock:
            self.clear()
            print(clean(message), file=self.stream, flush=True)

    def phase(self, label: str):
        with self.lock:
            if self.compact:
                self.activity = label
                return
            if label != self.label:
                self.label = label
                self.line(label)

    def ask(self, message: str, *, secret=False) -> str:
        from getpass import getpass
        with self.lock:
            self.paused = True
            self.clear()
            self.stream.flush()
        try:
            if not sys.stdin.isatty():
                raise ValueError('A terminal is required to answer Codex. Use --interactive in a terminal.')
            return getpass(clean(message)) if secret else input(clean(message))
        finally:
            with self.lock:
                self.paused = False

    def __exit__(self, kind, value, traceback):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self.clear()
            state = 'stopped' if kind else self.outcome
            print(f'  {self.label}: {state} ({int(time.monotonic() - self.started)}s)', file=self.stream, flush=True)
