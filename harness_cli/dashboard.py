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
        return {'state': 'not-installed', 'definitions': 0, 'expectedDefinitions': len(maintenance.EVENTS),
                'missingDefinitions': list(maintenance.EVENTS), 'recordedTrustMatches': 0,
                'trust': 'unconfirmed', 'localPolicy': 'not-checked', 'runtime': 'not-tested'}
    saved = receipt(saved)
    value = json.loads(maintenance._hook_snapshot(checked_path(home / 'hooks.json')) or b'{}')
    definitions = value.get('hooks', {}) if isinstance(value, dict) else None
    if not isinstance(definitions, dict):
        raise ValueError('Malformed hook definitions')
    count, missing, modified, duplicate = 0, [], [], []
    for event in maintenance.EVENTS:
        groups = definitions.get(event, [])
        if not isinstance(groups, list):
            raise ValueError('Malformed hook event groups')
        exact, changed = 0, False
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                raise ValueError('Malformed hook event group')
            for handler in group['hooks']:
                if isinstance(handler, dict) and handler.get('command') == saved['command']:
                    if set(group) == {'hooks'} and handler == maintenance.hook_definition(event, saved['command']):
                        exact += 1
                    else:
                        changed = True
        count += exact
        if not exact:
            missing.append(event)
        if changed:
            modified.append(event)
        if exact > 1:
            duplicate.append(event)
    _, config, states = configuration(maintenance._hook_snapshot(checked_path(home / 'config.toml')))
    trusted = sum(1 for key, entry in saved.get('trust', {}).items()
                  if entry['after'] is not None and states.get(key) == entry['expected']
                  and entry['expected'].get('enabled') is True and entry['expected'].get('trusted_hash'))
    features = config.get('features', {})
    if not isinstance(features, dict):
        raise ValueError('Malformed native hook feature settings')
    disabled = features.get('hooks', features.get('codex_hooks', True)) is False or config.get('allow_managed_hooks_only') is True
    return {'state': 'incomplete' if missing or modified or duplicate else 'registered',
            'definitions': count, 'expectedDefinitions': len(maintenance.EVENTS),
            'missingDefinitions': missing, 'modifiedDefinitions': modified, 'duplicateDefinitions': duplicate,
            'recordedTrustMatches': trusted,
            'trust': 'recorded-matches' if trusted >= len(maintenance.EVENTS) else 'unconfirmed',
            'localPolicy': 'user-hooks-disabled' if disabled else 'no-known-local-block',
            'nativeTrust': 'not-tested', 'runtime': 'not-tested'}


def maintenance_availability(manager, hooks):
    """Explain observed prerequisites without claiming native execution or task benefit."""
    if manager.get('mode') == 'off':
        return {'state': 'off', 'reasons': [], 'notes': [], 'basis': 'offline-recorded-prerequisites-only',
                'reviewEligibility': 'disabled', 'runtime': 'not-tested'}
    reasons, waiting, notes = [], [], []
    if manager.get('trackingIncomplete'):
        reasons.append('Session tracking is incomplete; automatic changes are paused.')
    if manager.get('applicationMarkerPresent'):
        reasons.append('An application marker is present; wait or inspect interrupted-apply recovery.')
    if manager.get('historyCapacityBlocked'):
        reasons.append('Change history is full of unresolved entries; review existing changes.')
    if any(change.get('status') == 'review-required' for change in manager.get('changes', [])):
        reasons.append('A previous change requires review before further automatic changes.')
    if manager.get('automaticChangesPaused') and not reasons:
        reasons.append('Automatic changes are paused by the recorded maintenance state.')
    if manager.get('blockingSessions'):
        waiting.append('Active session or child markers are present; their completion must be established.')
    if manager.get('reviewInProgress'):
        waiting.append('A review is already in progress.')
    if manager.get('reviewExpired'):
        notes.append('The previous review expired; a new review must claim current context again.')
    if manager.get('contextRequired'):
        detail = str(manager['contextRequired']) + ' eligible concerns need current session evidence context.'
        (waiting if manager['contextRequired'] >= manager.get('pending', 0) else notes).append(detail)
    schedule = manager.get('scheduling', {})
    if schedule.get('budgetBlocked'):
        reasons.append('The reported-token budget is blocked' + (' by unmeasured reviews.' if schedule.get('unmeasuredReviewsLastDay') else '.'))
    if schedule.get('reviewLimitReached'):
        waiting.append('The rolling 24-hour review limit has been reached.')
    if schedule.get('intervalRemainingSeconds', 0) > 0:
        waiting.append('The review interval has not elapsed.')
    if hooks.get('state') == 'not-installed':
        reasons.append('Harness hook registration is missing.')
    elif hooks.get('state') == 'incomplete':
        reasons.append('Harness hook definitions are missing, modified or duplicated.')
    elif hooks.get('state') != 'registered':
        waiting.append('Harness hook registration could not be checked.')
    if hooks.get('localPolicy') == 'user-hooks-disabled':
        reasons.append('Local native settings disable user hooks.')
    if hooks.get('trust') != 'recorded-matches':
        waiting.append('Native hook trust is unconfirmed; inspect /hooks in the selected project.')
    mode = manager.get('mode')
    state = ('off' if mode == 'off' else 'unavailable' if mode not in {'suggest', 'auto'} else
             'paused' if reasons else 'waiting' if waiting else 'idle' if not manager.get('pending') else
             'static-prerequisites-met')
    return {'state': state, 'reasons': reasons + waiting, 'notes': notes, 'basis': 'offline-recorded-prerequisites-only',
            'reviewEligibility': 'session-and-native-checks-required', 'runtime': 'not-tested'}


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
    result = {
        'maintenance': read(maintenance_status),
        'routing': read(lambda: routing.evidence_module(source_root).RoutingEvidence(root).status()),
        'jev': read(lambda: jev.execute(SimpleNamespace(project=root, jev_action='status'), source_root)),
        'graft': read(lambda: graft.execute(SimpleNamespace(project=root, graft_action='status'), source_root)),
        'hooks': read(hooks_status),
    }
    result['maintenance']['availability'] = maintenance_availability(result['maintenance'], result['hooks'])
    result['routing']['sessionSelection'] = 'not-observed; inspect /model'
    return result


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
    availability = manager.get('availability') or maintenance_availability(manager, hooks)
    rows += ['Maintenance setting: ' + str(manager.get('mode', 'unavailable')) + (' (advice only; no automatic edits)' if manager.get('mode') == 'suggest' else '') + ' | eligible concerns: ' + str(manager.get('pending', 'unknown')),
             'Maintenance availability: ' + availability['state'] + ' (offline prerequisites only)',
             *availability['reasons'][:2],
             'Adaptive evidence setting: ' + ('unavailable' if 'enabled' not in routing_state else 'on' if routing_state['enabled'] else 'off'),
             'Session model / Auto selection: not observed here; inspect /model.',
             'Jev: ' + str(jev_state.get('mode', 'unavailable')) + ' | credential: ' + ('available' if jev_state.get('keyAvailable') else 'unavailable') + ' | connection: not tested',
             'Graft: ' + ('unavailable' if 'enabled' not in graph else 'on' if graph['enabled'] else 'off') + ' | index: ' + ('present; freshness not checked' if graph.get('indexed') else 'not confirmed'),
             'Hooks: ' + str(hooks.get('state', 'unavailable')) + ' | definitions: ' + str(hooks.get('definitions', 'unknown')) + '/' + str(hooks.get('expectedDefinitions', len(maintenance.EVENTS))),
             'Hook trust: ' + str(hooks.get('trust', 'unconfirmed')) + ' | recorded matches: ' + str(hooks.get('recordedTrustMatches', 'unknown')),
             'Native hook policy/trust and live execution: not tested here.', '',
             'Runtime loading: not-tested', 'Task quality: not-measured',
             'Recorded counters alone do not establish Harness benefit.']
    schedule = manager.get('scheduling', {})
    if manager.get('mode') in {'suggest', 'auto'} and (schedule.get('reviewLimitReached') or schedule.get('intervalRemainingSeconds', 0) > 0):
        rows += ['Review starts in last 24h: ' + str(schedule.get('reviewsLastDay', 'unknown')) + '/' + str(schedule.get('reviewsPerDay', 'unknown')),
                 'Current candidate interval remaining: ' + str(round(schedule.get('intervalRemainingSeconds', 0))) + 's.']
    if availability['reasons'] or availability.get('notes'):
        rows.append('Maintenance details: ' + ui.command(['harness-codex', 'maintenance', '--project', root]))
    if any(hooks.get(name) for name in ('missingDefinitions', 'modifiedDefinitions', 'duplicateDefinitions')):
        rows.append('Hook definition details: ' + ui.command(['harness-codex', 'status', '--project', root, '--json']))
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
