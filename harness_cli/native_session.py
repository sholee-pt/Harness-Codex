"""Read-only native settings discovery and owned configuration-session cleanup."""
from __future__ import annotations

import json
import sys
import time

from .configuration import Server
from .presentation import Progress, clean
from .session_settings import automatic, current_settings, mode_choice, select


def settings_arguments(command, root, mode):
    if mode == 'native':
        return []
    with Progress('Select conversation settings', compact=True) as progress:
        mode = mode_choice(progress, mode)
        if mode == 'native':
            return []
        server = Server(command, root, progress)
        try:
            server.initialize()
            deadline = time.monotonic() + 60
            overrides = {}
            while mode == 'manual':
                selected = select(server, current_settings(server, root, deadline), root, deadline)
                if selected is not None:
                    overrides = selected
                    break
                mode = mode_choice(progress, 'ask')
                deadline = time.monotonic() + 60
            if mode == 'auto':
                overrides = automatic(server, deadline)
        finally:
            server.close()
    result = []
    if overrides.get('model'):
        result += ['--model', overrides['model']]
    if overrides.get('effort'):
        result += ['-c', 'model_reasoning_effort=' + json.dumps(overrides['effort'])]
    policy = overrides.get('sandboxPolicy', {})
    sandbox = policy.get('type')
    if sandbox:
        result += ['--sandbox', {'readOnly': 'read-only', 'workspaceWrite': 'workspace-write',
                                'dangerFullAccess': 'danger-full-access'}[sandbox],
                   '--ask-for-approval', overrides['approvalPolicy'], '-c',
                   'approvals_reviewer=' + json.dumps(overrides['approvalsReviewer'])]
        if sandbox == 'workspaceWrite':
            # Replace inherited workspace permissions with the user's conversation selection.
            for source, key in (('writableRoots', 'writable_roots'), ('networkAccess', 'network_access'),
                                ('excludeSlashTmp', 'exclude_slash_tmp'), ('excludeTmpdirEnvVar', 'exclude_tmpdir_env_var')):
                result += ['-c', 'sandbox_workspace_write.' + key + '=' + json.dumps(policy[source], ensure_ascii=False)]
    return result


def archive_configuration(command, root, session_id):
    """Called only for a newly created configuration thread after project validation."""
    try:
        with Progress('Keep completed setup out of the conversation picker', compact=True) as progress:
            server = Server(command, root, progress)
            try:
                server.initialize()
                server.call('thread/archive', {'threadId': session_id}, timeout=15)
            finally:
                server.close()
        print('Setup conversation archived; its history remains available in Codex.')
    except (OSError, ValueError, TimeoutError) as exc:
        print('Project configuration succeeded, but setup conversation archiving was unavailable: ' + clean(exc), file=sys.stderr)


def execution_diagnostic(message):
    text = str(message).casefold()
    if any(term in text for term in ('bwrap', 'rtm_newaddr', 'unprivileged_userns', 'creating new namespace failed')):
        return ('Sandbox setup failed. Harness does not configure bubblewrap or automatically relax native permissions. '
                'Check the same project with native Codex and inspect the host/container namespace restrictions. '
                'Use Codex permission controls for an allowed retry; do not regenerate the harness to repair the sandbox.')
    if ('approv' in text and any(term in text for term in ('limit', 'quota', 'budget', '한도'))):
        return ('The native approval reviewer reported a limit. Resume after the limit resets, or choose an available '
                'user-review mode through Codex permissions. Harness will not silently switch reviewers or broaden access.')
    return None
