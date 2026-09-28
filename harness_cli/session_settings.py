"""Select native Codex settings for one configuration conversation, in memory."""
from __future__ import annotations

import time
from .terminal_menu import choose


def mode_choice(progress, mode):
    if mode != 'ask':
        return mode
    return ('auto', 'manual', 'native')[choose(progress, 'Model selection', [
        'Automatic — use Codex recommended defaults; preserve a resumed session',
        'Manual — choose model, reasoning and permissions',
        'Keep native settings',
    ])]


def current_settings(server, root, deadline):
    result = server.call('config/read', {'cwd': str(root), 'includeLayers': False},
                         timeout=min(30, deadline - time.monotonic()))
    config = result.get('config', {})
    if not isinstance(config, dict):
        raise ValueError('Codex returned invalid configuration settings')
    return {'model': config.get('model'), 'reasoningEffort': config.get('model_reasoning_effort'),
            'approvalPolicy': config.get('approval_policy'),
            'sandbox': {'type': config.get('sandbox_mode') or 'native profile'}}


def automatic(server, deadline, *, resume=False, current=None):
    models = model_catalog(server, deadline)
    if not models:
        raise ValueError('No visible models are available; check native Codex account/provider settings.')
    current = current or {}
    retained = next((m for m in models if m['model'] == current.get('model')), None) if resume else None
    if retained and (current.get('reasoningEffort') is None or current['reasoningEffort'] in
                     [item.get('reasoningEffort') for item in retained.get('supportedReasoningEfforts', [])]):
        server.progress.line('Automatic: keep the available resumed conversation model and reasoning.')
        return {}
    model = retained or next((m for m in models if m.get('isDefault') is True), None)
    if model is None:
        if resume:
            raise ValueError('The resumed selection is unavailable and no supported default is advertised. Choose --settings manual.')
        server.progress.line('No recommended model in the catalog; keeping native settings.')
        return {}
    effort = model.get('defaultReasoningEffort')
    efforts = model.get('supportedReasoningEfforts')
    supported = [e.get('reasoningEffort') for e in efforts if isinstance(e, dict)] if isinstance(efforts, list) else []
    if not isinstance(effort, str) or effort not in supported:
        if resume:
            raise ValueError('No supported reasoning default for resume. Choose --settings manual.')
        server.progress.line('No supported default reasoning level; keeping native settings.')
        return {}
    reason = 'replaces unavailable or unknown saved settings' if resume else 'Codex recommended default'
    server.progress.line(f"Automatic: {model['model']} / {effort} ({reason}).")
    return {'model': model['model'], 'effort': effort}


def model_catalog(server, deadline):
    models, cursors = {}, set()
    cursor = None
    for _ in range(20):
        params = {'limit': 50, 'includeHidden': False}
        if cursor:
            params['cursor'] = cursor
        page = server.call('model/list', params, timeout=min(30, deadline - time.monotonic()))
        data = page.get('data')
        if not isinstance(data, list):
            raise ValueError('Codex model catalog is unavailable. Retry with --settings native or --interactive.')
        for model in data:
            if not isinstance(model, dict) or not isinstance(model.get('model'), str) or not model['model']:
                raise ValueError('Codex returned an invalid model catalog; retry with --settings native.')
            if not model.get('hidden'):
                models.setdefault(model['model'], model)
        cursor = page.get('nextCursor')
        if cursor is None:
            return list(models.values())
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            break
        cursors.add(cursor)
    raise ValueError('Codex model catalog pagination did not finish; retry with --settings native.')


def select(server, current, root, deadline):
    """No config writes, default model guesses, or fallback permission grants."""
    progress = server.progress
    models = model_catalog(server, deadline)
    progress.line('Configuration settings | this Codex conversation only')
    progress.line('Enter keeps the current setting. Global Codex settings are unchanged.')
    retained = next((m for m in models if m['model'] == current.get('model')), None)
    if not models:
        raise ValueError('No visible models are available; use native Codex to check account access.')
    if not retained and current.get('model'):
        progress.line('The previous model is unavailable. Choose a model from the current catalog.')
    offset = int(retained is not None or not current.get('model'))
    selected = choose(progress, 'Model', ([f"Keep current: {current.get('model', 'native default')}"] if offset else []) +
                      [f"{m.get('displayName') or m['model']} ({m['model']})" for m in models])
    overrides = {}
    chosen = selected >= offset
    model = models[selected - offset] if chosen else retained
    changed_model = bool(chosen and model['model'] != current.get('model'))
    if chosen:
        overrides['model'] = model['model']
    if model:
        efforts = model.get('supportedReasoningEfforts')
        if (not isinstance(efforts, list) or any(not isinstance(e, dict) or not isinstance(e.get('reasoningEffort'), str)
                                               or not e['reasoningEffort'] for e in efforts)):
            raise ValueError('Codex returned invalid reasoning options; retry with --settings native.')
        default = model.get('defaultReasoningEffort') if changed_model else current.get('reasoningEffort')
        reset_effort = changed_model or default is not None and default not in [e['reasoningEffort'] for e in efforts]
        if reset_effort:
            default = model.get('defaultReasoningEffort')
            progress.line('Reasoning options refreshed; select a supported value or the model default.')
        if reset_effort and (not default or default not in [e['reasoningEffort'] for e in efforts]):
            raise ValueError('The selected model has no supported default reasoning level. Use --interactive.')
        selection = choose(progress, 'Reasoning',
                           [f"{'Model default' if reset_effort else 'Keep current'}: {default or 'native default'}"] +
                           [f"{e['reasoningEffort']} — {e.get('description', '')}" for e in efforts])
        if selection:
            overrides['effort'] = efforts[selection - 1]['reasoningEffort']
        elif reset_effort:
            # Do not accidentally inherit an incompatible effort from another model.
            overrides['effort'] = default
    else:
        progress.line('Reasoning: keep current (this model is not in the visible catalog).')
    sandbox = current.get('sandbox') or {}
    approval = current.get('approvalPolicy')
    current_label = sandbox.get('type', 'native profile') if isinstance(sandbox, dict) else 'native profile'
    current_label += ' / ' + (approval if isinstance(approval, str) else 'custom approval policy')
    selection = choose(progress, 'Permissions', [
        'Keep current: ' + current_label,
        'Read only; network restricted; ask you for additional access',
        'Workspace and temp writes; network restricted; ask you for additional access',
        'Full access; unrestricted files/network; no command approval prompts',
    ])
    if selection == 3:
        answer = progress.ask('Allow unrestricted Codex access for this conversation? Type yes; Enter keeps current: ')
        if answer != 'yes':
            selection = 0
    if selection:
        policies = {1: {'type': 'readOnly', 'networkAccess': False},
                    2: {'type': 'workspaceWrite', 'writableRoots': [str(root)], 'networkAccess': False,
                        'excludeSlashTmp': False, 'excludeTmpdirEnvVar': False},
                    3: {'type': 'dangerFullAccess'}}
        overrides.update(sandboxPolicy=policies[selection], approvalPolicy='never' if selection == 3 else 'on-request',
                         approvalsReviewer='user')
    progress.line('Settings selected. Codex enforces any managed policy restrictions.')
    return overrides
