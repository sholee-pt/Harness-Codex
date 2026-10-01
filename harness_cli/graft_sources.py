"""Explicit external code snapshots attached to one project's retrieval state."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from .paths import checked_path, external_location, is_link, project_root

MAX_FILES = 200
MAX_BYTES = 16 * 1024 * 1024
SUFFIXES = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.rs', '.go', '.java', '.c', '.h',
            '.cpp', '.hpp', '.cs', '.rb', '.php', '.sh', '.swift', '.kt', '.scala', '.r', '.sql'}
SKIP = {'.git', '.harness', '.context', '.agents', '.codex', 'node_modules', '__pycache__', '.venv', 'venv'}


def valid_sources(value):
    if (not isinstance(value, dict) or len(value) > 16
            or not all(isinstance(k, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,39}', k)
                       and isinstance(v, str) and Path(v).is_absolute() and '\0' not in v for k, v in value.items())):
        raise ValueError('Invalid external retrieval sources; existing settings were preserved.')
    return value


def select(root, value):
    selected = Path(value).expanduser()
    path = project_root(selected) if selected.is_dir() else external_location(selected)
    if not path.exists() or not (path.is_dir() or path.is_file()):
        raise ValueError('Select an existing external code file or directory.')
    if path.is_relative_to(root) or root.is_relative_to(path):
        raise ValueError('Select external code only, not the project itself or an ancestor containing it.')
    if any(part.casefold() in SKIP or part.casefold().startswith('.env') for part in path.parts):
        raise ValueError('Metadata, credentials and environment directories are not external code sources.')
    if path.is_file() and path.suffix.lower() not in SUFFIXES:
        raise ValueError('External retrieval accepts supported source-code files only.')
    return path


def collect(root, sources):
    """Bound reads; never follow nested links, special files or broad unselected roots."""
    files, total, visited, seen = {}, 0, 0, set()
    for name, location in valid_sources(sources).items():
        source = select(root, location)
        pending = [source]
        while pending:
            path = pending.pop()
            visited += 1
            if visited > 10000:
                raise ValueError('External source scan exceeds 10000 entries; select a narrower directory.')
            if path != source and (path.name.startswith('.') or path.name in SKIP):
                continue
            if is_link(path):
                raise ValueError('External source contains a nested link; select its intended target explicitly: ' + str(path))
            checked_path(path)
            info = path.stat()
            if stat.S_ISDIR(info.st_mode):
                with os.scandir(path) as entries:
                    for entry in entries:
                        pending.append(Path(entry.path))
                        if len(pending) + visited > 10000:
                            raise ValueError('External source scan is too large; select a narrower directory.')
                continue
            if not stat.S_ISREG(info.st_mode) or path.suffix.lower() not in SUFFIXES:
                continue
            if path in seen:
                continue
            seen.add(path)
            if info.st_size > 1024 * 1024 or len(files) >= MAX_FILES or total + info.st_size > MAX_BYTES:
                raise ValueError('External code exceeds 200 files, 1 MiB/file or 16 MiB total; select narrower sources.')
            with path.open('rb') as stream:
                data = stream.read(1024 * 1024 + 1)
            after = path.stat()
            if (info.st_size, info.st_mtime_ns, info.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or len(data) != info.st_size:
                raise ValueError('External source changed while reading; repeat retrieval after editing finishes.')
            if b'\0' in data:
                raise ValueError('Binary content is not an external code source.')
            data.decode('utf-8')
            relative = path.relative_to(source).as_posix() if source.is_dir() else path.name
            key = name + '/' + relative
            files[key] = (data, str(path))
            total += len(data)
    return files


def snapshot(folder, files):
    """Reuse unchanged snapshots; remove only bytes proved to belong to this adapter."""
    from .project_installer import Entry, DirectoryState, directory_state, snapshot as tree_snapshot, replace_folder
    tree = checked_path(folder / 'source')
    receipt_name = '.harness-sources.json'
    old_root = directory_state(tree)
    old = tree_snapshot(tree)
    previous = {}
    if old_root is not None:
        receipt = old.get(receipt_name)
        if receipt is None or receipt.data is None or len(receipt.data) > 256 * 1024:
            raise ValueError('Unowned external source cache was preserved.')
        value = json.loads(receipt.data)
        if not isinstance(value, dict) or value.get('owner') != 'harness-graft-sources-v1' or not isinstance(value.get('files'), dict):
            raise ValueError('Invalid external source cache was preserved.')
        previous = value['files']
    for name, digest in previous.items():
        if not isinstance(name, str) or '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Invalid external cache entry.')
        entry = old.get(name)
        if entry is None or entry.data is None or hashlib.sha256(entry.data).hexdigest() != digest:
            raise ValueError('Modified external cache was preserved; use ordinary source search.')
    for name, entry in old.items():
        if entry.data is not None and name != receipt_name and name not in previous:
            raise ValueError('Unowned external cache content was preserved.')
    current = {name: hashlib.sha256(data).hexdigest() for name, (data, _) in files.items()}
    if old_root is not None and previous == current:
        return tree
    stamp = time.time_ns()
    desired = {}
    for name, (data, _) in files.items():
        desired[name] = old[name] if previous.get(name) == current[name] else Entry(data, 0o600, stamp)
        for parent in Path(name).parents:
            if parent != Path('.'):
                desired[parent.as_posix()] = old.get(parent.as_posix(), Entry(None, 0o700, stamp))
    data = (json.dumps({'owner': 'harness-graft-sources-v1', 'files': current}, sort_keys=True) + '\n').encode()
    desired[receipt_name] = Entry(data, 0o600, stamp)
    replace_folder(tree, old, desired, old_root, old_root or DirectoryState(0o700, stamp, stamp, 0, 0))
    return tree


def query(args, source_root, root, folder, settings, result, *, timeout):
    from .graft import _invoke
    started = time.monotonic()
    files = collect(root, settings.get('externalSources', {}))
    if not files:
        return result
    tree = snapshot(folder / 'external', files)
    timeout -= time.monotonic() - started
    if timeout <= 0:
        raise TimeoutError('External snapshot preparation exhausted the query deadline.')
    external = _invoke(source_root, tree, folder / 'external-graph', settings, 'query', timeout=timeout,
                       question=args.question, limit=max(1, args.limit // 2), max_chars=max(512, args.max_chars // 2), advice=False)
    text = external['text']
    # Report the selected originals, never imply the disposable snapshot is editable.
    pointers = {key: original for name, (_, original) in files.items() for key in (str(tree / name), name)}
    text = re.sub('|'.join(re.escape(key) for key in sorted(pointers, key=len, reverse=True)),
                  lambda match: pointers[match.group()], text)
    heading = '\n\nExternal code (separate structural index; verify original files; cross-root edges are not inferred):\n'
    remaining = max(0, args.max_chars - len(heading))
    share = remaining // 2
    combined = result['text'][:remaining - share] + heading + text[:share]
    result.update(text=combined, projectHits=result.get('hits', 0), hits=result.get('hits', 0) + external.get('hits', 0), externalHits=external.get('hits', 0),
                  externalRefreshed=external.get('refreshed', False), externalFiles=len(files),
                  truncated=result.get('truncated', False) or external.get('truncated', False)
                  or len(result['text']) > remaining - share or len(text) > share)
    return result
