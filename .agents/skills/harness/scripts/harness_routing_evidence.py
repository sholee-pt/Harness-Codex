"""Opt-in local routing observations, bounded confidence and conservative advice."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
import re
from statistics import NormalDist, mean, stdev
import time

from harness_maintenance import checked
import harness_eval_store as storage
from harness_eval_lock import FileLock
import harness_state

MAX_BYTES = 512 * 1024
MAX_SAMPLES = 256
DEFAULTS = {'qualityFloor': 0.8, 'confidence': 0.95, 'minimumGain': 0.15, 'historyDays': 30}
OUTCOMES = {'unknown', 'verified', 'user-accepted', 'failed', 'needs-revision'}


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and value.isprintable() and not any(c.isspace() for c in value)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def defaults():
    return {'schema': 1, 'enabled': False, 'policy': dict(DEFAULTS), 'samples': {}}


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != set(DEFAULTS):
        raise ValueError('Invalid adaptive routing policy')
    for name, low, high in (('qualityFloor', 0.5, 0.99), ('confidence', 0.8, 0.999), ('minimumGain', 0.05, 0.9), ('historyDays', 1, 365)):
        if not number(policy[name]) or not low <= policy[name] <= high:
            raise ValueError('Invalid adaptive routing limit: ' + name)


def bounds(values, confidence):
    if len(values) < 2:
        return 0, float('inf')
    average = mean(values)
    # Conservative small-sample uncertainty, without pretending samples are a
    # randomized causal trial. Identical observations still retain a margin.
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    radius = z * max(stdev(values), average * 0.1) / math.sqrt(len(values))
    return max(0, average - radius), average + radius


def quality_lower(successes, total, confidence):
    if not total:
        return 0
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    proportion = successes / total
    return (proportion + z*z/(2*total) - z*math.sqrt(proportion*(1-proportion)/total + z*z/(4*total*total))) / (1 + z*z/total)


class RoutingEvidence:
    def __init__(self, root, state_root=None, *, clock=time.time):
        self.root = checked(root)
        self.store = storage.EvaluationStore(state_root=checked(state_root or storage.default_state_root()))
        storage.ensure_state_outside_repositories(self.store.root, [self.root])
        self.clock = clock
        self._secret = None

    def fingerprint(self, value, create=False):
        if self._secret is None:
            path = checked(self.store.secret_path)
            self._secret = self.store._load_or_create_secret() if create and not path.exists() else path.read_bytes()
            if len(self._secret) != 32:
                self._secret = None
                raise ValueError('Invalid adaptive evidence secret; existing state preserved')
        return hmac.digest(self._secret, value, 'sha256').hex()

    def location(self, create=False):
        checked(self.store.root)
        if not create and not self.store.secret_path.exists():
            return None
        key = self.fingerprint(os.path.normcase(str(self.root)).encode(), create=create)
        return checked(self.store.root / 'routing' / key / 'state.json')

    def read(self):
        path = self.location()
        if path is None or not path.exists():
            return defaults()
        with path.open('rb') as stream:
            content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('Adaptive routing evidence exceeds its limit')
        value = json.loads(content)
        if (not isinstance(value, dict) or set(value) != set(defaults()) or value['schema'] != 1
                or type(value['enabled']) is not bool or not isinstance(value['samples'], dict) or len(value['samples']) > MAX_SAMPLES):
            raise ValueError('Invalid adaptive routing state; preserve it for inspection')
        validate_policy(value['policy'])
        for key, item in value['samples'].items():
            if (not isinstance(key, str) or not re.fullmatch(r'work-item:[0-9a-f]{32}', key)
                    or not isinstance(item, dict) or set(item) != {'context', 'pair', 'at', 'milliseconds', 'tokens', 'outcome', 'source', 'cause'}
                    or any(not isinstance(item[name], str) or not re.fullmatch(r'[0-9a-f]{64}', item[name]) for name in ('context', 'pair'))
                    or not number(item['at']) or not number(item['milliseconds'])
                    or item['tokens'] is not None and (type(item['tokens']) is not int or not 0 <= item['tokens'] <= 10**12)
                    or item['outcome'] not in OUTCOMES or item['source'] not in {'runtime', 'verification', 'user-reported'}
                    or item['cause'] not in {'unknown', 'inference', 'environment'}):
                raise ValueError('Invalid routing observation')
            if (item['outcome'] == 'verified' and item['source'] != 'verification'
                    or item['outcome'] == 'user-accepted' and item['source'] != 'user-reported'):
                raise ValueError('Invalid routing outcome provenance')
        return value

    @contextmanager
    def transaction(self, create=False):
        path = self.location(create)
        if path is None or not path.exists() and not create:
            yield defaults()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            path.parent.chmod(0o700)
        with FileLock(checked(path.with_suffix('.lock')), timeout=0.2):
            state = self.read()
            before = digest(state)
            yield state
            if digest(state) != before or not path.exists():
                content = json.dumps(state, sort_keys=True) + '\n'
                if len(content.encode()) > MAX_BYTES:
                    raise ValueError('Adaptive routing state exceeds its limit')
                harness_state.atomic_write_text(path, content, mode=0o600)

    def configure(self, enabled=None, policy=None):
        from harness_maintenance import Maintenance
        Maintenance(self.root, self.store.root).manifest()
        with self.transaction(create=True) as state:
            if enabled is not None:
                if type(enabled) is not bool:
                    raise ValueError('Adaptive routing enablement must be boolean')
                state['enabled'] = enabled
            if policy is not None:
                candidate = {**state['policy'], **policy}
                validate_policy(candidate)
                state['policy'] = candidate
        return self.status()

    def status(self):
        state = self.read()
        return {'enabled': state['enabled'], 'policy': state['policy'], 'samples': len(state['samples']),
                'workItems': [{'reference': key, 'outcome': item['outcome'], 'tokens': item['tokens'], 'milliseconds': item['milliseconds']}
                              for key, item in sorted(state['samples'].items(), key=lambda pair: pair[1]['at'])[-12:]],
                'benefit': 'not-established', 'modelCalls': 0, 'rawContentStored': False}

    def clear(self):
        with self.transaction() as state:
            state.clear()
            state.update(defaults())
        return self.status()

    def context(self, *, runtime, catalog, revision, category, tier):
        return self.fingerprint(json.dumps([runtime, catalog, revision, category, tier], sort_keys=True).encode())

    def pair(self, model, effort):
        if not identifier(model) or not identifier(effort):
            raise ValueError('Routing observation requires the actual model and reasoning')
        return self.fingerprint(json.dumps([model, effort]).encode())

    def record(self, session, turn, *, context, model, effort, milliseconds, tokens):
        if (not identifier(session) or not identifier(turn) or not number(milliseconds)
                or not isinstance(context, str) or not re.fullmatch(r'[0-9a-f]{64}', context)):
            raise ValueError('Invalid routing observation identity or timing')
        if tokens is not None and (type(tokens) is not int or not 0 <= tokens <= 10**12):
            raise ValueError('Invalid routing token observation')
        with self.transaction() as state:
            if not state['enabled']:
                return {'recorded': False, 'reason': 'disabled'}
            repository_id = self.store.register_workspace(self.root)
            reference = self.store.pseudonym(repository_id, 'work-item', session + '\0' + turn)
            sample = {'context': context, 'pair': self.pair(model, effort), 'at': self.clock(),
                      'milliseconds': milliseconds, 'tokens': tokens, 'outcome': 'unknown', 'source': 'runtime', 'cause': 'unknown'}
            previous = state['samples'].get(reference)
            if previous:
                if previous['context'] != context or previous['pair'] != sample['pair']:
                    return {'recorded': False, 'reason': 'mixed-inference-turn'}
                return {'recorded': False, 'reference': reference, 'reason': 'already-recorded'}
            while len(state['samples']) >= MAX_SAMPLES:
                del state['samples'][min(state['samples'], key=lambda key: state['samples'][key]['at'])]
            state['samples'][reference] = sample
            return {'recorded': True, 'reference': reference}

    def feedback(self, reference, outcome, source, cause='unknown'):
        if (outcome not in OUTCOMES or source not in {'verification', 'user-reported'}
                or cause not in {'unknown', 'inference', 'environment'}
                or outcome == 'verified' and source != 'verification'
                or outcome == 'user-accepted' and source != 'user-reported'):
            raise ValueError('Routing feedback requires explicit verification or user evidence')
        with self.transaction() as state:
            if not state['enabled'] or reference not in state['samples']:
                return {'recorded': False, 'reason': 'disabled-or-unobserved-work'}
            sample = state['samples'][reference]
            update = {'outcome': outcome, 'source': source, 'cause': cause}
            changed = any(sample[name] != value for name, value in update.items())
            sample.update(update)
            return {'recorded': changed, 'reference': reference}

    def recommend(self, context, baseline, candidates, *, active_task=False, state=None):
        state = self.read() if state is None else state
        if not state['enabled']:
            return None
        policy, groups = state['policy'], {}
        cutoff = self.clock() - policy['historyDays'] * 86400
        for sample in state['samples'].values():
            if sample['context'] != context or not cutoff <= sample['at'] <= self.clock() or sample['source'] == 'runtime' or sample['cause'] == 'environment':
                continue
            success = sample['outcome'] in {'verified', 'user-accepted'}
            failure = sample['outcome'] in {'failed', 'needs-revision'} and sample['cause'] == 'inference'
            if success or failure:
                groups.setdefault(sample['pair'], []).append(sample)
        base = groups.get(self.pair(*baseline), [])
        if not base:
            return None
        gain = min(0.95, policy['minimumGain'] * (2 if active_task else 1))
        base_failures = sum(row['outcome'] in {'failed', 'needs-revision'} for row in base)
        recovery = 1 - quality_lower(base_failures, len(base), policy['confidence']) < policy['qualityFloor']
        best, best_ratio = None, float('inf') if recovery else 1.0
        for pair in candidates:
            rows = groups.get(self.pair(*pair), [])
            successes = sum(row['outcome'] in {'verified', 'user-accepted'} for row in rows)
            if pair == baseline or quality_lower(successes, len(rows), policy['confidence']) < policy['qualityFloor']:
                continue
            ratios, improved, regressed = [], False, False
            for metric in ('tokens', 'milliseconds'):
                left = [row[metric] for row in base if row[metric] is not None]
                right = [row[metric] for row in rows if row[metric] is not None]
                if len(left) < 2 or len(right) < 2 or mean(left) <= 0:
                    continue
                lower, _ = bounds(left, policy['confidence'])
                _, upper = bounds(right, policy['confidence'])
                improved |= upper < lower * (1 - gain)
                regressed |= mean(right) > mean(left) * (1 + gain / 2)
                ratios.append(mean(right) / mean(left))
            if ratios and (recovery or improved and not regressed) and mean(ratios) < best_ratio:
                best, best_ratio = {'pair': pair, 'reason': 'observed-quality-recovery' if recovery else 'observed-efficiency'}, mean(ratios)
        return best
