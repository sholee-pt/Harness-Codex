"""Observe protocol metadata locally; completed turns alone never establish quality."""
from dataclasses import replace
import json
from pathlib import Path
import re
import time

from .model_routing import catalog_entries, _effort, identifier


def category(prompt):
    if re.search(r'\breadme\b|documentation|문서|오탈자|오타', prompt, re.I):
        return 'documentation'
    if re.search(r'review|audit|검토|검수', prompt, re.I):
        return 'review'
    if re.search(r'investigate|debug|원인|조사', prompt, re.I):
        return 'investigation'
    if re.search(r'implement|refactor|function|구현|수정|함수|리팩', prompt, re.I):
        return 'implementation'
    return 'general'


class Observer:
    def __init__(self, source_root, cwd, runtime, *, clock=time.monotonic):
        from .routing import evidence_module
        self.module = evidence_module(source_root)
        self.cwd, self.runtime, self.clock = Path(cwd), runtime, clock
        self.roots, self.managers, self.pending, self.active, self.usage = {}, {}, {}, {}, {}
        self.catalog, self.catalog_hash = None, None

    def manager(self, thread):
        folder = self.roots.get(thread)
        if folder is None:
            return None
        if folder not in self.managers:
            if len(self.managers) >= 512:
                self.managers.pop(next(iter(self.managers)))
            from harness_maintenance import find_root
            root = find_root(folder)
            self.managers[folder] = self.module.RoutingEvidence(root) if root else None
        return self.managers[folder]

    def decision(self, thread, prompt, decision, catalog, context, profiles, *, allow_advice=True):
        manager = self.manager(thread)
        if manager is None or not identifier(self.runtime):
            return decision
        state = manager.read()
        if not state['enabled']:
            return decision
        manifest_path = manager.root / '.harness/manifest.json'
        if manifest_path.stat().st_size > 4 * 1024 * 1024:
            return decision
        revision = self.module.digest(json.loads(manifest_path.read_text(encoding='utf-8')))
        if catalog is not self.catalog:
            self.catalog, self.catalog_hash = catalog, self.module.digest(catalog)
        group = manager.context(runtime=self.runtime, catalog=self.catalog_hash, revision=revision, category=category(prompt), tier=decision.tier)
        entries = catalog_entries(catalog)
        allowed = profiles.get(decision.tier) if profiles else None
        candidates = [(entry['model'], _effort(entry, decision.tier)) for entry in entries.values()
                      if not allowed or entry['model'] in allowed]
        candidates = [pair for pair in candidates if pair[1] is not None]
        recommendation = None
        if allow_advice and decision.reason not in {'continue-task', 'lighter-request-pending'}:
            recommendation = manager.recommend(group, (decision.model, decision.effort), candidates, active_task=context.active_task, state=state)
        if recommendation:
            model, effort = recommendation['pair']
            decision = replace(decision, model=model, effort=effort, reason=recommendation['reason'], selection='observed-policy',
                               changed=(model, effort) != (context.model, context.effort))
        if len(self.pending) < 64 and thread not in self.active:
            self.pending[thread] = {'manager': manager, 'context': group, 'model': decision.model, 'effort': decision.effort,
                                    'started': self.clock(), 'baseline': self.usage.get(thread), 'latest': None, 'mixed': False}
        return decision

    def response(self, message, method, params):
        result = message.get('result')
        if method in {'thread/start', 'thread/resume', 'thread/fork'} and isinstance(result, dict):
            thread = result.get('thread') or {}
            identity = thread.get('id')
            folder = thread.get('cwd') or params.get('cwd')
            if folder is None and method == 'thread/start':
                folder = str(self.cwd)
            if identity and isinstance(folder, str) and (identity in self.roots or len(self.roots) < 512):
                self.roots[identity] = folder
                if method == 'thread/start':
                    self.usage[identity] = 0
        if method == 'turn/start':
            thread = params.get('threadId')
            turn = (result or {}).get('turn') if isinstance(result, dict) else None
            if isinstance(turn, dict) and identifier(turn.get('id')):
                self.start(thread, turn['id'])
            elif 'error' in message:
                self.pending.pop(thread, None)
        event = message.get('params') or {}
        kind, thread = message.get('method'), event.get('threadId')
        if kind == 'turn/started':
            turn = event.get('turn') or {}
            self.start(thread, turn.get('id'))
        if kind == 'thread/settings/updated' and thread in self.active:
            settings = event.get('threadSettings') or {}
            active = self.active[thread]
            if settings.get('model') not in (None, active['model']) or settings.get('effort') not in (None, active['effort']):
                active['mixed'] = True
        if kind == 'thread/tokenUsage/updated':
            total = ((event.get('tokenUsage') or {}).get('total') or {}).get('totalTokens')
            if thread in self.roots and type(total) is int and 0 <= total <= 10**12:
                self.usage[thread] = total
                active = self.active.get(thread)
                if active and event.get('turnId') == active['turn']:
                    active['latest'] = total
        if kind == 'turn/completed':
            turn = event.get('turn') or {}
            active = self.active.get(thread)
            if active and turn.get('id') == active['turn']:
                self.active.pop(thread)
                if active['mixed'] or turn.get('status') != 'completed':
                    return
                baseline, latest = active['baseline'], active['latest']
                tokens = latest - baseline if baseline is not None and latest is not None and latest >= baseline else None
                active['manager'].record(thread, active['turn'], context=active['context'], model=active['model'], effort=active['effort'],
                    milliseconds=max(0, (self.clock() - active['started']) * 1000), tokens=tokens)

    def start(self, thread, turn):
        if not identifier(thread) or not identifier(turn) or thread not in self.pending:
            return
        if thread not in self.active:
            self.active[thread] = {**self.pending.pop(thread), 'turn': turn}
