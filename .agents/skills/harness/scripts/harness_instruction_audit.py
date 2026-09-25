#!/usr/bin/env python3
"""Bounded static instruction inventory; no model calls, writes or token estimates."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tomllib

import harness_frontmatter
import harness_change_discipline
import harness_state
import harness_teamplay

MAX_FILES = 256
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024


def summarize(contents, skipped=None):
    surfaces, paragraphs = [], {}
    for path, content in contents.items():
        kind = 'root-instructions'
        body, description = content, None
        try:
            if path.endswith('/SKILL.md'):
                kind = 'on-demand-skill'
                description = harness_frontmatter.parse(content)['description']
                body = content.split('---', 2)[2]
            elif path.endswith('.toml'):
                kind = 'on-demand-agent'
                body = tomllib.loads(content).get('developer_instructions', '')
                if not isinstance(body, str):
                    raise ValueError('Agent instructions must be text')
        except (ValueError, KeyError, IndexError):
            kind = 'unparsed-instructions'
            body = content
        surfaces.append({'path': path, 'kind': kind, 'bytes': len(content.encode('utf-8')),
                         'characters': len(content), 'lines': len(content.splitlines()),
                         'descriptionCharacters': len(description) if description else 0})
        # Required canonical repetition is deliberate and cannot be optimized
        # away independently of its artifact contract.
        body = re.sub(r'<!-- harness:[^>]+:begin -->.*?<!-- harness:[^>]+:end -->', '', body, flags=re.S)
        body = body.replace(harness_teamplay.AGENT_BLOCK, '')
        body = body.replace(harness_change_discipline.WRITER_BLOCK, '')
        for paragraph in re.split(r'\n\s*\n', body):
            normalized = ' '.join(paragraph.split())
            if len(normalized) < 160 or normalized.startswith('```'):
                continue
            key = hashlib.sha256(normalized.encode()).hexdigest()
            entry = paragraphs.setdefault(key, {'characters': len(normalized), 'paths': []})
            entry['paths'].append(path)
    duplicates = [{'fingerprint': key, **entry} for key, entry in paragraphs.items() if len(entry['paths']) > 1]
    return {'scope': 'project instruction files only; no user/global/plugin inventory',
            'measurement': 'static bytes and characters; actual loading, tokens and savings are not measured',
            'files': len(surfaces), 'bytes': sum(item['bytes'] for item in surfaces),
            'characters': sum(item['characters'] for item in surfaces),
            'discoveryDescriptionCharacters': sum(item['descriptionCharacters'] for item in surfaces),
            'surfaces': sorted(surfaces, key=lambda item: (-item['bytes'], item['path'])),
            'duplicateParagraphs': duplicates, 'skipped': skipped or [],
            'guidance': 'Review repeated prose in its loading context; preserve required contracts. No automatic deletion.'}


def inspect(root: Path, manifest):
    entries = manifest.get('managedFiles', []) if isinstance(manifest, dict) else []
    names = {'AGENTS.md', 'AGENTS.override.md', '.agents/skills/harness/SKILL.md'}
    if isinstance(entries, list):
        names.update(item['path'] for item in entries if isinstance(item, dict) and isinstance(item.get('path'), str)
                     and (item['path'].endswith('/SKILL.md') or item['path'].endswith('.toml')))
    contents, skipped, total = {}, [], 0
    for index, name in enumerate(sorted(names)):
        if index >= MAX_FILES:
            skipped.append({'path': name, 'reason': 'inventory-file-budget'})
            continue
        try:
            path = harness_state.resolve_inside(root, name)
            if not path.exists():
                continue
            limit = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total)
            if path.stat().st_size > limit:
                raise ValueError('instruction inventory byte budget exceeded')
            with path.open('rb') as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError('instruction changed beyond inventory byte budget')
            total += len(data)
            contents[name] = data.decode('utf-8')
        except (OSError, ValueError) as error:
            skipped.append({'path': name, 'reason': str(error)})
    return summarize(contents, skipped)
