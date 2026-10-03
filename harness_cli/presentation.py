"""Human-readable CLI reports and elapsed-time progress; JSON is opt-in."""
from __future__ import annotations

from contextvars import ContextVar
import json
import os
import shlex
import shutil
import sys
import threading
import time
import unicodedata

JSON_MODE = ContextVar('harness_json_output', default=False)


def command(arguments, *, windows=None) -> str:
    """Format literal argv for POSIX shells, or PowerShell on Windows."""
    values = [str(value) for value in arguments]
    if windows is None:
        windows = os.name == 'nt'
    if windows:
        return '& ' + ' '.join("'" + value.replace("'", "''") + "'" for value in values)
    return shlex.join(values)


def confirm(message, *, progress=None) -> bool:
    """Explicit Enter/y/yes accepts; closed or redirected input never does."""
    progress = progress or Progress('', stream=sys.stdout)
    while True:
        try:
            answer = progress.ask(message + ' [Y/n]: ').strip().casefold()
        except EOFError:
            return False
        if answer in {'', 'y', 'yes'}:
            return True
        if answer in {'n', 'no'}:
            return False
        progress.line('Press Enter or type y/yes to approve; type n/no to decline.', style='warning')


def update_report(value: dict) -> None:
    if JSON_MODE.get():
        report(value, title='Tool update')
        return
    display = Progress('', stream=sys.stdout)
    updated = value.get('updated') is True
    available = value.get('updateAvailable') is True
    refused = value.get('status') == 'downgrade-refused'
    title = ('Harness updated' if updated else 'Older version; downgrade refused' if refused else
             'Harness update available' if available else 'Harness is already up to date')
    display.line('\n' + title, style='warning' if refused else 'success' if updated or not available else 'heading')
    display.line('  Current version: ' + clean(value.get('installation', {}).get('version', value.get('currentVersion', 'unknown'))), style='value')
    display.line('  Latest version:  ' + clean(value.get('availableVersion', 'unknown')), style='value')
    if updated:
        display.line('  Previous version: ' + clean(value.get('currentVersion', 'unknown')), style='muted')
    elif available:
        display.line('  Run harness-codex update to install it.')
    else:
        display.line('  No files were changed.', style='muted')
    display.line('')


def clean(value) -> str:
    # Never let model/tool output inject terminal control sequences.
    return ''.join(c if c in '\n\t' or ord(c) >= 32 and not 127 <= ord(c) < 160 else '?' for c in str(value))


def box(rows, *, title, subtitle='', stream=None):
    stream = stream or sys.stdout
    width = min(96, max(1, shutil.get_terminal_size((80, 24)).columns - 1))
    if width < 8:
        for row in [title, subtitle, *rows]:
            print(clean(row), file=stream)
        return
    inner = width - 4
    def size(char):
        return 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1
    def wrapped(value):
        line, used = '', 0
        for char in clean(value).replace('\t', '    ').replace('\r', '').replace('\n', ' '):
            count = size(char)
            if used + count > inner:
                yield line, used
                line, used = '', 0
            line += char
            used += count
        yield line, used
    encoding = getattr(stream, 'encoding', None) or 'utf-8'
    try:
        '╭─╮│╰╯'.encode(encoding)
        top, bottom, edge, bar = ('╭', '╮'), ('╰', '╯'), '│', '─'
    except (UnicodeError, LookupError):
        top = bottom = ('+', '+')
        edge, bar = '|', '-'
    print(top[0] + bar * (width - 2) + top[1], file=stream)
    for row in [title, subtitle, '', *rows]:
        for text, used in wrapped(row):
            print(edge + ' ' + text + ' ' * (inner - used) + ' ' + edge, file=stream)
    print(bottom[0] + bar * (width - 2) + bottom[1], file=stream, flush=True)


def report(value: dict, *, title='Harness', error=False) -> None:
    stream = sys.stderr if error else sys.stdout
    if JSON_MODE.get():
        print(json.dumps(value, indent=2, ensure_ascii=False), file=stream, flush=True)
        return
    state = value.get('state', value.get('installationStatus', value.get('status')))
    if state is None:
        state = 'valid' if value.get('valid') is True else 'needs attention' if value.get('valid') is False else value.get('mode', 'complete')
    print(f'{title}: {clean(state)}', file=stream)
    integration = value.get('codexIntegration')
    if isinstance(integration, dict):
        print('Codex integration: ' + clean(integration.get('state', 'unknown')), file=stream)
        if integration.get('state') not in {'configured', 'not-installed'}:
            print('  ' + clean(integration.get('error') or 'Open a fresh terminal and check Codex PATH precedence; use config to repair integration.'), file=stream)
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
    inventory = value.get('instructionInventory')
    if isinstance(inventory, dict):
        print(f"  Instructions: {inventory['files']} files, {inventory['bytes']} bytes; "
              f"{len(inventory['duplicateParagraphs'])} repeated prose groups, {len(inventory['skipped'])} skipped. "
              'Static inventory only; --json shows details.', file=stream)
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
        self.line(self.label, style='heading')
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

    def line(self, message: str, *, style=None):
        with self.lock:
            self.clear()
            text = clean(message)
            colors = {'heading': '1;36', 'value': '36', 'success': '32', 'warning': '33', 'error': '31', 'muted': '2'}
            if self.tty and 'NO_COLOR' not in os.environ and style in colors:
                text = f'\033[{colors[style]}m{text}\033[0m'
            print(text, file=self.stream, flush=True)

    def phase(self, label: str):
        with self.lock:
            if self.compact:
                self.activity = label
                return
            if label != self.label:
                self.label = label
                self.line(label, style='heading')

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
            state = 'stopped' if kind else self.outcome
            self.line(f'  {self.label}: {state} ({int(time.monotonic() - self.started)}s)',
                      style='error' if kind else 'success' if state in {'finished', 'updated', 'up-to-date'} else 'warning')
