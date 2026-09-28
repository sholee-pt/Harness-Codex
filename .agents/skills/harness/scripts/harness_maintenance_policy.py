"""Local adaptive cadence inside explicit limits; no model calls or benefit claims."""
import math

MAX_REVIEWS = 24
MAX_SECONDS = 900
DEFAULTS = {'schedule': 'adaptive', 'reviewsPerDay': 2, 'minIntervalSeconds': 300,
            'maxIntervalSeconds': 86400, 'reviewSeconds': 180, 'reportedTokensPerDay': None}


def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate(policy, recent):
    if not isinstance(policy, dict) or set(policy) != set(DEFAULTS) or policy['schedule'] not in {'adaptive', 'fixed'}:
        raise ValueError('Invalid maintenance scheduling policy')
    for name, low, high in (('reviewsPerDay', 1, MAX_REVIEWS), ('minIntervalSeconds', 60, 86400),
                            ('maxIntervalSeconds', 60, 604800), ('reviewSeconds', 30, MAX_SECONDS)):
        if type(policy[name]) is not int or not low <= policy[name] <= high:
            raise ValueError('Invalid maintenance policy limit: ' + name)
    if policy['maxIntervalSeconds'] < policy['minIntervalSeconds']:
        raise ValueError('Maximum maintenance interval must not be below minimum')
    budget = policy['reportedTokensPerDay']
    if budget is not None and (type(budget) is not int or not 1 <= budget <= 10000000):
        raise ValueError('Invalid reported maintenance token budget')
    if not isinstance(recent, list) or len(recent) > MAX_REVIEWS:
        raise ValueError('Invalid recent maintenance reviews')
    for item in recent:
        if (not isinstance(item, dict) or set(item) != {'at', 'duration', 'tokens', 'decision'}
                or not valid_number(item['at']) or not valid_number(item['duration'])
                or item['tokens'] is not None and (type(item['tokens']) is not int or item['tokens'] < 0)
                or item['decision'] not in {'unchanged', 'proposed', 'deferred', 'apply', 'expired'}):
            raise ValueError('Invalid maintenance cost observation')


def schedule(state, now, candidates):
    policy, recent = state['policy'], state['recentReviews']
    validate(policy, recent)
    quiet = 0
    for item in reversed(recent):
        if item['decision'] != 'unchanged':
            break
        quiet += 1
    explicit = any(item['reason'] in {'scope-changed', 'user-request'} for item in candidates)
    repetitions = max((len(item['observations']) for item in candidates), default=0)
    interval, seconds = 3600, policy['reviewSeconds']
    if policy['schedule'] == 'adaptive':
        urgency = max(1, repetitions / 2)
        interval = 3600 * (1 if explicit else 2 ** min(quiet, 6)) / urgency
        completed = [item['duration'] for item in recent if item['decision'] in {'apply', 'unchanged', 'proposed'}]
        if completed:
            seconds = min(seconds, max(30, math.ceil(sum(completed[-4:]) / len(completed[-4:]) * 1.5 * math.sqrt(max(1, len(candidates))))))
    interval = max(policy['minIntervalSeconds'], min(policy['maxIntervalSeconds'], math.ceil(interval)))
    today = [item for item in recent if now - item['at'] < 86400]
    budget = policy['reportedTokensPerDay']
    unmeasured = sum(item['tokens'] is None for item in today)
    reported = sum(item['tokens'] or 0 for item in today)
    blocked = budget is not None and (unmeasured > 0 or reported >= budget)
    return {'schedule': policy['schedule'], 'intervalSeconds': interval, 'applicationSeconds': seconds,
            'reportedTokensLastDay': reported, 'unmeasuredReviewsLastDay': unmeasured,
            'budgetBlocked': blocked, 'reviewsPerDay': policy['reviewsPerDay'],
            'hardTokenEnforcement': False}


def record(state, now, duration, tokens, decision):
    state['recentReviews'].append({'at': now, 'duration': max(0, duration), 'tokens': tokens, 'decision': decision})
    del state['recentReviews'][:-MAX_REVIEWS]
