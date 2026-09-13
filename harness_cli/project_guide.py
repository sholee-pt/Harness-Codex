"""One deterministic, ownership-checked project guide; no dated copies."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile

from .paths import checked_path

PATH = '.harness/GUIDE.md'
HEADER = re.compile(rb'<!-- harness-codex-guide:v1 sha256:([0-9a-f]{64}) -->\n')


def owned(root):
    path = checked_path(Path(root) / PATH)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        return False
    data = path.read_bytes()
    match = HEADER.match(data)
    return bool(match and hashlib.sha256(data[match.end():]).hexdigest().encode() == match[1])


def sync(root, *, version, revision, stale=False):
    path = checked_path(Path(root) / PATH)
    if os.path.lexists(path) and not owned(root):
        return 'preserved-user-content'
    before = path.read_bytes() if path.is_file() else None
    body = (f'# Project harness guide\n\n'
            f'- Tool version: {version}\n- Project harness revision: {revision}\n'
            f'- Source evidence: {"review current source" if stale else "matches recorded references"}\n\n'
            '## Project work\n\n'
            '- Run `codex` in this project; use `codex resume` or `codex resume --last` for existing conversations. Native root instructions activate `.agents/skills/project-harness/SKILL.md`.\n'
            '- Reuse the current agents and skills. Do not regenerate them merely to resume a conversation.\n'
            '- Verify current source before relying on recorded evidence; deleted or changed references require review, not invented replacements.\n'
            '- Preserve native Codex model and permission settings. Changing the conversation model does not require regenerating this harness.\n'
            '- Editing files does not authorize commit or push. Honor only explicit authorization within its scope.\n\n'
            '## Maintenance\n\n'
            '- Use `harness-codex config` to review project responsibilities and update the existing harness.\n'
            '- Ask Codex to re-read current project instructions when an existing conversation needs a configuration refresh; no automatic user turn is added.\n'
            '- Use `harness-codex doctor --json` for full static diagnostics. Static validity does not prove live agent loading or task quality.\n'
            '- Maintain this guide at `.harness/GUIDE.md` only. Do not create dated/versioned copies. The CLI refreshes it after init/config; native conversations do not rewrite it.\n').encode('utf-8')
    data = b'<!-- harness-codex-guide:v1 sha256:' + hashlib.sha256(body).hexdigest().encode() + b' -->\n' + body
    if data == before:
        return 'unchanged'
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.guide-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        # Preserve concurrent user edits; the guide is not required to launch work.
        current = path.read_bytes() if path.is_file() else None
        if current != before:
            return 'preserved-concurrent-change'
        from .project import harness_revision
        if harness_revision(root) != revision:
            return 'preserved-concurrent-change'
        checked_path(path)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return 'updated'
