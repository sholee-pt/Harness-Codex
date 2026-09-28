"""Read-only model-routing preview; a proposal never changes a native session."""
from __future__ import annotations

import json
from pathlib import Path
import stat
import time

from . import model_routing as policy


def register(commands):
    parser = commands.add_parser('routing', help='Preview a next-turn model/reasoning decision without running a model.')
    parser.add_argument('prompt', nargs='?', help='Task to classify; use one quoted argument.')
    parser.add_argument('--prompt-file', type=Path, help='Read a UTF-8 task brief, up to 32 KiB.')
    parser.add_argument('--catalog', type=Path, help='Use a saved model/list response offline; otherwise query native metadata only.')
    parser.add_argument('--profiles', type=Path, help='JSON model preferences for fast, balanced and deep tiers.')
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--codex-binary', default='codex')
    parser.add_argument('--previous-tier', choices=policy.TIERS, default='balanced')
    parser.add_argument('--previous-model')
    parser.add_argument('--previous-effort', help='A reasoning option advertised by the model catalog.')
    parser.add_argument('--continue-task', action='store_true', help='Keep the previous task selection unless escalation is justified.')
    parser.add_argument('--failures', type=int, default=0, help='Verified consecutive failures in this task, not model self-ratings.')
    parser.add_argument('--model', help='Preview a manual fixed model; requires --effort.')
    parser.add_argument('--effort', help='A reasoning option advertised by the selected model.')
    parser.add_argument('--adaptive', choices=('on', 'off', 'status', 'clear'), help='Manage opt-in local outcome-based Auto advice.')
    parser.add_argument('--adaptive-policy', type=Path, help='JSON quality/confidence/cost-gain limits; no model names.')
    parser.add_argument('--feedback', help='An observed work-item reference from adaptive status or operations evidence.')
    parser.add_argument('--outcome', choices=('unknown', 'verified', 'user-accepted', 'failed', 'needs-revision'))
    parser.add_argument('--source', choices=('verification', 'user-reported'))
    parser.add_argument('--cause', choices=('unknown', 'inference', 'environment'), default='unknown')
    parser.add_argument('--yes', action='store_true', help='Confirm clearing this project\'s adaptive evidence and disabling advice.')


def evidence_module(source_root):
    import importlib
    import sys
    scripts = Path(source_root).resolve() / '.agents/skills/harness/scripts'
    sys.path.insert(0, str(scripts))
    try:
        module = importlib.import_module('harness_routing_evidence')
        if Path(module.__file__).resolve().parent != scripts:
            raise ValueError('Another Harness evidence helper is loaded; start a fresh command')
        return module
    finally:
        sys.path.remove(str(scripts))


def read_text(path, limit):
    path = path.expanduser()
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Routing inputs must be regular files.')
    with path.open('rb') as stream:
        import os
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Routing inputs must be regular files.')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Routing input exceeds its documented size limit.')
    return data.decode('utf-8-sig')


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate routing JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(read_text(path, 2 * 1024 * 1024), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite routing JSON value.')))


def load_catalog(value):
    if isinstance(value, dict):
        value = value.get('result', value)
        if not isinstance(value, dict) or value.get('nextCursor') is not None:
            raise ValueError('Provide a complete model catalog, not a partial page.')
        value = value.get('data')
    policy.catalog_entries(value)
    return value


def run(args, source_root):
    from .main import build_parser
    from .presentation import Progress, clean
    if args.adaptive or args.adaptive_policy or args.feedback:
        if args.prompt is not None or args.prompt_file is not None:
            raise ValueError('Choose an evidence action or a routing preview')
        manager = evidence_module(source_root).RoutingEvidence(args.project.expanduser().resolve(strict=True))
        if args.feedback:
            if args.adaptive or args.adaptive_policy or not args.outcome or not args.source:
                raise ValueError('Feedback requires outcome/source and cannot change settings')
            report = manager.feedback(args.feedback, args.outcome, args.source, args.cause)
        elif args.adaptive == 'clear':
            if not args.yes or args.adaptive_policy:
                raise ValueError('Clearing adaptive evidence requires --yes without policy changes')
            report = manager.clear()
        elif args.adaptive in {'on', 'off'} or args.adaptive_policy:
            report = manager.configure(None if args.adaptive not in {'on', 'off'} else args.adaptive == 'on',
                                       read_json(args.adaptive_policy) if args.adaptive_policy else None)
        else:
            report = manager.status()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print('Adaptive Auto: ' + ('enabled' if report.get('enabled') else 'disabled') if 'enabled' in report else 'Routing feedback: ' + ('recorded' if report.get('recorded') else report.get('reason', 'unchanged')))
            for item in report.get('workItems', []):
                print(f"  {item['reference']}: {item['outcome']} | tokens: {item['tokens']} | time: {item['milliseconds']:.0f}ms")
            print('Local evidence only; no additional model call. Quality/cost benefit is not established.')
        return 0
    if args.prompt is None and args.prompt_file is None:
        # Explicitly offline, like --help; do not start an empty model session.
        build_parser(source_root).parse_args(['routing', '--help'])
    if args.prompt is not None and args.prompt_file is not None:
        raise ValueError('Choose a quoted prompt or --prompt-file, not both.')
    if bool(args.model) != bool(args.effort):
        raise ValueError('Manual routing requires both --model and --effort.')
    prompt = read_text(args.prompt_file, policy.MAX_PROMPT) if args.prompt_file else args.prompt
    context = policy.Context(args.previous_tier, args.previous_model, args.previous_effort,
                             args.failures, args.continue_task)
    policy.classify(prompt, context)  # Reject malformed requests before Codex/network work.
    profiles = read_json(args.profiles) if args.profiles else None
    # Validate custom policy before connecting, including all unselected tiers.
    policy.choose(prompt, [], context=context, profiles=profiles)
    if args.catalog:
        catalog = load_catalog(read_json(args.catalog))
        catalog_source = 'file-unverified-availability'
    else:
        from .configuration import Server
        from .project import _codex_command
        from .session_settings import model_catalog
        root = args.project.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Project path must be a directory.')
        with Progress('Read available Codex models', compact=True) as progress:
            server = Server(_codex_command(args.codex_binary), root, progress)
            try:
                server.initialize()
                catalog = model_catalog(server, time.monotonic() + 30)
            finally:
                server.close()
        catalog_source = 'native-metadata'
    started = time.perf_counter()
    decision = policy.choose(prompt, catalog, context=context, profiles=profiles,
                             fixed=(args.model, args.effort) if args.model else None)
    report = {'operation': 'routing-preview', 'applied': False, 'decision': decision.report(),
              'turnOverrides': decision.turn_overrides(), 'catalogSource': catalog_source,
              'selectionMilliseconds': round((time.perf_counter() - started) * 1000, 3),
              'modelCalls': 0, 'taskQuality': 'not-measured', 'costBenefit': 'not-measured'}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print('Routing preview — native session unchanged')
        print(f"  Tier: {decision.tier} | Model: {clean(decision.model or 'native unresolved')} | Reasoning: {decision.effort or 'native unresolved'}")
        print(f'  Reason: {decision.reason} | Selection: {decision.selection}')
        print('  No model request or project write. Task quality and cost benefit are not measured.')
    return 0
