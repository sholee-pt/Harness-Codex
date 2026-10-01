"""Prepare only owned maintenance hooks through Codex's native trust interface."""
from __future__ import annotations

import json
import subprocess
import time

from . import maintenance, presentation as ui
from .configuration import Server
from .paths import checked_path, external_location, project_root


class MetadataServer(Server):
    def answer(self, request_id, method, params):
        self.send({'id': request_id, 'error': {'code': -32601, 'message': 'Hook setup accepts metadata responses only'}})
        raise ValueError('Unexpected Codex request during hook setup')


def token(value, limit=4096):
    return isinstance(value, str) and 0 < len(value) <= limit and value.isprintable()


def owned_definitions(path, expected_command):
    receipt = checked_path(path.parent / 'harness-maintenance-hooks.json')
    original, ownership = maintenance._hook_snapshot(path), maintenance._hook_snapshot(receipt)
    from .hook_state import receipt as read_receipt
    saved = read_receipt(ownership or b'{}')
    if saved['command'] != expected_command:
        raise ValueError('Maintenance hook ownership is unavailable')
    command = saved['command']
    value = json.loads(original or b'{}')
    hooks = value.get('hooks') if isinstance(value, dict) else None
    if not isinstance(hooks, dict):
        raise ValueError('Maintenance hook definitions are unavailable')
    for event in maintenance.EVENTS:
        expected = maintenance.hook_definition(event, command)
        matches = []
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError('Malformed maintenance hook groups')
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                raise ValueError('Malformed maintenance hook group')
            for handler in group['hooks']:
                if isinstance(handler, dict) and handler.get('command') == command:
                    if set(group) != {'hooks'} or handler != expected:
                        raise ValueError('An owned hook was customized; review it with /hooks')
                    matches.append(handler)
        if len(matches) != 1:
            raise ValueError('Expected one owned maintenance handler per event')
    return command, {path: original, receipt: ownership}


def selected_hooks(result, root, path, command):
    entries = result.get('data') if isinstance(result, dict) else None
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError('Unsupported hooks/list response')
    entry = entries[0]
    if not isinstance(entry.get('cwd'), str) or project_root(entry['cwd']) != project_root(root) or entry.get('errors'):
        raise ValueError('Codex could not resolve the selected project hooks')
    hooks = entry.get('hooks')
    if not isinstance(hooks, list) or len(hooks) > 2048:
        raise ValueError('Unsupported hook inventory')
    selected = {}
    for hook in hooks:
        if not isinstance(hook, dict):
            raise ValueError('Invalid native hook metadata')
        if hook.get('command') != command or hook.get('source') != 'user':
            continue
        if not isinstance(hook.get('sourcePath'), str) or external_location(hook['sourcePath']) != path:
            continue
        event_name = hook.get('eventName')
        event = next((name for name in maintenance.EVENTS if name[0].lower() + name[1:] == event_name), None)
        if event not in maintenance.EVENTS:
            continue
        expected = maintenance.hook_definition(event, command)
        if (hook.get('handlerType') != 'command' or hook.get('isManaged') is not False
                or hook.get('matcher') is not None or hook.get('pluginId') is not None
                or hook.get('async') is not False or hook.get('statusMessage') is not None
                or hook.get('timeoutSec') != expected['timeout']
                or hook.get('additionalContextLimit') != expected.get('additionalContextLimit')
                or not token(hook.get('key')) or not token(hook.get('currentHash'), 256)
                or hook.get('trustStatus') not in ('trusted', 'untrusted', 'modified')
                or type(hook.get('enabled')) is not bool or event in selected):
            raise ValueError('Owned hook metadata differs from the installed definition')
        selected[event] = hook
    if len(selected) != len(maintenance.EVENTS) or len({h['key'] for h in selected.values()}) != len(selected):
        raise ValueError('Codex did not expose all owned hooks; check hook support and managed policy')
    return selected


def user_layer(result, path):
    config = result.get('config') if isinstance(result, dict) else None
    if not isinstance(config, dict):
        raise ValueError('Codex configuration is unavailable')
    features = config.get('features') or {}
    if (not isinstance(features, dict) or features.get('hooks', features.get('codex_hooks', True)) is False
            or config.get('allow_managed_hooks_only') is True):
        raise ValueError('Native settings disable user hooks; settings were not overridden')
    layers = result.get('layers')
    if not isinstance(layers, list):
        raise ValueError('Codex did not provide configuration versions')
    matches = [layer for layer in layers if isinstance(layer, dict) and isinstance(layer.get('name'), dict)
               and layer['name'].get('type') == 'user' and layer['name'].get('profile') is None]
    if (len(matches) != 1 or not isinstance(matches[0]['name'].get('file'), str)
            or external_location(matches[0]['name']['file']) != path or matches[0].get('disabledReason')
            or not token(matches[0].get('version'))):
        raise ValueError('Native user configuration layer could not be identified')
    return matches[0]['version']


def trust(command, root, path, expected_command, progress):
    expected, snapshots = owned_definitions(path, expected_command)
    config_path = checked_path(path.parent / 'config.toml')
    deadline = time.monotonic() + 20
    server = MetadataServer(command, root, progress)
    def call(method, params):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Hook trust setup timed out')
        return server.call(method, params, timeout=remaining)
    try:
        server.initialize(timeout=max(.1, deadline - time.monotonic()))
        response = call('configRequirements/read', None)
        if not isinstance(response, dict) or 'requirements' not in response:
            raise ValueError('Unsupported native requirements response')
        requirements = response['requirements']
        if requirements is not None and not isinstance(requirements, dict):
            raise ValueError('Unsupported native requirements response')
        requirements = requirements or {}
        features = requirements.get('featureRequirements') or {}
        if (not isinstance(features, dict) or requirements.get('allowManagedHooksOnly') is True
                or features.get('hooks', features.get('codex_hooks', True)) is False):
            raise ValueError('Managed policy disables user hooks; policy was not overridden')
        version = user_layer(call('config/read', {'cwd': str(root), 'includeLayers': True}), config_path)
        hooks = selected_hooks(call('hooks/list', {'cwds': [str(root)]}), root, path, expected)
        edits = {h['key']: {'trusted_hash': h['currentHash'], 'enabled': True} for h in hooks.values()
                 if h['trustStatus'] != 'trusted' or not h['enabled']}
        if any(maintenance._hook_snapshot(target) != content for target, content in snapshots.items()):
            raise ValueError('Hook definitions changed during setup; retry init or use /hooks')
        if edits:
            from .hook_state import begin_trust, encoded, finish_trust, receipt, replace_file
            ownership = checked_path(path.parent / 'harness-maintenance-hooks.json')
            before = maintenance._hook_snapshot(config_path)
            original_receipt = snapshots[ownership]
            pending = begin_trust(receipt(original_receipt), before, edits)
            intent = encoded(pending)
            replace_file(ownership, original_receipt, intent)
            snapshots[ownership] = intent
            try:
                report = call('config/batchWrite', {'edits': [{'keyPath': 'hooks.state', 'value': edits, 'mergeStrategy': 'upsert'}],
                              'filePath': str(config_path), 'expectedVersion': version, 'reloadUserConfig': True})
                committed = encoded(finish_trust(pending, maintenance._hook_snapshot(config_path), edits))
                replace_file(ownership, intent, committed)
                snapshots[ownership] = committed
            except BaseException:
                if maintenance._hook_snapshot(config_path) == before:
                    replace_file(ownership, intent, original_receipt)
                raise
            if not isinstance(report, dict) or report.get('status') != 'ok':
                raise ValueError('Native hook trust was not confirmed; inspect /hooks')
        verified = selected_hooks(call('hooks/list', {'cwds': [str(root)]}), root, path, expected)
        if (any(maintenance._hook_snapshot(target) != content for target, content in snapshots.items())
                or any(h['trustStatus'] != 'trusted' or not h['enabled']
                       or h['currentHash'] != hooks[event]['currentHash'] or h['key'] != hooks[event]['key']
                       for event, h in verified.items())):
            raise ValueError('Hook trust verification did not pass; inspect /hooks')
        return {'status': 'trusted', 'count': len(verified), 'changed': bool(edits)}
    finally:
        server.close()


def prepare(source_root, root, *, binary='codex', mode='auto'):
    try:
        expected = maintenance.hook_command(source_root)
        installed = maintenance.install_hooks(source_root)
        if mode == 'manual':
            return {'status': 'manual-review-required', 'guidance': 'Use /hooks to review and trust the Harness handler.'}
        from .project import _codex_command
        with ui.Progress('Preparing Harness hook trust', compact=True) as progress:
            result = trust(_codex_command(binary), project_root(root), checked_path(installed['path']), expected, progress)
        return result
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'status': 'manual-review-required', 'warning': ui.clean(exc),
                'guidance': 'Automatic hook trust is unavailable. Use /hooks to review the Harness handler; project preferences were not changed by trust setup.'}
