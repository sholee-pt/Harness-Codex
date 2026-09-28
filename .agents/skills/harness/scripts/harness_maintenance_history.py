"""Bounded, descriptive maintenance history; never stores skill text or learns routing."""
from __future__ import annotations

import re

LIMIT = 16
OBSERVATIONS = 32
STATUSES = {'applying', 'rolling-back', 'observing', 'review-required', 'reviewed', 'rolled-back', 'superseded'}
OUTCOMES = {'unknown', 'verified', 'user-accepted', 'needs-revision', 'failed'}
SOURCES = {'agent-reported', 'user-reported', 'verification'}


def hashed(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def validate(changes):
    if not isinstance(changes, list) or len(changes) > LIMIT:
        raise ValueError('Invalid maintenance change history')
    ids = set()
    for item in changes:
        if (not isinstance(item, dict) or set(item) - {'rollbackRevision'} != {'id', 'before', 'after', 'reasons', 'evidence', 'files', 'status', 'observations', 'reviewed'}
                or 'rollbackRevision' in item and not hashed(item['rollbackRevision'])
                or item.get('status') == 'rolling-back' and 'rollbackRevision' not in item
                or not isinstance(item['id'], str) or re.fullmatch(r'[0-9a-f]{32}', item['id']) is None or item['id'] in ids
                or not hashed(item['before']) or not hashed(item['after']) or item['status'] not in STATUSES
                or not isinstance(item['reasons'], list) or not 1 <= len(item['reasons']) <= 5
                or any(x not in {'scope-changed', 'user-request', 'workflow-gap', 'routing-mismatch', 'verification-gap'} for x in item['reasons'])
                or not isinstance(item['evidence'], list) or len(item['evidence']) > 32 or any(not hashed(x) for x in item['evidence'])
                or not isinstance(item['files'], dict) or not 1 <= len(item['files']) <= 2
                or any(not hashed(key) or not isinstance(pair, list) or len(pair) != 2 or any(not hashed(x) for x in pair)
                       for key, pair in item['files'].items())
                or not isinstance(item['observations'], dict) or len(item['observations']) > OBSERVATIONS
                or type(item['reviewed']) is not int or not 0 <= item['reviewed'] <= len(item['observations'])):
            raise ValueError('Invalid maintenance change record')
        ids.add(item['id'])
        sequences = set()
        for key, observation in item['observations'].items():
            if (not hashed(key) or not isinstance(observation, dict) or set(observation) != {'outcome', 'source', 'stratum', 'sequence'}
                    or observation['outcome'] not in OUTCOMES or observation['source'] not in SOURCES
                    or type(observation['sequence']) is not int or not 0 <= observation['sequence'] < len(item['observations'])
                    or observation['sequence'] in sequences
                    or observation['stratum'] is not None and not hashed(observation['stratum'])):
                raise ValueError('Invalid maintenance effect observation')
            sequences.add(observation['sequence'])


def find(changes, identity):
    return next((item for item in changes if item['id'] == identity), None)


def observe(item, reference, outcome, source, stratum):
    if outcome not in OUTCOMES or source not in SOURCES:
        raise ValueError('Invalid maintenance effect outcome/source')
    if outcome == 'verified' and source != 'verification' or outcome == 'user-accepted' and source != 'user-reported':
        raise ValueError('A success label requires the corresponding external evidence')
    previous = item['observations'].get(reference)
    if previous and (previous['outcome'], previous['source'], previous['stratum']) == (outcome, source, stratum):
        return False
    if previous is None and len(item['observations']) >= OBSERVATIONS:
        raise ValueError('Maintenance observation limit reached; review this change')
    item['observations'][reference] = {'outcome': outcome, 'source': source, 'stratum': stratum,
                                     'sequence': previous['sequence'] if previous else len(item['observations'])}
    recent = [value for value in item['observations'].values() if value['sequence'] >= item['reviewed']]
    adverse = [value for value in recent if value['source'] != 'agent-reported'
               and value['outcome'] in {'needs-revision', 'failed'} and value['stratum'] is not None]
    if stratum is not None and sum(value['stratum'] == stratum for value in adverse) >= 2:
        item['status'] = 'review-required'
    return True


def summary(changes):
    return {'automaticChangesPaused': any(item['status'] in {'applying', 'rolling-back', 'review-required'} for item in changes),
            'changes': [{'id': item['id'], 'beforeRevision': item['before'], 'afterRevision': item['after'],
                         'status': item['status'], 'reasons': item['reasons'], 'observations': len(item['observations']),
                         'effect': 'not-established'} for item in changes],
            'effectEvaluation': 'descriptive-only', 'rollbackRequiresPlan': True}
