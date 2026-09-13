"""Bounded private stdio bridge for the original Codex TUI extension."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness_cli.model_routing import Context, choose, validate_context


def select(value):
    if not isinstance(value, dict) or set(value) != {'prompt', 'catalog', 'context', 'model', 'effort', 'hasImages'}:
        raise ValueError('Invalid native selector request')
    if type(value['hasImages']) is not bool or not isinstance(value['catalog'], list) or len(value['catalog']) > 200:
        raise ValueError('Invalid native catalog')
    catalog = []
    for entry in value['catalog']:
        if not isinstance(entry, dict):
            raise ValueError('Invalid native model')
        if entry.get('show_in_picker') is not True:
            continue
        if value['hasImages'] and 'image' not in entry.get('input_modalities', []):
            continue
        options = entry.get('supported_reasoning_efforts', [])
        if not isinstance(options, list) or any(not isinstance(option, dict) for option in options):
            raise ValueError('Invalid native reasoning options')
        catalog.append({'model': entry.get('model'), 'isDefault': entry.get('is_default'),
            'defaultReasoningEffort': entry.get('default_reasoning_effort'),
            'supportedReasoningEfforts': [{'reasoningEffort': option.get('effort')}
                for option in options]})
    previous = value['context']
    if previous is None:
        effort = value['effort']
        tier = 'deep' if effort in {'high', 'xhigh', 'max', 'ultra'} else 'balanced'
        context = Context(tier=tier, model=value['model'], effort=effort)
    elif isinstance(previous, dict) and set(previous) == set(asdict(Context())):
        context = Context(**previous)
    else:
        raise ValueError('Invalid native routing context')
    validate_context(context)
    prompt = value['prompt']
    profiles = None
    profile = os.environ.get('HARNESS_ROUTER_PROFILES')
    if profile:
        from harness_cli.routing import read_json
        profiles = read_json(Path(profile))
    decision = choose(prompt, catalog, context=context, profiles=profiles)
    next_context = replace(context, tier=decision.tier, model=decision.model or context.model,
                           effort=decision.effort or context.effort, active_task=True)
    return {'model': decision.model, 'effort': decision.effort,
            'context': asdict(next_context)}


def main():
    try:
        payload = sys.stdin.buffer.read(256 * 1024 + 1)
        if len(payload) > 256 * 1024:
            raise ValueError('Oversized request')
        result = select(json.loads(payload))
        sys.stdout.write(json.dumps(result, separators=(',', ':')))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        # No raw prompt, path, catalog or provider error goes to logs.
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
