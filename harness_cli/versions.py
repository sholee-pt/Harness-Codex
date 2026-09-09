"""Release ordering, including immutable pre-SemVer installation receipts."""
from __future__ import annotations

import re

NUMBER = r'(?:0|[1-9][0-9]*)'
VERSION_RE = re.compile(rf'({NUMBER})\.({NUMBER})(?:\.({NUMBER})(-beta)?)?\Z')
BRANCH_RE = re.compile(rf'codex/v{NUMBER}(?:\.{NUMBER}(?:\.{NUMBER}(?:-beta)?)?)?\Z')


def version_key(value: str) -> tuple[int, int, int, int]:
    match = VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError('Invalid Harness version; expected N.N.N[-beta] or a legacy N.N receipt')
    major, minor = int(match[1]), int(match[2])
    if match[3] is None:
        return 0, major, minor, 0
    return major, minor, int(match[3]), 0 if match[4] else 1


def display_version(value: str) -> str:
    key = version_key(value)
    return '.'.join(map(str, key[:3])) + ('-beta' if key[3] == 0 else '')


def branch_version(value: str) -> str:
    if not isinstance(value, str) or not BRANCH_RE.fullmatch(value):
        raise ValueError('Branch must be codex/vN.N.N[-beta] (legacy version branches remain readable)')
    raw = value[len('codex/v'):]
    return raw if '.' in raw else raw + '.0'
