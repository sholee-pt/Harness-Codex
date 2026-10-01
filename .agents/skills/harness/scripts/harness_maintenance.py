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
import subprocess
import sys
import time
import uuid

import harness_eval_store as storage
from harness_eval_lock import FileLock, project_lock
import harness_state
import harness_maintenance_history as history
import harness_maintenance_policy as cadence

REASONS = ('scope-changed', 'workflow-gap', 'routing-mismatch', 'verification-gap', 'user-request')
MODES = ('off', 'suggest', 'auto')
MAX_STATE = 512 * 1024
MAX_CANDIDATES = 32
MAX_SESSIONS = 32
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
    return {'schema': 4, 'mode': 'off', 'candidates': {}, 'sessions': {}, 'trackingIncomplete': False, 'lease': None, 'changes': [],
            'policy': dict(cadence.DEFAULTS), 'recentReviews': [], 'retired': {},
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
        self.root = harness_state.workspace_root(root)
        self.store = storage.EvaluationStore(state_root=state_root)
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
        previous_fields = set(expected) - {'trackingIncomplete'}
        new_fields = {'policy', 'recentReviews', 'retired'}
        if isinstance(value, dict) and value.get('schema') == 1 and set(value) == previous_fields - {'changes', *new_fields}:
            value = {**value, 'schema': 2, 'changes': []}
        if isinstance(value, dict) and value.get('schema') == 2 and set(value) == previous_fields - new_fields:
            value = {**value, 'schema': 3, **{name: expected[name] for name in new_fields}}
        if isinstance(value, dict) and value.get('schema') == 3 and set(value) == previous_fields:
            value = {**value, 'schema': 4, 'trackingIncomplete': False}
        if (not isinstance(value, dict) or set(value) != set(expected) or value['schema'] != 4
                or type(value['trackingIncomplete']) is not bool
                or value['mode'] not in MODES or not isinstance(value['candidates'], dict)
                or len(value['candidates']) > MAX_CANDIDATES or not isinstance(value['sessions'], dict)
                or len(value['sessions']) > MAX_SESSIONS or not isinstance(value['attempts'], list)
                or len(value['attempts']) > cadence.MAX_REVIEWS or not isinstance(value['metrics'], dict)
                or set(value['metrics']) != set(expected['metrics'])):
            raise ValueError('Invalid maintenance state; preserve it for inspection')
        history.validate(value['changes'])
        cadence.validate(value['policy'], value['recentReviews'])
        if (not isinstance(value['retired'], dict) or len(value['retired']) > 128
                or any(not history.hashed(key) or not cadence.valid_number(at) for key, at in value['retired'].items())):
            raise ValueError('Invalid retired maintenance candidates')
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
                    or not 0 < lease['deadline'] - lease['started'] <= cadence.MAX_SECONDS):
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
                self._write(path, value)

    def _write(self, path, value):
        history.validate(value['changes'])
        content = json.dumps(value, sort_keys=True) + '\n'
        if len(content.encode('utf-8')) > MAX_STATE:
            raise ValueError('Maintenance state exceeds its size limit; existing state preserved')
        harness_state.atomic_write_text(path, content, mode=0o600)

    def manifest(self):
        path = checked(self.root / '.harness/manifest.json')
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('A configured project harness is required')
        value = json.loads(path.read_text(encoding='utf-8'))
        import harness_metadata
        harness_metadata.artifact_contract_state(value)
        return value

    def configure(self, mode=None, policy=None):
        if mode is not None and mode not in MODES:
            raise ValueError('Unknown maintenance mode')
        self.manifest()
        with self.transaction(create=True) as state:
            if mode is not None:
                state['mode'] = mode
            if policy is not None:
                candidate = {**state['policy'], **policy}
                cadence.validate(candidate, state['recentReviews'])
                state['policy'] = candidate
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
        expired = state['lease'] is not None and self.clock() > state['lease']['deadline']
        changes = history.summary(state['changes'])
        return {'mode': state['mode'], 'pending': len(self._eligible(state)),
                'blockingSessions': [{'ref': key, 'active': item['active'], 'children': len(item['children'])}
                                     for key, item in state['sessions'].items() if item['active'] or item['children']],
                'reviewInProgress': state['lease'] is not None and not expired, 'reviewExpired': expired, 'metrics': state['metrics'],
                'automaticScope': 'existing-skill-content-only', 'qualityBenefit': 'not-established',
                'tokenBudgetEnforcement': 'not-available-in-native-interactive-session',
                'reviewTimeLimitSeconds': state['policy']['reviewSeconds'], 'reviewsPerDay': state['policy']['reviewsPerDay'],
                'policy': state['policy'], 'scheduling': cadence.schedule(state, self.clock(), [state['candidates'][key] for key in self._eligible(state)]),
                **changes, 'trackingIncomplete': state['trackingIncomplete'],
                'automaticChangesPaused': state['trackingIncomplete'] or changes['automaticChangesPaused']}

    def recover_session(self, session_ref):
        if not isinstance(session_ref, str) or (session_ref != 'all' and not re.fullmatch(r'[0-9a-f]{64}', session_ref)):
            raise ValueError('Use an opaque session ref from maintenance status')
        with self.transaction() as state:
            # A caller must confirm that the session and its children stopped.
            # Elapsed time alone never establishes that native writers exited.
            if session_ref == 'all':
                recovered = bool(state['sessions']) or state['trackingIncomplete']
                state['sessions'].clear()
                state['trackingIncomplete'] = False
            else:
                recovered = state['sessions'].pop(session_ref, None) is not None
            if state['lease'] is not None and (session_ref == 'all' or state['lease']['session'] == session_ref):
                lease = state['lease']
                duration = max(0, min(self.clock(), lease['deadline']) - lease['started'])
                state['metrics']['reviewSeconds'] += duration
                state['metrics']['unmeasuredReviews'] += 1
                cadence.record(state, self.clock(), duration, None, 'deferred')
                state['lease'] = None
                recovered = True
        return {'status': 'session-recovered' if recovered else 'session-absent'}

    def observe(self, change, observation, outcome, source, revision, *, model=None, effort=None, category=None, runtime=None):
        if not isinstance(observation, str) or not observation or len(observation) > 256:
            raise ValueError('Provide a bounded work-item reference, not task text')
        with self.transaction() as state:
            if state['mode'] == 'off':
                return {'recorded': False, 'reason': 'disabled'}
            item = history.find(state['changes'], change)
            if item is None or revision != item['after'] or digest(self.manifest()) != revision or item['status'] in {'applying', 'rolling-back', 'rolled-back', 'superseded'}:
                return {'recorded': False, 'reason': 'change-revision-not-current'}
            values = (model, effort, category, runtime)
            if any(value is not None and (not isinstance(value, str) or not value or len(value) > 256 or not value.isprintable()) for value in values):
                raise ValueError('Invalid observation context')
            stratum = self.store.fingerprint(json.dumps(values).encode()) if all(values) and 'unknown' not in values else None
            recorded = history.observe(item, self.store.fingerprint(observation.encode()), outcome, source, stratum)
            return {'recorded': recorded, 'status': item['status'], 'effect': 'not-established'}

    def resolve(self, change, decision, *, plan=None):
        if decision not in {'keep', 'rollback'}:
            raise ValueError('Choose keep or rollback after reviewing the change')
        with self.transaction() as state:
            self._expire(state)
            item = history.find(state['changes'], change)
            if item is None or item['status'] in {'rolled-back', 'superseded'}:
                raise ValueError('No current maintenance change has that identity')
            if state['lease'] or self._busy(state, None):
                raise ValueError('Wait until observed tasks and maintenance reviews are idle')
            with project_lock(self.root):
                if (self.root / '.harness/transaction.json').exists():
                    raise ValueError('Recover the pending Harness transaction before resolving maintenance')
                manifest = self.manifest()
                revision = digest(manifest)
                unstarted = item['status'] == 'applying' and revision == item['before']
                restored = item['status'] == 'rolling-back' and revision == item.get('rollbackRevision')
                for managed in manifest['managedFiles']:
                    if harness_state.entry_status(self.root, managed).get('state') != 'unchanged':
                        raise ValueError('Modified managed files preserved; resolve their ownership before maintenance')
                if unstarted or restored:
                    item['status'] = 'rolled-back'
                    state['appliedRevision'] = revision
                    return {'status': 'rolled-back', 'effect': 'not-established', 'writes': 0}
                if revision != item['after']:
                    if decision != 'keep':
                        raise ValueError('Project revision changed; inspect the current config and explicitly keep it to close the prior change')
                    item['status'] = 'superseded'
                    state['appliedRevision'] = revision
                    return {'status': 'superseded', 'effect': 'not-established', 'writes': 0}
                if decision == 'rollback':
                    if plan is None:
                        raise ValueError('Rollback requires a reviewed plan restoring the recorded skill hashes')
                    application = self._limited_application(plan)
                    files = self._change_files(application)
                    if files != {key: list(reversed(pair)) for key, pair in item['files'].items()}:
                        raise ValueError('Rollback may only restore the unchanged managed skills to their recorded prior bytes')
                    import harness_apply
                    item['status'] = 'rolling-back'
                    item['rollbackRevision'] = digest(json.loads(application['manifestText']))
                    self._write(self._location(), state)
                    harness_apply.apply_application(application)
                    state['appliedRevision'] = digest(self.manifest())
                    item['status'] = 'rolled-back'
                else:
                    item['status'] = 'reviewed'
                    item['reviewed'] = len(item['observations'])
            return {'status': item['status'], 'effect': 'not-established'}

    def _change_files(self, application):
        files = {}
        for item in application['report']['actions']:
            name = item['path']
            if item['action'] != 'unchanged' and name != '.harness/manifest.json':
                before = hashlib.sha256(harness_state.resolve_inside(self.root, name).read_bytes()).hexdigest()
                after = hashlib.sha256(application['artifacts'][name].encode('utf-8')).hexdigest()
                files[self.store.fingerprint(name.encode())] = [before, after]
        return files

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
            state['retired'] = {key: at for key, at in state['retired'].items() if at > self.clock()}
            if key in state['retired']:
                return {'recorded': False, 'reason': 'recently-reviewed-with-this-evidence'}
            if key not in state['candidates']:
                if len(state['candidates']) >= MAX_CANDIDATES:
                    retired = next((name for name, item in state['candidates'].items() if item['status'] == 'resolved'), None)
                    if retired is None:
                        return {'recorded': False, 'reason': 'pending-candidate-limit; review existing concerns first'}
                    if len(state['retired']) >= 128:
                        del state['retired'][min(state['retired'], key=state['retired'].get)]
                    state['retired'][retired] = self.clock() + 7 * 86400
                    del state['candidates'][retired]
                state['candidates'][key] = {'reason': reason, 'evidence': evidence_hash, 'observations': [], 'status': 'pending'}
            candidate = state['candidates'][key]
            if candidate['status'] == 'resolved':
                return {'recorded': False, 'reason': 'already-reviewed-with-this-evidence'}
            if ref not in candidate['observations'] and len(candidate['observations']) < 8:
                candidate['observations'].append(ref)
            return {'recorded': True, 'candidate': key, 'eligible': key in self._eligible(state)}

    def _busy(self, state, session):
        return state['trackingIncomplete'] or any(item['children'] or (key != session and item['active']) for key, item in state['sessions'].items())

    def _expire(self, state):
        lease = state['lease']
        if lease and self.clock() > lease['deadline']:
            for key in lease['candidates']:
                state['candidates'][key]['status'] = 'resolved'
            state['metrics']['reviewSeconds'] += lease['deadline'] - lease['started']
            state['metrics']['unmeasuredReviews'] += 1
            cadence.record(state, lease['deadline'], lease['deadline'] - lease['started'], None, 'expired')
            state['lease'] = None

    def _claim(self, state, session):
        self._expire(state)
        now = self.clock()
        state['attempts'] = [t for t in state['attempts'] if now - t < 86400]
        if state['lease'] or self._busy(state, session) or history.summary(state['changes'])['automaticChangesPaused']:
            return None
        candidates = self._eligible(state)
        schedule = cadence.schedule(state, now, [state['candidates'][key] for key in candidates])
        if (not candidates or schedule['budgetBlocked'] or len(state['attempts']) >= schedule['reviewsPerDay']
                or (state['attempts'] and now - state['attempts'][-1] < schedule['intervalSeconds'])):
            return None
        manifest = self.manifest()
        state['lease'] = {'id': uuid.uuid4().hex, 'revision': digest(manifest),
                          'candidates': candidates, 'session': session, 'started': now,
                          'deadline': now + schedule['applicationSeconds']}
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
        application = harness_apply.build_application(self.root, harness_apply.load_plan(harness_state.external_location(plan)))
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
                if history.summary(state['changes'])['automaticChangesPaused']:
                    raise ValueError('Review the unresolved previous maintenance change before applying another')
                if self._busy(state, lease['session']):
                    raise ValueError('Another task or child agent is active; defer maintenance')
                if plan is None:
                    raise ValueError('An independently validated application plan is required')
                import harness_apply
                # Keep the lease checks and application on the same locked revision.
                with project_lock(self.root):
                    if self.clock() > lease['deadline']:
                        raise ValueError('Review deadline passed; preserve the existing harness and finish as deferred')
                    if digest(self.manifest()) != lease['revision']:
                        raise ValueError('Project harness changed during review; review the current revision')
                    application = self._limited_application(plan)
                    if self.clock() > lease['deadline']:
                        raise ValueError('Review deadline passed before apply')
                    if len(state['changes']) >= history.LIMIT:
                        discard = next((i for i, item in enumerate(state['changes']) if item['status'] in {'reviewed', 'rolled-back', 'superseded'}), None)
                        if discard is None:
                            raise ValueError('Review existing maintenance changes before extending the bounded history')
                        state['changes'].pop(discard)
                    state['changes'].append({'id': lease['id'], 'before': lease['revision'],
                        'after': digest(json.loads(application['manifestText'])),
                        'reasons': sorted({state['candidates'][key]['reason'] for key in lease['candidates']}),
                        'evidence': sorted({state['candidates'][key]['evidence'] for key in lease['candidates']}),
                        'files': self._change_files(application), 'status': 'applying', 'observations': {}, 'reviewed': 0})
                    # Record intent before project writes. An interruption pauses future
                    # changes until ordinary transaction recovery and explicit review.
                    self._write(self._location(), state)
                    harness_apply.apply_application(application)
                    state['appliedRevision'] = digest(self.manifest())
                    state['changes'][-1]['status'] = 'observing'
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
            cadence.record(state, self.clock(), self.clock() - lease['started'], tokens, decision)
            state['lease'] = None
            return {'status': decision, 'revision': state['appliedRevision'], 'taskQuality': 'not-measured',
                    'changeId': lease_id if decision == 'apply' else None, 'effect': 'not-established'}

    def hook(self, event):
        kind = event.get('hook_event_name')
        if kind not in {'SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt', 'SessionEnd', 'SubagentStart', 'SubagentStop'}:
            return ''
        with self.transaction() as state:
            if state['mode'] == 'off':
                return ''
            # A missed/ignored review cannot permanently block maintenance or
            # cause repeated model work on the same unresolved batch.
            self._expire(state)
            raw_id = event.get('session_id')
            if not isinstance(raw_id, str) or not raw_id or len(raw_id) > 256:
                return ''
            session_id = self.store.fingerprint(raw_id.encode())
            if kind == 'SessionEnd':
                state['sessions'].pop(session_id, None)
                return ''
            if session_id not in state['sessions']:
                if kind in {'Stop', 'Interrupt', 'SubagentStop'}:
                    return ''
                if len(state['sessions']) >= MAX_SESSIONS:
                    state['trackingIncomplete'] = True
                    return 'Harness maintenance paused: session limit reached. Existing harness remains active.'
                state['sessions'][session_id] = {'active': False, 'children': [], 'seenRevision': None}
            session = state['sessions'][session_id]
            if kind in {'SubagentStart', 'SubagentStop'}:
                child = self.store.fingerprint(str(event.get('agent_id', 'unknown')).encode())
                if kind == 'SubagentStart' and child not in session['children']:
                    if len(session['children']) >= 64:
                        state['trackingIncomplete'] = True
                        return 'Harness maintenance paused: child-agent limit reached. Existing harness remains active.'
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
                current = next((item for item in reversed(state['changes']) if item['after'] == revision
                                and item['status'] in {'observing', 'review-required', 'reviewed'}), None)
                if current:
                    messages.append('Maintenance change ' + current['id'] + ' at revision ' + revision
                        + ' is being observed, not proven beneficial. Record explicitly related outcomes only; '
                        'read the maintenance protocol for observe/operations annotation. Do not run an extra evaluation model.')
            if history.summary(state['changes'])['automaticChangesPaused']:
                if state['notified'] != '0' * 64:
                    messages.append('Harness automatic changes paused: a prior change needs review or recovery. '
                        'Continue project work; use harness-codex maintenance to inspect and resolve it.')
                    state['notified'] = '0' * 64
                return '\n'.join(messages)
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
    root = harness_state.workspace_root(cwd)
    for candidate in (root, *root.parents):
        if (candidate / '.harness/manifest.json').is_file():
            return candidate
    return None


def register_effect_commands(commands):
    observe = commands.add_parser('observe', help='Record an explicitly related outcome; never infer causal benefit.')
    for name in ('change', 'observation', 'revision'):
        observe.add_argument('--' + name, required=True)
    observe.add_argument('--outcome', choices=sorted(history.OUTCOMES), required=True)
    observe.add_argument('--source', choices=sorted(history.SOURCES), required=True)
    for name in ('model', 'effort', 'category', 'runtime'):
        observe.add_argument('--' + name)
    resolve = commands.add_parser('resolve', help='Review a change, or restore a verified previous skill plan.')
    resolve.add_argument('--change', required=True)
    resolve.add_argument('--decision', choices=('keep', 'rollback'), required=True)
    resolve.add_argument('--plan', type=Path)


def effect_command(manager, args, action):
    if action == 'resolve':
        return manager.resolve(args.change, args.decision, plan=args.plan)
    return manager.observe(args.change, args.observation, args.outcome, args.source, args.revision,
                           model=args.model, effort=args.effort, category=args.category, runtime=args.runtime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest='command', required=True)
    register_effect_commands(commands)
    commands.add_parser('status')
    clear = commands.add_parser('clear')
    clear.add_argument('--yes', action='store_true', required=True)
    recover = commands.add_parser('recover-session')
    recover.add_argument('--session-ref', required=True, help='A recorded session ref, or all only after confirming every project session and child stopped.')
    recover.add_argument('--yes', action='store_true', required=True)
    settings = commands.add_parser('configure')
    settings.add_argument('--mode', choices=MODES)
    settings.add_argument('--policy-json', help='Bounded local scheduling overrides; never expands automatic edit scope')
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
            if not isinstance(event, dict):
                raise ValueError('Hook input must be an object')
            if event == {'hook_event_name': 'HarnessProbe'}:
                print(json.dumps({'harnessHookProbe': 1}))
                return 0
            root = find_root(event.get('cwd', ''))
            if root is None:
                return 0
            context = Maintenance(root).hook(event)
            if context:
                if event['hook_event_name'] in {'SessionStart', 'UserPromptSubmit'}:
                    print(json.dumps({'hookSpecificOutput': {'hookEventName': event['hook_event_name'], 'additionalContext': context}}))
                else:
                    print(json.dumps({'systemMessage': context}))
            return 0
        manager = Maintenance(args.root)
        if args.command == 'status':
            result = manager.status()
        elif args.command == 'clear':
            result = manager.clear()
        elif args.command == 'recover-session':
            result = manager.recover_session(args.session_ref)
        elif args.command == 'configure':
            result = manager.configure(args.mode, json.loads(args.policy_json) if args.policy_json else None)
        elif args.command == 'signal':
            result = manager.signal(args.reason, args.evidence, args.observation)
        elif args.command == 'begin':
            result = manager.begin(args.session)
        elif args.command in {'observe', 'resolve'}:
            result = effect_command(manager, args, args.command)
        else:
            result = manager.finish(args.lease, args.decision, plan=args.plan, tokens=args.reported_tokens)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        if args.command == 'hook':
            # Never echo event text, filesystem paths or stored user data.
            category = ('state-or-input' if isinstance(exc, (ValueError, TypeError, KeyError)) else
                        'timeout' if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) else
                        'filesystem' if isinstance(exc, OSError) else 'internal')
            print(json.dumps({'systemMessage': 'Harness maintenance unavailable (' + category + '). Existing project configuration preserved. '
                              'Run harness-codex maintenance --project CURRENT_PATH for details; a moved session may need its current working directory corrected.'}))
            return 0
        print('harness maintenance: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
