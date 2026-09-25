#!/usr/bin/env python3
"""Opt-in, bounded project maintenance; ordinary turns never launch a model.

Only enum signals, HMAC references, revisions and counters persist outside the
project. The native agent reviews an eligible batch at a subsequent turn boundary.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

import harness_eval_store as storage
from harness_eval_lock import FileLock
import harness_state

REASONS = ('scope-changed', 'workflow-gap', 'routing-mismatch', 'verification-gap', 'user-request')
MODES = ('off', 'suggest', 'auto')
MAX_STATE = 256 * 1024
MAX_CANDIDATES = 32
MAX_SESSIONS = 32
REVIEW_SECONDS = 180
COOLDOWN_SECONDS = 3600
REVIEWS_PER_DAY = 2
SIGNAL_POLICY = '1'


def signal_context(mode):
    return ('Project maintenance is ' + mode + '. Keep the existing harness by default. '
            'Only explicit responsibility changes or recurring workflow/routing/verification gaps justify a signal; '
            'then read .agents/skills/harness/references/maintenance.md and record the bounded evidence signal. '
            'Ordinary bugs, single failures and new topics do not justify harness review. '
            'Do not review every turn or add agents merely because scope grows. Native hooks announce eligible batches.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def default_state():
    return {'schema': 1, 'mode': 'off', 'candidates': {}, 'sessions': {}, 'lease': None,
            'attempts': [], 'notified': None, 'appliedRevision': None,
            'metrics': {'reviews': 0, 'applied': 0, 'unchanged': 0, 'reviewSeconds': 0,
                        'reportedTokens': 0, 'unmeasuredReviews': 0}}


def checked(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    for parent in (path, *path.parents):
        if parent.is_symlink() or (os.path.lexists(parent) and
                getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Maintenance paths must not contain links or reparse points')
    return path


class Maintenance:
    def __init__(self, root, state_root=None, *, clock=time.time):
        self.root = checked(root)
        self.store = storage.EvaluationStore(state_root=checked(state_root or storage.default_state_root()))
        storage.ensure_state_outside_repositories(self.store.root, [self.root])
        self.clock = clock

    def _location(self, create=False):
        checked(self.store.root)
        if not self.store.secret_path.exists() and not create:
            return None
        checked(self.store.secret_path)
        # Selected folders stay distinct, including two folders in one Git repo.
        key = self.store.fingerprint(os.path.normcase(str(self.root)).encode())
        return checked(self.store.root / 'maintenance' / key / 'state.json')

    def _read(self, path):
        if path is None or not path.exists():
            return default_state()
        if path.stat().st_size > MAX_STATE:
            raise ValueError('Maintenance state exceeds its size limit')
        value = json.loads(path.read_text(encoding='utf-8'))
        expected = default_state()
        if (not isinstance(value, dict) or set(value) != set(expected) or value['schema'] != 1
                or value['mode'] not in MODES or not isinstance(value['candidates'], dict)
                or len(value['candidates']) > MAX_CANDIDATES or not isinstance(value['sessions'], dict)
                or len(value['sessions']) > MAX_SESSIONS or not isinstance(value['attempts'], list)
                or len(value['attempts']) > REVIEWS_PER_DAY or not isinstance(value['metrics'], dict)
                or set(value['metrics']) != set(expected['metrics'])):
            raise ValueError('Invalid maintenance state; preserve it for inspection')
        for key, item in value['candidates'].items():
            if (not re.fullmatch(r'[0-9a-f]{64}', key) or not isinstance(item, dict)
                    or set(item) != {'reason', 'evidence', 'observations', 'status'}
                    or item['reason'] not in REASONS or item['status'] not in {'pending', 'resolved'}
                    or not re.fullmatch(r'[0-9a-f]{64}', item['evidence'])
                    or not isinstance(item['observations'], list) or len(item['observations']) > 8
                    or any(not re.fullmatch(r'[0-9a-f]{64}', ref) for ref in item['observations'])):
                raise ValueError('Invalid maintenance candidate')
        for key, session in value['sessions'].items():
            if (not re.fullmatch(r'[0-9a-f]{64}', key) or not isinstance(session, dict)
                    or not {'active', 'children', 'seenRevision'} <= set(session) <= {'active', 'children', 'seenRevision', 'seenPolicy'}
                    or ('seenPolicy' in session and session['seenPolicy'] not in {None, *('1:' + mode for mode in MODES)})
                    or type(session['active']) is not bool or not isinstance(session['children'], list)
                    or len(session['children']) > 64
                    or any(not re.fullmatch(r'[0-9a-f]{64}', ref) for ref in session['children'])
                    or (session['seenRevision'] is not None and not re.fullmatch(r'[0-9a-f]{64}', session['seenRevision']))):
                raise ValueError('Invalid maintenance session')
        if any(type(n) not in (int, float) or n < 0 or not n < float('inf') for n in value['attempts']):
            raise ValueError('Invalid maintenance review timestamps')
        if any(type(n) not in (int, float) or n < 0 or not n < float('inf') for n in value['metrics'].values()):
            raise ValueError('Invalid maintenance metrics')
        lease = value['lease']
        if lease is not None:
            if (not isinstance(lease, dict) or set(lease) != {'id', 'revision', 'candidates', 'session', 'started', 'deadline'}
                    or not re.fullmatch(r'[0-9a-f]{32}', lease['id'])
                    or not re.fullmatch(r'[0-9a-f]{64}', lease['revision'])
                    or not isinstance(lease['candidates'], list)
                    or any(key not in value['candidates'] for key in lease['candidates'])
                    or type(lease['started']) not in (int, float) or type(lease['deadline']) not in (int, float)
                    or not 0 < lease['deadline'] - lease['started'] <= REVIEW_SECONDS):
                raise ValueError('Invalid maintenance lease')
        for name in ('notified', 'appliedRevision'):
            if value[name] is not None and not re.fullmatch(r'[0-9a-f]{64}', value[name]):
                raise ValueError('Invalid maintenance revision')
        return value

    @contextmanager
    def transaction(self, *, create=False):
        path = self._location(create)
        if path is None or (not path.exists() and not create):
            yield default_state()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            path.parent.chmod(0o700)
        with FileLock(checked(path.with_suffix('.lock')), timeout=1):
            value = self._read(path)
            before = digest(value)
            yield value
            if digest(value) != before or not path.exists():
                harness_state.atomic_write_text(path, json.dumps(value, sort_keys=True) + '\n', mode=0o600)

    def manifest(self):
        path = checked(self.root / '.harness/manifest.json')
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('A configured project harness is required')
        value = json.loads(path.read_text(encoding='utf-8'))
        import harness_metadata
        harness_metadata.artifact_contract_state(value)
        return value

    def configure(self, mode):
        if mode not in MODES:
            raise ValueError('Unknown maintenance mode')
        self.manifest()
        with self.transaction(create=True) as state:
            state['mode'] = mode
            state['lease'] = None
        return self.status()

    def _eligible(self, state):
        return [key for key, item in state['candidates'].items()
                if item['status'] == 'pending' and (item['reason'] in {'scope-changed', 'user-request'}
                                                   or len(item['observations']) >= 2)]

    def clear(self):
        # Explicit CLI confirmation is required. Resetting disables maintenance;
        # project artifacts, native history and other project records are retained.
        with self.transaction() as state:
            state.clear()
            state.update(default_state())
        return self.status()

    def status(self):
        state = self._read(self._location())
        return {'mode': state['mode'], 'pending': len(self._eligible(state)),
                'reviewInProgress': state['lease'] is not None, 'metrics': state['metrics'],
                'automaticScope': 'existing-skill-content-only', 'qualityBenefit': 'not-established',
                'tokenBudgetEnforcement': 'not-available-in-native-interactive-session',
                'reviewTimeLimitSeconds': REVIEW_SECONDS, 'reviewsPerDay': REVIEWS_PER_DAY}

    def signal(self, reason, evidence, observation):
        if reason not in REASONS or not observation or len(observation) > 256:
            raise ValueError('A supported reason and bounded observation reference are required')
        # Only relevant, explicitly selected source evidence is read; never scan a tree.
        path = harness_state.resolve_inside(self.root, evidence, must_exist=True)
        if (not path.is_file() or path.stat().st_size > 1024 * 1024
                or any(part.casefold() in {'.git', '.harness'} for part in Path(evidence).parts)):
            raise ValueError('Signal evidence must be a bounded project source file')
        with self.transaction() as state:
            if state['mode'] == 'off':
                return {'recorded': False, 'reason': 'disabled'}
            evidence_hash = self.store.fingerprint(path.read_bytes())
            key = self.store.fingerprint((reason + '\0' + evidence + '\0' + evidence_hash).encode())
            ref = self.store.fingerprint(observation.encode())
            if key not in state['candidates']:
                if len(state['candidates']) >= MAX_CANDIDATES:
                    return {'recorded': False, 'reason': 'candidate-limit; use maintenance clear --yes to disable and reset records'}
                state['candidates'][key] = {'reason': reason, 'evidence': evidence_hash, 'observations': [], 'status': 'pending'}
            candidate = state['candidates'][key]
            if candidate['status'] == 'resolved':
                return {'recorded': False, 'reason': 'already-reviewed-with-this-evidence'}
            if ref not in candidate['observations'] and len(candidate['observations']) < 8:
                candidate['observations'].append(ref)
            return {'recorded': True, 'candidate': key, 'eligible': key in self._eligible(state)}

    def _busy(self, state, session):
        return any(item['children'] or (key != session and item['active']) for key, item in state['sessions'].items())

    def _claim(self, state, session):
        now = self.clock()
        state['attempts'] = [t for t in state['attempts'] if now - t < 86400]
        if state['lease'] or self._busy(state, session):
            return None
        candidates = self._eligible(state)
        if (not candidates or len(state['attempts']) >= REVIEWS_PER_DAY
                or (state['attempts'] and now - state['attempts'][-1] < COOLDOWN_SECONDS)):
            return None
        manifest = self.manifest()
        state['lease'] = {'id': uuid.uuid4().hex, 'revision': digest(manifest),
                          'candidates': candidates, 'session': session, 'started': now,
                          'deadline': now + REVIEW_SECONDS}
        state['attempts'].append(now)
        state['metrics']['reviews'] += 1
        return state['lease']

    def begin(self, session='manual'):
        with self.transaction() as state:
            if state['mode'] == 'off':
                return {'status': 'disabled'}
            session_ref = self.store.fingerprint(session.encode())
            lease = self._claim(state, session_ref)
            return {'status': 'claimed', **lease} if lease else {'status': 'deferred'}

    def _limited_application(self, plan):
        import harness_apply
        old = self.manifest()
        application = harness_apply.build_application(self.root, harness_apply.load_plan(checked(plan)))
        new = json.loads(application['manifestText'])
        for field in ('topology', 'capabilityPolicies', 'instructionFile', 'workspace'):
            if new.get(field) != old.get(field):
                raise ValueError('Role, routing-contract or permission changes require explicit config review')
        if application['report']['removalCandidates']:
            raise ValueError('Automatic maintenance cannot remove artifacts')
        changed = [item for item in application['report']['actions'] if item['action'] != 'unchanged'
                   and item['path'] != '.harness/manifest.json']
        if len(changed) > 2:
            raise ValueError('Automatic maintenance is limited to two existing skills per review')
        if not changed:
            raise ValueError('No skill correction was proposed; finish the review as unchanged')
        changed_bytes = 0
        old_modes = {item['path']: item.get('mode') for item in old['managedFiles']}
        if any(item.get('mode') != old_modes.get(item['path']) for item in new['managedFiles']):
            raise ValueError('Automatic maintenance cannot change file permissions')
        import difflib
        for item in changed:
            name = item['path']
            if item['action'] != 'update' or not name.startswith('.agents/skills/') or not name.endswith('/SKILL.md'):
                raise ValueError('Automatic maintenance may only update existing managed skill content')
            before = harness_state.resolve_inside(self.root, name).read_text(encoding='utf-8')
            after = application['artifacts'][name]
            changed_bytes += sum(len(line.encode()) for line in difflib.ndiff(before.splitlines(True), after.splitlines(True))
                                 if line.startswith(('+ ', '- ')))
        if changed_bytes > 8192:
            raise ValueError('Automatic maintenance exceeds the 8 KiB changed-content limit')
        return application

    def finish(self, lease_id, decision, *, plan=None, tokens=None):
        if decision not in {'unchanged', 'proposed', 'deferred', 'apply'}:
            raise ValueError('Unknown maintenance decision')
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError('Reported tokens must be a nonnegative integer')
        with self.transaction() as state:
            lease = state['lease']
            if not lease or lease['id'] != lease_id:
                raise ValueError('Review lease is missing or no longer current')
            if decision == 'apply':
                if state['mode'] != 'auto':
                    raise ValueError('Automatic apply was not enabled for this project')
                if self.clock() > lease['deadline']:
                    raise ValueError('Review deadline passed; preserve the existing harness and finish as deferred')
                if digest(self.manifest()) != lease['revision']:
                    raise ValueError('Project harness changed during review; review the current revision')
                if self._busy(state, lease['session']):
                    raise ValueError('Another task or child agent is active; defer maintenance')
                if plan is None:
                    raise ValueError('An independently validated application plan is required')
                import harness_apply
                application = self._limited_application(plan)
                if self.clock() > lease['deadline']:
                    raise ValueError('Review deadline passed before apply')
                harness_apply.apply_application(application)
                state['appliedRevision'] = digest(self.manifest())
                state['metrics']['applied'] += 1
            for key in lease['candidates']:
                state['candidates'][key]['status'] = 'resolved'
            if decision == 'unchanged':
                state['metrics']['unchanged'] += 1
            state['metrics']['reviewSeconds'] += max(0, self.clock() - lease['started'])
            if tokens is None:
                state['metrics']['unmeasuredReviews'] += 1
            else:
                state['metrics']['reportedTokens'] += tokens
            state['lease'] = None
            return {'status': decision, 'revision': state['appliedRevision'], 'taskQuality': 'not-measured'}

    def hook(self, event):
        kind = event.get('hook_event_name')
        if kind not in {'SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt', 'SessionEnd', 'SubagentStart', 'SubagentStop'}:
            return ''
        with self.transaction() as state:
            if state['mode'] == 'off':
                return ''
            # A missed/ignored review cannot permanently block maintenance or
            # cause repeated model work on the same unresolved batch.
            expired = state['lease']
            if expired and self.clock() > expired['deadline']:
                for key in expired['candidates']:
                    state['candidates'][key]['status'] = 'resolved'
                state['metrics']['reviewSeconds'] += expired['deadline'] - expired['started']
                state['metrics']['unmeasuredReviews'] += 1
                state['lease'] = None
            raw_id = event.get('session_id')
            if not isinstance(raw_id, str) or not raw_id or len(raw_id) > 256:
                return ''
            session_id = self.store.fingerprint(raw_id.encode())
            if kind == 'SessionEnd':
                state['sessions'].pop(session_id, None)
                return ''
            if session_id not in state['sessions']:
                if len(state['sessions']) >= MAX_SESSIONS:
                    return 'Harness maintenance paused: session limit reached. Existing harness remains active.'
                state['sessions'][session_id] = {'active': False, 'children': [], 'seenRevision': None}
            session = state['sessions'][session_id]
            if kind in {'SubagentStart', 'SubagentStop'}:
                child = self.store.fingerprint(str(event.get('agent_id', 'unknown')).encode())
                if kind == 'SubagentStart' and child not in session['children']:
                    if len(session['children']) >= 64:
                        raise ValueError('Maintenance child-agent limit reached')
                    session['children'].append(child)
                elif kind == 'SubagentStop' and child in session['children']:
                    session['children'].remove(child)
                return ''
            if kind in {'Stop', 'Interrupt'}:
                session['active'] = False
                return ''
            policy = SIGNAL_POLICY + ':' + state['mode']
            messages = []
            if session.get('seenPolicy') != policy or kind == 'SessionStart' and event.get('source') == 'compact':
                messages.append(signal_context(state['mode']))
                session['seenPolicy'] = policy
            if kind == 'SessionStart':
                # Compaction can emit SessionStart during an active turn.
                # Keep existing activity; a new entry already starts inactive.
                return '\n'.join(messages)
            session['active'] = True
            revision = state['appliedRevision']
            if revision and session['seenRevision'] != revision:
                messages.append('Harness skill content changed. Re-read the current project-harness and relevant skills before this task. '
                                'This is a reload instruction, not proof of native discovery or task quality.')
                session['seenRevision'] = revision
            eligible = self._eligible(state)
            if eligible:
                if state['mode'] == 'auto':
                    lease = self._claim(state, session_id)
                    if lease:
                        reasons = sorted({state['candidates'][key]['reason'] for key in eligible})
                        messages.append('A bounded Harness maintenance review is due, reasons: ' + ', '.join(reasons) + '. '
                            'Read .agents/skills/harness/references/maintenance.md. Review only those concerns against current evidence; '
                            'keep the harness unchanged unless an existing skill needs a justified correction. '
                            f'Review lease {lease["id"]}; deadline {int(lease["deadline"])} UTC Unix seconds. '
                            'Finish or defer before the user task; do not start a separate model, remove verification, '
                            'add agents, change permissions or run GPU training. Resolve using harness-codex maintenance finish. '
                            'This does not authorize commit/push. If no relevant evidence is available, choose unchanged.')
                else:
                    fingerprint = digest(sorted(eligible))
                    if state['notified'] != fingerprint:
                        messages.append('Harness maintenance has review candidates. Mention them briefly when relevant; '
                                        'keep the current harness until the user requests config review. Do not launch an automatic review.')
                        state['notified'] = fingerprint
            return '\n'.join(messages)


def find_root(cwd):
    root = checked(cwd)
    for candidate in (root, *root.parents):
        if (candidate / '.harness/manifest.json').is_file():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    clear = commands.add_parser('clear')
    clear.add_argument('--yes', action='store_true', required=True)
    settings = commands.add_parser('configure')
    settings.add_argument('--mode', choices=MODES, required=True)
    signal = commands.add_parser('signal')
    signal.add_argument('--reason', choices=REASONS, required=True)
    signal.add_argument('--evidence', required=True)
    signal.add_argument('--observation', required=True, help='A turn/run reference, never raw task text')
    begin = commands.add_parser('begin')
    begin.add_argument('--session', default='manual')
    finish = commands.add_parser('finish')
    finish.add_argument('--lease', required=True)
    finish.add_argument('--decision', choices=('unchanged', 'proposed', 'deferred', 'apply'), required=True)
    finish.add_argument('--plan', type=Path)
    finish.add_argument('--reported-tokens', type=int)
    commands.add_parser('hook')
    args = parser.parse_args()
    try:
        if args.command == 'hook':
            data = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Oversized hook input')
            event = json.loads(data)
            root = find_root(event.get('cwd', ''))
            if root is None:
                return 0
            context = Maintenance(root).hook(event)
            if context:
                print(json.dumps({'hookSpecificOutput': {'hookEventName': event['hook_event_name'], 'additionalContext': context}}))
            return 0
        manager = Maintenance(args.root)
        if args.command == 'status':
            result = manager.status()
        elif args.command == 'clear':
            result = manager.clear()
        elif args.command == 'configure':
            result = manager.configure(args.mode)
        elif args.command == 'signal':
            result = manager.signal(args.reason, args.evidence, args.observation)
        elif args.command == 'begin':
            result = manager.begin(args.session)
        else:
            result = manager.finish(args.lease, args.decision, plan=args.plan, tokens=args.reported_tokens)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        if args.command == 'hook':
            print(json.dumps({'systemMessage': 'Harness maintenance unavailable; existing project configuration preserved.'}))
            return 0
        print('harness maintenance: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
