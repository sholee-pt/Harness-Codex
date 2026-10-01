"""Offline Harness status, shared by the CLI and management interfaces."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from . import graft, jev, maintenance, presentation as ui, routing
from .paths import checked_path, storage_location


def hooks_status():
    from .hook_state import configuration, receipt
    home = storage_location(Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    saved = maintenance._hook_snapshot(checked_path(home / 'harness-maintenance-hooks.json'))
    if saved is None:
        return {'state': 'not-installed', 'runtime': 'not-tested'}
    saved = receipt(saved)
    value = json.loads(maintenance._hook_snapshot(checked_path(home / 'hooks.json')) or b'{}')
    definitions = value.get('hooks', {})
    if not isinstance(definitions, dict):
        raise ValueError('Malformed hook definitions')
    count = 0
    for event in maintenance.EVENTS:
        for group in definitions.get(event, []):
            for handler in group.get('hooks', []):
                if handler == maintenance.hook_definition(event, saved['command']):
                    count += 1
    _, _, states = configuration(maintenance._hook_snapshot(checked_path(home / 'config.toml')))
    trusted = sum(1 for key, entry in saved.get('trust', {}).items()
                  if states.get(key) == entry['expected'] and entry['expected'].get('enabled') is True)
    return {'state': 'registered', 'definitions': count, 'recordedTrustMatches': trusted, 'runtime': 'not-tested'}


def collect(source_root, root):
    def read(function):
        try:
            return function()
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return {'state': 'unavailable', 'error': ui.clean(exc)}
    def maintenance_status():
        import subprocess
        try:
            return maintenance.helper(source_root, root, ['status'])
        except subprocess.SubprocessError:
            return {'state': 'unavailable', 'error': 'Maintenance status timed out'}
    return {
        'maintenance': read(maintenance_status),
        'routing': read(lambda: routing.evidence_module(source_root).RoutingEvidence(root).status()),
        'jev': read(lambda: jev.execute(SimpleNamespace(project=root, jev_action='status'), source_root)),
        'graft': read(lambda: graft.execute(SimpleNamespace(project=root, graft_action='status'), source_root)),
        'hooks': read(hooks_status),
    }


def display(report, root, version):
    if ui.JSON_MODE.get():
        ui.report(report, title='Project harness')
        return
    features = report.get('features', {})
    manager, routing_state, jev_state, graph, hooks = [features.get(key, {}) for key in ('maintenance', 'routing', 'jev', 'graft', 'hooks')]
    rows = [f'Project: {root.name}', f'Directory: {root}',
            'Project harness: ' + report['state'], 'Generator: ' + report.get('generator', 'unknown'), '']
    integration = report.get('codexIntegration', {})
    if integration:
        rows.append('Codex integration: ' + integration.get('state', 'unknown'))
        if integration.get('error'):
            rows.append(integration['error'])
    rows += ['Maintenance: ' + str(manager.get('mode', 'unavailable')) + ' | eligible concerns: ' + str(manager.get('pending', 'unknown')),
             'Adaptive Auto: ' + ('unavailable' if 'enabled' not in routing_state else 'on' if routing_state['enabled'] else 'off') + ' | session model: use /model',
             'Jev: ' + str(jev_state.get('mode', 'unavailable')) + ' | credential: ' + ('available' if jev_state.get('keyAvailable') else 'unavailable') + ' | connection: not tested',
             'Graft: ' + ('unavailable' if 'enabled' not in graph else 'on' if graph['enabled'] else 'off') + ' | index: ' + ('present; freshness not checked' if graph.get('indexed') else 'not confirmed'),
             'Hooks: ' + str(hooks.get('state', 'unavailable')) + ' | live execution: not tested', '',
             'Runtime loading: not-tested', 'Task quality: not-measured',
             'Recorded counters alone do not establish Harness benefit.']
    for name, value in features.items():
        if value.get('error'):
            rows.append(name + ': ' + value['error'])
    rows.extend(report.get('errors', [])[:6])
    if len(report.get('errors', [])) > 6:
        rows.append('More findings: use --json or doctor.')
    if report.get('nextCommand'):
        rows += ['', 'Next: ' + report['nextCommand']]
    if report.get('hookPreparation'):
        preparation = report['hookPreparation']
        rows += ['Hook preparation: ' + preparation.get('status', 'unknown')]
        rows += [preparation[key] for key in ('warning', 'guidance') if preparation.get(key)]
    ui.box(rows, title=f'Harness for Codex ({version})', subtitle='by sholee-pt')
