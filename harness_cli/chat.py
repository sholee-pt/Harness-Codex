"""Opt-in Harness conversation UI. Codex owns execution, approval and history.

No raw conversation, routing state, global settings or project policy is saved
by this client. Existing native conversations remain usable by ordinary Codex.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import sys
import time

from .chat_transport import ChatServer, Console
from .model_routing import Context, MAX_PROMPT, advance, choose as route, catalog_entries
from .presentation import clean
from .session_settings import model_catalog
from .terminal_menu import choose

HELP = '''/model    Auto first, or fix a model and reasoning level
/status   Show routing settings and native usage (not measured task quality)
/task TEXT  Explicit new task; permits a lower routing tier
/done     Mark the current task complete; the next request is a new task
/failed   Record a verified task failure; does not retry automatically
/paste    Enter multiline text, ending with /end on its own line
/native   Continue this conversation in the original Codex CLI
/quit     Exit; native conversation history is retained
Ctrl+C interrupts the current turn; at the prompt it exits.
Other native slash commands, attachments and background-thread navigation use /native.'''


def select_model(server, context, catalog=None):
    catalog = catalog if catalog is not None else model_catalog(server, time.monotonic() + 30)
    entries = list(catalog_entries(catalog).values())
    selection = choose(server.progress, 'Model and reasoning', ['Auto — choose before each request',
        'Keep the current native model and reasoning'] + [entry.get('displayName') or entry['model'] for entry in entries])
    if selection == 0:
        return 'auto', None, catalog
    if selection == 1:
        return 'native', None, catalog
    entry = entries[selection - 2]
    options = [item['reasoningEffort'] for item in entry.get('supportedReasoningEfforts', [])]
    if not options:
        raise ValueError('This model has no advertised reasoning choices; use /native to select it.')
    default = entry.get('defaultReasoningEffort')
    options = ([default] if default in options else []) + [effort for effort in options if effort != default]
    effort = options[choose(server.progress, 'Reasoning (fixed until Auto is selected)', options)]
    return 'manual', (entry['model'], effort), catalog


def select_thread(server, root, session_id=None, last=False):
    if session_id and re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', session_id):
        return session_id
    cursor, cursors = None, set()
    matches = []
    for _ in range(20):
        params = {'cwd': str(root), 'archived': False, 'limit': 30, 'sortKey': 'updated_at', 'sortDirection': 'desc',
                  'sourceKinds': ['cli', 'appServer', 'vscode', 'exec']}
        if cursor:
            params['cursor'] = cursor
        page = server.call('thread/list', params)
        data = page.get('data')
        if not isinstance(data, list):
            raise ValueError('Invalid native conversation list.')
        data = [item for item in data if isinstance(item, dict) and isinstance(item.get('id'), str)
                and item.get('cwd') == str(root)]
        if session_id:
            matches += [item for item in data if item.get('name') == session_id or item.get('id') == session_id]
        elif last and data:
            return data[0]['id']
        elif data:
            labels = ['Cancel'] + [(item.get('name') or item.get('preview') or item['id'])[:100] for item in data]
            if page.get('nextCursor'):
                labels.append('More conversations')
            selection = choose(server.progress, 'Resume a Codex conversation', labels)
            if selection == 0:
                raise KeyboardInterrupt
            if selection <= len(data):
                return data[selection - 1]['id']
        cursor = page.get('nextCursor')
        if cursor is None:
            break
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise ValueError('Native conversation pagination did not advance.')
        cursors.add(cursor)
    else:
        raise ValueError('Conversation listing limit reached. Supply the exact session ID.')
    if session_id and len(matches) == 1:
        return matches[0]['id']
    if len(matches) > 1:
        raise ValueError('Multiple conversations have that name. Supply the exact session ID.')
    raise ValueError('No matching conversation in this project. Use new or supply an exact session ID.')


def session_context(result):
    model, effort = result.get('model'), result.get('reasoningEffort')
    # Metadata is not proof the saved task has finished. Resume conservatively.
    tier = 'deep' if effort in {'high', 'xhigh', 'max', 'ultra'} else 'balanced'
    return Context(tier, model if isinstance(model, str) else None,
                   effort if effort in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'} else None,
                   active_task=True)


def _thread(server, root, session_id=None):
    params = {'cwd': str(root)}
    if session_id:
        params['threadId'] = session_id
        params['excludeTurns'] = True
    result = server.call('thread/resume' if session_id else 'thread/start', params)
    thread = result.get('thread')
    if not isinstance(thread, dict) or not isinstance(thread.get('id'), str) or not thread['id']:
        raise ValueError('Codex did not return a native conversation ID.')
    if session_id and thread['id'] != session_id:
        raise ValueError('Codex resumed a different conversation ID; no task was submitted.')
    status = thread.get('status') or {}
    if isinstance(status, dict) and status.get('type') == 'active':
        raise ValueError('This native conversation is already running. Finish or interrupt it in its current client first.')
    server.thread_id = thread['id']
    return result


def _turn(server, text, decision, *, timeout=1800):
    deadline = time.monotonic() + timeout
    server.completed.clear()
    server.turn_id = None
    server.actual_model = None
    server.progress.begin_turn()
    try:
        response = server.call('turn/start', {'threadId': server.thread_id,
            'input': [{'type': 'text', 'text': text}], **decision.turn_overrides()}, timeout=min(30, timeout))
        turn_id = response.get('turn', {}).get('id')
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError('Codex did not acknowledge the turn ID; inspect the native conversation before retrying.')
        while True:
            if not server.completed:
                server.event(deadline)
                continue
            turn = server.completed.popleft()
            if turn.get('id') != turn_id:
                continue
            server.progress.idle()
            status = turn.get('status')
            if status not in {'completed', 'failed', 'interrupted'}:
                raise ValueError('Codex returned an unknown turn outcome.')
            if status != 'completed':
                server.progress.line('Turn ' + status + ': ' + clean((turn.get('error') or {}).get('message', '')))
            return status
    except (KeyboardInterrupt, TimeoutError):
        if server.turn_id:
            # Interrupt, then wait for a terminal event before allowing another turn.
            server.call('turn/interrupt', {'threadId': server.thread_id, 'turnId': server.turn_id}, timeout=10)
            stop_deadline = time.monotonic() + 10
            while not any(turn.get('id') == server.turn_id for turn in server.completed):
                server.event(stop_deadline)
        else:
            raise ValueError('Turn start was interrupted before acknowledgment. Inspect the native conversation; no automatic retry was sent.')
        server.progress.idle()
        server.progress.line('Turn interrupted. Check partial work before your next request.')
        return 'interrupted'


def run(command, root, activation, *, initial_task=None, resume=False, session_id=None, last=False,
        settings='ask', profiles=None, timeout=1800):
    """Return (exit code, optional ID to hand back to the original native CLI)."""
    from .model_routing import Decision
    if not sys.stdin.isatty():
        raise ValueError('Harness conversation UI requires an interactive terminal. Use the native CLI for noninteractive work.')
    with Console() as console:
        console.line('Harness UI · experimental · native Codex execution and history')
        console.line('Type /help for commands. /model offers Auto first. /native opens the original CLI.')
        server = ChatServer(command, root, console)
        context, fixed, mode = Context(), None, settings
        pending = initial_task
        try:
            server.initialize()
            catalog = model_catalog(server, time.monotonic() + 30)
            if resume:
                target = select_thread(server, root, session_id, last)
                result = _thread(server, root, target)
                context = session_context(result)
                console.line('Resumed: ' + server.thread_id)
                console.line('Native conversation history retained; /native opens its original history view.')
            else:
                defaults = next((entry for entry in catalog if entry.get('isDefault')), {})
                context = Context(model=defaults.get('model'), effort=defaults.get('defaultReasoningEffort'))
            if mode in {'ask', 'manual'}:
                mode, fixed, catalog = select_model(server, context, catalog)
            while True:
                console.idle()
                raw = pending if pending is not None else console.ask('You › ')
                pending = None
                text = raw.strip()
                if not text:
                    continue
                if text in {'/quit', '/exit'}:
                    return 0, None
                if text == '/help':
                    console.line(HELP)
                    continue
                if text == '/model':
                    mode, fixed, catalog = select_model(server, context)
                    console.line('Selection: ' + mode + (' · ' + ' / '.join(fixed) if fixed else ''))
                    continue
                if text == '/status':
                    console.line(f"Mode: {mode} | Last selection: {context.model or 'native'} / {context.effort or 'native'} | Task tier: {context.tier}")
                    if server.actual_model:
                        console.line('Native reroute: ' + clean(server.actual_model))
                    console.line('Session: ' + (server.thread_id or 'not created yet'))
                    if server.usage:
                        usage = server.usage.get('last', {})
                        console.line('Last native usage: ' + ', '.join(f'{clean(k)}={clean(v)}' for k, v in usage.items()))
                    console.line('Task quality and routing benefit: not measured. No separate selection-model calls.')
                    continue
                if text == '/native':
                    if server.thread_id:
                        return 0, server.thread_id
                    console.line('No conversation yet. Exit and run harness-codex new without --ui harness.')
                    continue
                if text == '/done':
                    context = replace(context, active_task=False, failures=0)
                    console.line('Next request starts a new task; automatic routing may choose a lower tier.')
                    continue
                if text == '/failed':
                    context = replace(context, active_task=True, failures=min(100, context.failures + 1))
                    console.line('Task failure recorded in memory. No automatic retry.')
                    continue
                if text == '/paste':
                    lines, size = [], 0
                    while True:
                        line = console.ask('… ')
                        if line == '/end':
                            break
                        size += len(line.encode('utf-8')) + 1
                        if size > MAX_PROMPT:
                            raise ValueError('Pasted request exceeds 32 KiB. Reference a project file instead.')
                        lines.append(line)
                    pending = '\n'.join(lines)
                    continue
                new_task = text.startswith('/task ')
                if new_task:
                    text = text[6:].strip()
                elif text.startswith('/'):
                    console.line('Unsupported Harness command. Use /help or /native for the original Codex menus.')
                    continue
                if mode == 'native':
                    # Validate transport input but do not impose inference overrides.
                    route(text, catalog, context=context, new_task=new_task, profiles=profiles)
                    decision = Decision(context.tier, None, None, 'native-settings', 'native', False)
                else:
                    decision = route(text, catalog, context=context, new_task=new_task, profiles=profiles,
                                     fixed=fixed if mode == 'manual' else None)
                console.line(f"{mode.title()} › {decision.model or 'native'} / {decision.effort or 'native'} · {decision.reason}")
                if not server.thread_id:
                    _thread(server, root)
                    console.line('Session: ' + server.thread_id)
                request = ((activation + '\n\nUser task:\n') if activation else '') + text
                status = _turn(server, request, decision, timeout=timeout)
                activation = None  # Sent with a real task once; never a separate bootstrap turn.
                if new_task:
                    context = replace(context, failures=0)
                context = advance(context, decision, succeeded=status in {'completed', 'interrupted'})
        except (EOFError, KeyboardInterrupt):
            return 130, None
        except (OSError, ValueError, TimeoutError) as exc:
            console.line('Conversation stopped: ' + clean(exc))
            return 1, None
        finally:
            if server.thread_id:
                console.line('Continue: harness-codex resume ' + server.thread_id + ' --ui harness')
                console.line('Original Codex UI: harness-codex resume ' + server.thread_id + ' --settings native')
            server.close()
