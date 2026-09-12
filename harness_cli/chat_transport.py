"""Harness terminal presentation over the native Codex App Server transport."""
from __future__ import annotations

import sys
import time

from .configuration import Server
from .presentation import Progress, clean


class Console(Progress):
    def __init__(self):
        super().__init__('Harness conversation · Codex engine', stream=sys.stdout, compact=True)
        self.paused = True
        self.streaming = False

    def phase(self, label):
        # Configuration-oriented phase labels belong to the setup client.
        pass

    def begin_turn(self):
        self.started = time.monotonic()
        self.activity = 'Codex is working'
        self.paused = False

    def end_text(self):
        with self.lock:
            if self.streaming:
                self.stream.write('\n')
                self.stream.flush()
                self.streaming = False
            self.paused = False

    def delta(self, text):
        with self.lock:
            if not self.streaming:
                self.clear()
                self.streaming = True
            self.paused = True
            self.stream.write(clean(text))
            self.stream.flush()

    def line(self, message):
        if getattr(self, 'streaming', False):
            self.end_text()
        super().line(message)

    def idle(self):
        self.end_text()
        with self.lock:
            self.paused = True
            self.clear()


class ChatServer(Server):
    def __init__(self, command, root, console):
        super().__init__(command, root, console)
        self.streamed = set()
        self.usage = None
        self.actual_model = None

    def observe(self, method, params):
        if method == 'item/agentMessage/delta':
            item_id, delta = params.get('itemId'), params.get('delta')
            if not isinstance(item_id, str) or not isinstance(delta, str):
                raise ValueError('Invalid Codex message delta.')
            if len(self.streamed) >= 128 and item_id not in self.streamed:
                raise ValueError('Too many concurrent message streams.')
            self.streamed.add(item_id)
            self.progress.delta(delta)
        elif method in {'item/started', 'item/completed'}:
            item = params.get('item')
            if not isinstance(item, dict):
                raise ValueError('Invalid Codex item.')
            kind = item.get('type')
            if method == 'item/started' and kind == 'commandExecution':
                self.progress.line('› ' + clean(item.get('command', 'Command')))
            elif method == 'item/started' and kind == 'fileChange':
                self.progress.line('› Preparing file changes')
            elif method == 'item/completed' and kind == 'agentMessage':
                if item.get('id') in self.streamed:
                    self.progress.end_text()
                else:
                    self.progress.line(item.get('text', ''))
                self.streamed.discard(item.get('id'))
            elif method == 'item/completed' and kind == 'commandExecution':
                self.progress.line(f"  Command finished: {clean(item.get('exitCode', 'unknown'))}")
                output = item.get('aggregatedOutput') or ''
                if output:
                    self.progress.line(output[-4000:])
                    if len(output) > 4000:
                        self.progress.line('  Earlier command output omitted from this view; native history retains it.')
            elif method == 'item/completed' and kind == 'fileChange':
                self.progress.line('  File changes: ' + clean(item.get('status', 'reported')))
            elif method == 'item/completed' and kind in {'collabAgentToolCall', 'mcpToolCall'}:
                self.progress.line('  Tool finished: ' + clean(item.get('tool', kind)))
        elif method == 'thread/tokenUsage/updated':
            self.usage = params.get('tokenUsage')
        elif method == 'model/rerouted':
            self.actual_model = params.get('toModel')
            self.progress.line('Codex rerouted the model: ' + clean(self.actual_model or 'see native status'))
