"""Explain and select optional project improvements after successful configuration."""
from __future__ import annotations

import subprocess
import sys

from . import hook_trust, maintenance, presentation as ui, routing
from .terminal_menu import choose


def configure(args, source_root, root, *, emit=True):
    if getattr(args, 'dry_run', False) or getattr(args, 'install_only', False):
        return
    mode, adaptive = getattr(args, 'maintenance', None), getattr(args, 'adaptive', None)
    try:
        current = maintenance.helper(source_root, root, ['status'])
        manager = routing.evidence_module(source_root).RoutingEvidence(root)
        observed = manager.status()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if mode is not None or adaptive is not None:
            raise ValueError('Project preferences could not be read; existing settings were preserved. ' + str(exc)) from exc
        ui.report({'state': 'unavailable', 'warnings': [str(exc)],
                   'guidance': 'Inspect harness-codex maintenance and harness-codex routing --adaptive status; existing preferences were preserved.'},
                  title='Project preferences', error=True)
        return
    interactive = (getattr(args, 'command', None) == 'init' and not getattr(args, 'json', False)
                   and not ui.JSON_MODE.get() and sys.stdin.isatty() and sys.stdout.isatty())
    progress = ui.Progress('Project preferences', stream=sys.stdout)
    if interactive and (mode is None or adaptive is None):
        progress.line('\nProject preferences | Enter accepts the selection; Left goes back; Ctrl+C cancels these choices.')
        select_mode, select_adaptive = mode is None, adaptive is None
        modes = [current['mode'], *(value for value in ('off', 'suggest', 'auto') if value != current['mode'])]
        values = [observed['enabled'], not observed['enabled']]
        mode_index = adaptive_index = 0
        if select_mode:
            progress.line('Maintenance reviews specific recurring concerns, not every conversation.')
            progress.line('Auto may edit existing skills within limits; reviews use conversation tokens and require trusted hooks.')
        if select_adaptive:
            progress.line('Adaptive Auto uses local timing/token records plus recorded quality feedback; it makes no extra model call.')
            progress.line('It does not grade task quality automatically. Advice applies only when /model is Auto; manual choices stay manual.')
        while True:
            if select_mode:
                labels = {'off': 'Off - no automatic review', 'suggest': 'Suggest - notify when review is warranted',
                          'auto': 'Auto - review and make bounded skill corrections'}
                mode_index = choose(progress, 'Harness maintenance', [labels[value] + (' (current)' if index == 0 else '')
                                                                      for index, value in enumerate(modes)], initial=mode_index)
                mode = modes[mode_index]
            if select_adaptive:
                labels = {False: 'Off - keep ordinary Auto rules', True: 'On - use comparable verified outcomes for Auto advice'}
                selected = choose(progress, 'Improve Auto selection from local results',
                                  [labels[value] + (' (current)' if index == 0 else '') for index, value in enumerate(values)],
                                  back=select_mode, summary=['Maintenance: ' + (mode or current['mode'])], initial=adaptive_index)
                if selected == -1:
                    continue
                adaptive_index = selected
                adaptive = 'on' if values[adaptive_index] else 'off'
            break
    # Collect both choices before applying either, so Ctrl+C never half-applies a menu.
    if mode is not None and mode != current['mode']:
        current = maintenance.enable(source_root, root, mode, quiet=True)
    if adaptive is not None and (adaptive == 'on') != observed['enabled']:
        observed = manager.configure(adaptive == 'on')
    trust = None
    if getattr(args, 'command', None) == 'init':
        trust = hook_trust.prepare(source_root, root, binary=getattr(args, 'codex_binary', 'codex'),
                                   mode=getattr(args, 'hook_trust', 'auto'))
    commands = ['harness-codex maintenance --mode suggest', 'harness-codex routing --adaptive on',
                'harness-codex maintenance', 'harness-codex routing --adaptive status']
    if not emit:
        return
    if getattr(args, 'json', False) or ui.JSON_MODE.get():
        ui.report({'state': 'configured', 'maintenance': current['mode'], 'adaptiveRouting': observed['enabled'],
                   'hookTrust': trust or {'status': 'unchanged'},
                   'changeCommands': commands, 'maintenanceModes': ['off', 'suggest', 'auto'], 'adaptiveModes': ['off', 'on']},
                  title='Project preferences')
        return
    progress.line('Project preferences: maintenance ' + current['mode'] + '; adaptive Auto ' + ('on' if observed['enabled'] else 'off') + '.')
    if trust:
        if trust['status'] == 'trusted':
            progress.line('Harness hook trust: ready. Project modes are independent; off remains off.')
        else:
            progress.line('Harness hook trust: manual review required.')
            if trust.get('warning'):
                progress.line(trust['warning'])
            progress.line(trust['guidance'])
    elif current['mode'] != 'off':
        progress.line('Hook trust is unchanged. If native hooks are blocked, run init to prepare Harness trust or inspect /hooks.')
    if observed['enabled']:
        progress.line('Auto advice needs the Harness Codex integration and Auto selected in /model; quality feedback must be recorded.')
    progress.line('Change anytime from this project (or add --project PATH):')
    progress.line('  ' + commands[0] + '  (off / suggest / auto)')
    progress.line('  ' + commands[1] + '  (on / off)')
    progress.line('Status only: ' + commands[2] + ' | ' + commands[3])
