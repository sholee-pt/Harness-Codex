"""Owned native trust fragments and reversible hook-file changes."""
from __future__ import annotations

import copy
import json
import os
import re
import stat
import tomllib

from .paths import checked_path


def receipt(content):
    value = json.loads(content)
    if (not isinstance(value, dict) or set(value) not in ({'owner', 'command'}, {'owner', 'command', 'trust'})
            or value['owner'] != 'harness-maintenance-v1' or not isinstance(value['command'], str)):
        raise ValueError('Maintenance hook ownership receipt is invalid')
    records = value.get('trust', {})
    if not isinstance(records, dict) or len(records) > 128:
        raise ValueError('Invalid hook trust ownership records')
    for key, entry in records.items():
        if (not isinstance(key, str) or not key or not key.isprintable() or len(key) > 4096 or not isinstance(entry, dict)
                or set(entry) != {'before', 'after', 'expected'} or not isinstance(entry['expected'], dict)
                or any(entry[field] is not None and not isinstance(entry[field], str) for field in ('before', 'after'))):
            raise ValueError('Invalid hook trust ownership entry')
    return value


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode('utf-8')


def configuration(content):
    text = (content or b'').decode('utf-8')
    value = tomllib.loads(text)
    hooks = value.get('hooks', {})
    states = hooks.get('state', {}) if isinstance(hooks, dict) else None
    if not isinstance(states, dict):
        raise ValueError('Native hook state is not a table')
    return text, value, states


def fragment(text, key):
    # Locate only independently declared tables. A full semantic comparison
    # below guards against header-looking lines inside TOML multiline strings.
    headers = list(re.finditer(r'(?m)^[ \t]*\[.*\][ \t]*(?:#[^\r\n]*)?\r?$', text))
    for index, match in enumerate(headers):
        try:
            value = tomllib.loads(match.group() + '\n')
        except ValueError:
            continue
        if value != {'hooks': {'state': {key: {}}}}:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        end = match.start() + len(text[match.start():end].rstrip())
        if text[end:end + 2] == '\r\n':
            end += 2
        elif text[end:end + 1] == '\n':
            end += 1
        try:
            value = tomllib.loads(text)
            expected = copy.deepcopy(value)
            del expected['hooks']['state'][key]
            observed = tomllib.loads(text[:match.start()] + text[end:])
            if normalized(observed) != normalized(expected):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        return match.start(), end, text[match.start():end]
    return None


def normalized(value):
    result = copy.deepcopy(value)
    if result.get('hooks', {}).get('state') == {}:
        del result['hooks']['state']
    if result.get('hooks') == {}:
        del result['hooks']
    return result


def begin_trust(saved, content, edits):
    text, _, states = configuration(content)
    result = copy.deepcopy(saved)
    records = result.setdefault('trust', {})
    for key, fields in edits.items():
        section = fragment(text, key)
        current = states.get(key)
        if current is not None and (not isinstance(current, dict) or section is None):
            raise ValueError('Existing hook trust layout requires manual review')
        before = section[2] if section else None
        previous = records.get(key)
        if previous and previous['after'] is not None and before == previous['after']:
            before = previous['before']
        records[key] = {'before': before, 'after': None, 'expected': {**(current or {}), **fields}}
    receipt(encoded(result))
    return result


def finish_trust(saved, content, keys):
    text, _, states = configuration(content)
    result = copy.deepcopy(saved)
    for key in keys:
        entry = result['trust'][key]
        section = fragment(text, key)
        if section is None or states.get(key) != entry['expected']:
            raise ValueError('Native trust write could not be bound to its ownership record')
        entry['after'] = section[2]
    return result


def restore_trust(content, records):
    text, value, states = configuration(content)
    warnings = []
    for key, entry in records.items():
        section = fragment(text, key)
        if key not in states:
            continue  # A user deletion must not resurrect an earlier value.
        if section is None or entry['after'] is None or section[2] != entry['after'] or states[key] != entry['expected']:
            warnings.append('Modified or unconfirmed Harness hook trust preserved: ' + key)
            continue
        replacement = entry['before'] or ''
        candidate = text[:section[0]] + replacement + text[section[1]:]
        expected = copy.deepcopy(value)
        target = expected['hooks']['state']
        if replacement:
            prior = configuration(replacement.encode())[2]
            if set(prior) != {key}:
                raise ValueError('Invalid prior hook trust fragment')
            target[key] = prior[key]
        else:
            del target[key]
        parsed = tomllib.loads(candidate)
        # Empty implicit parent tables disappear when their last child is gone.
        if normalized(parsed) != normalized(expected):
            raise ValueError('Hook trust cleanup would change unrelated configuration')
        text, value, states = configuration(candidate.encode())
    return text.encode('utf-8') if content is not None else None, warnings


def replace_file(path, before, after):
    from .maintenance import _hook_snapshot
    from .shell import _replace_profile
    path = checked_path(path)
    if _hook_snapshot(path) != before:
        raise ValueError('Hook settings changed concurrently; user edits preserved')
    if before == after:
        return
    if after is None:
        path.unlink()
    else:
        _replace_profile(path, before or b'', after)


def apply_changes(changes, written):
    from .maintenance import _hook_snapshot
    if any(_hook_snapshot(path) != before for path, before, _ in changes):
        raise ValueError('Hook settings changed after the uninstall preview')
    for path, before, after in changes:
        if before != after:
            metadata = file_metadata(path)
            replace_file(path, before, after)
            written.append((path, before, after, metadata, file_metadata(path)))


def file_metadata(path):
    checked_path(path)
    if not path.exists():
        return None
    info = path.stat()
    return stat.S_IMODE(info.st_mode), info.st_mtime_ns


def rollback_changes(written, backup):
    failures = []
    for index, (path, before, after, metadata, observed) in enumerate(reversed(written)):
        try:
            if file_metadata(path) != observed:
                raise ValueError('Hook file metadata changed during rollback')
            replace_file(path, after, before)
            if metadata is not None:
                path.chmod(metadata[0])
                os.utime(path, ns=(path.stat().st_atime_ns, metadata[1]))
        except (OSError, ValueError):
            # Keep recovery evidence outside user configuration if a concurrent
            # edit prevents restoration; never overwrite that edit.
            record = backup / ('hook-recovery-' + str(index) + '.json')
            record.write_bytes(encoded({'path': str(path), 'before': before.decode('utf-8') if before is not None else None,
                                        'after': after.decode('utf-8') if after is not None else None}))
            failures.append(str(record))
    return failures
