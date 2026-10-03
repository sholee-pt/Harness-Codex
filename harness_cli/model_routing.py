"""Bounded, in-memory next-turn routing; never runs a model or changes files.

Profile preferences are explicit policy, not benchmark results or pricing claims.
Only visible catalog entries and their advertised reasoning options are selected.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re

TIERS = ('fast', 'balanced', 'deep')
PROFILE_CANDIDATES = dict.fromkeys(TIERS, ())
MAX_PROMPT = 32 * 1024


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and value.isprintable() and not any(c.isspace() for c in value)


@dataclass(frozen=True)
class Context:
    """Caller-owned task state. No prompt, transcript, path, or agent identifier."""
    tier: str = 'balanced'
    model: str | None = None
    effort: str | None = None
    failures: int = 0
    active_task: bool = False
    lighter_requests: int = 0


@dataclass(frozen=True)
class Decision:
    tier: str
    model: str | None
    effort: str | None
    reason: str
    selection: str
    changed: bool

    def report(self):
        return asdict(self)

    def turn_overrides(self):
        """Only inference settings; no permission, tool, Git, or cwd overrides."""
        return {key: value for key, value in (('model', self.model), ('effort', self.effort)) if value is not None}


def validate_context(context):
    if (context.tier not in TIERS or type(context.failures) is not int
            or not 0 <= context.failures <= 100 or type(context.active_task) is not bool
            or type(context.lighter_requests) is not int or not 0 <= context.lighter_requests <= 1
            or context.effort is not None and not identifier(context.effort)
            or context.model is not None and not identifier(context.model)):
        raise ValueError('Invalid routing task context.')


def catalog_entries(catalog):
    if not isinstance(catalog, list) or len(catalog) > 1000:
        raise ValueError('Routing requires a bounded model catalog list.')
    result = {}
    for entry in catalog:
        if not isinstance(entry, dict) or not identifier(entry.get('model')):
            raise ValueError('Invalid model catalog entry.')
        if entry.get('hidden'):
            continue
        name = entry['model']
        if name in result:
            raise ValueError('Duplicate visible model catalog entry.')
        options = entry.get('supportedReasoningEfforts', [])
        if (not isinstance(options, list) or len(options) > 64
                or any(not isinstance(item, dict) or not identifier(item.get('reasoningEffort')) for item in options)
                or len({item['reasoningEffort'] for item in options}) != len(options)):
            raise ValueError('Invalid supported reasoning options.')
        result[name] = entry
    return result


def available_model(name, catalog, entries):
    """Follow advertised successors only when the original is no longer visible."""
    seen = set()
    source = {item['model']: item for item in catalog}
    while name not in entries and name in source and name not in seen:
        seen.add(name)
        name = source[name].get('upgrade')
        if not identifier(name):
            return None
    return entries.get(name)


def classify(prompt, context, *, new_task=False):
    validate_context(context)
    if not isinstance(prompt, str) or not prompt.strip() or '\0' in prompt or len(prompt.encode('utf-8')) > MAX_PROMPT:
        raise ValueError('Provide a nonempty routing prompt of at most 32 KiB without NUL characters.')
    text = re.sub(r'\s+', ' ', prompt.casefold()).strip()
    tier, reason = _request_tier(text)
    if context.active_task and not (new_task or starts_new_task(text)):
        if context.failures >= 2:
            return 'deep', 'repeated-failure'
        if tier == 'deep':
            return tier, reason
        continuation = re.search(r'^(continue\b|yes\b|no\b|do it\b|try again\b|same\b|that\b|it\b|계속|이어서|앞서|아까|그것|그대로|그럼|그러면|다시|한\s*번\s*더|네[.!\s]*$|응[.!\s]*$)', text)
        if continuation or reason == 'uncertain-scope':
            return context.tier, 'continue-task'
        if TIERS.index(tier) < TIERS.index(context.tier) and context.lighter_requests == 0:
            return context.tier, 'lighter-request-pending'
    return tier, reason


def starts_new_task(prompt):
    return bool(re.search(r'^\s*(new task\b|next task\b|separate (task|request)\b|unrelated (task|request)\b|새(?:로운)?\s*작업|다음\s*작업|다른\s*작업|별개로|별도의\s*요청)', prompt.casefold()))


def _request_tier(text):
    # A named security topic is not itself a security change. Restrict this
    # exception to one explicit documentation-only edit, never mixed requests.
    narrow_document = re.search(r'\breadme\b|\bdocumentation\b|문서', text)
    typo = re.search(r'\b(typo|spelling|punctuation)\b|오탈자|오타|맞춤법', text)
    mixed = re.search(r'\b(and|also|then|implement|refactor|investigate|review|audit|test|code|function|disable|enable|delete|remove|bypass|migrate|deploy|modify)\b|[;,]|그리고|추가로|구현|리팩|조사|검토|검증|코드|함수|삭제|제거|우회|비활성|활성화|배포|변경', text)
    if narrow_document and typo and not mixed and len(text) <= 300:
        return 'fast', 'narrow-text-edit'
    if _complex(text):
        return 'deep', 'complex-change'
    # Clear scope may change tiers; ambiguous follow-ups retain their selection.
    edit = re.search(r'\b(typo|spelling|punctuation)\b|오탈자|오타|맞춤법', text)
    documentation = re.search(r'\breadme\b|문서|documentation', text)
    local_edit = re.search(r'\b(sentence|word|heading|wording)\b|문장|단어|제목|문구', text)
    code_work = re.search(r'\b(code|function|bug|logic|algorithm|refactor|implement)\b|코드|함수|버그|로직|알고리즘|리팩|구현', text)
    if (edit or documentation and local_edit) and not code_work and len(text) <= 700:
        return 'fast', 'narrow-text-edit'
    if code_work and re.search(r'\b(function|module|endpoint|pipeline|test|feature|api)\b|함수|모듈|기능|파이프라인|테스트', text):
        return 'balanced', 'scoped-code-request'
    return 'balanced', 'uncertain-scope'


def _complex(text):
    review = re.search(r'\b(review|audit|inspect)\b|검토|감사|점검|전수', text)
    broad = re.search(r'\b(whole|entire|all)\b.{0,40}\b(repository|repositories|repo|codebase|code|files|modules)\b'
        r'|\b(repository|repo|codebase)[- ]wide\b|(?:전체|전반).{0,20}(저장소|레포지토리|리포지토리|코드|모듈|파일)'
        r'|(저장소|레포지토리|리포지토리|코드베이스).{0,20}(전체|전반)|모든\s*(파일|코드|모듈)', text)
    if review and broad:
        return True
    return bool(re.search(
        r'\b(architecture|concurrency|race condition|deadlock|data leakage|security|authentication|authorization|migration)\b'
        r'|아키텍처|동시성|교착|데이터\s*누수|보안|인증|권한|마이그레이션|여러\s*(모듈|저장소)|반복.{0,12}실패'
        r'|\b(cross[- ]module|multi[- ]repository|distributed)\b', text))


def choose(prompt, catalog, *, context=Context(), new_task=False, profiles=None, fixed=None):
    """Plan one future turn. A fixed (model, effort) selection disables routing.

    Keep ambiguous follow-ups stable. Clear scope can escalate immediately;
    lighter requests require confirmation across turns or a new-task boundary. Missing
    model metadata retains native settings instead of guessing a valid model.
    """
    tier, reason = classify(prompt, context, new_task=new_task)
    entries = catalog_entries(catalog)
    preferences = dict(PROFILE_CANDIDATES)
    if profiles is not None:
        if not isinstance(profiles, dict) or set(profiles) - set(TIERS):
            raise ValueError('Routing profiles accept only fast, balanced, and deep.')
        for key, value in profiles.items():
            if not isinstance(value, list) or len(value) > 20 or any(not isinstance(name, str) or not name.strip() for name in value):
                raise ValueError('Each routing profile must be a bounded list of model IDs.')
            preferences[key] = tuple(value)
    if fixed is not None:
        if not isinstance(fixed, tuple) or len(fixed) != 2:
            raise ValueError('A fixed selection requires a model and reasoning effort.')
        model, effort = fixed
        entry = entries.get(model)
        if entry is None or effort not in _efforts(entry):
            raise ValueError('The fixed model/reasoning combination is not supported by the visible catalog.')
        return Decision(context.tier, model, effort, 'manual-fixed', 'manual', (model, effort) != (context.model, context.effort))
    if reason in {'continue-task', 'lighter-request-pending'} and context.model in entries and context.effort in _efforts(entries[context.model]):
        return Decision(tier, context.model, context.effort, reason, 'retained', False)
    default = next((entry for entry in entries.values() if entry.get('isDefault') is True), None)
    selected = next((entry for name in preferences[tier] if (entry := available_model(name, catalog, entries))), None)
    selection = 'profile'
    if selected is None:
        selected = available_model(context.model, catalog, entries) or default
        selection = 'available-default'
    if selected is None:
        return Decision(tier, None, None, reason, 'native-unresolved', False)
    effort = _effort(selected, tier)
    if effort is None:
        # Do not switch models while accidentally inheriting incompatible effort.
        return Decision(tier, None, None, reason, 'native-unresolved', False)
    model = selected['model']
    return Decision(tier, model, effort, reason, selection, (model, effort) != (context.model, context.effort))


def _efforts(entry):
    return [item['reasoningEffort'] for item in entry.get('supportedReasoningEfforts', [])]


def _effort(entry, tier):
    options = _efforts(entry)
    desired = {'fast': 'low', 'balanced': 'medium', 'deep': 'high'}[tier]
    if desired in options:
        return desired
    default = entry.get('defaultReasoningEffort')
    return default if default in options else None


def advance(context, decision, *, succeeded, task_complete=False):
    """Explicit execution feedback, never inferred from reassuring model prose."""
    validate_context(context)
    if type(succeeded) is not bool or type(task_complete) is not bool:
        raise ValueError('Execution feedback must use explicit boolean outcomes.')
    return Context(decision.tier, decision.model or context.model, decision.effort or context.effort,
                   0 if succeeded else min(context.failures + 1, 100), not task_complete,
                   int(not task_complete and decision.reason == 'lighter-request-pending'))
