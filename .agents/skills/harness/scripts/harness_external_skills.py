"""Offline external skill discovery and explicit, create-only local import."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

import harness_frontmatter
import harness_state


RECEIPT = '.harness-external.json'
MAX_FILES = 1024
MAX_BYTES = 64 * 1024 * 1024
MAX_HEADER_BYTES = 128 * 1024
RESERVED = {'harness', 'project-harness'}


def _plain(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('External skill paths must not contain links or reparse points: ' + str(path))
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError('External skills require ordinary files and directories: ' + str(path))


def _path(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    for item in reversed((path, *path.parents)):
        if os.path.lexists(item):
            _plain(item)
    return path


def _project(path: Path) -> Path:
    if any(part.rstrip(' .').casefold() in {'.git', '.hg', '.svn'} for part in path.parts):
        raise ValueError('Project must be an existing directory outside repository metadata')
    path = harness_state.workspace_root(path)
    if not path.is_dir() or any(part.rstrip(' .').casefold() in {'.git', '.hg', '.svn'} for part in path.parts):
        raise ValueError('Project must be an existing directory outside repository metadata')
    return path


def metadata(path: Path) -> dict:
    """Project name/description only; never rewrite or claim full YAML validation."""
    _plain(path)
    prefix = bytearray()
    with path.open('rb') as stream:
        while len(prefix) <= MAX_HEADER_BYTES:
            line = stream.readline(MAX_HEADER_BYTES + 1 - len(prefix))
            if not line:
                break
            closes = bool(prefix) and line.rstrip(b'\r\n') == b'---'
            prefix.extend(line)
            if closes:
                break
    raw_lines = prefix.replace(b'\r\n', b'\n').split(b'\n')
    if b'---' not in raw_lines[1:]:
        raise ValueError('External skill needs a bounded YAML header in SKILL.md')
    lines = b'\n'.join(raw_lines[:raw_lines.index(b'---', 1) + 1]).decode('utf-8-sig').split('\n')
    if not lines or lines[0] != '---' or '---' not in lines[1:]:
        raise ValueError('External skill needs a bounded YAML header in SKILL.md')
    header = lines[1:lines.index('---', 1)]
    selected = []
    for line in header:
        if not line or line.startswith((' ', '\t', '#')):
            continue
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_-]*):(?: +(.*))?', line)
        if match is None:
            raise ValueError('External header needs unquoted top-level keys; merge keys and YAML directives are unsupported')
        if match[1] in {'name', 'description'}:
            selected.append(line)
    result = harness_frontmatter.parse('---\n' + '\n'.join(selected) + '\n---\n')
    return {**result, 'metadataValidation': 'name-description-only', 'runtimeLoading': 'not-tested'}


def _walk_error(error: OSError) -> None:
    raise error


def _files(root: Path) -> dict[str, dict]:
    result = {}
    total = 0
    visited = 0
    for folder, directories, files in os.walk(root, followlinks=False, onerror=_walk_error):
        for name in directories + files:
            visited += 1
            if visited > MAX_FILES * 2:
                raise ValueError('External skill has too many directory entries')
            path = Path(folder) / name
            _plain(path)
            relative = path.relative_to(root).as_posix()
            if any(part in {'.git', '.hg', '.svn'} for part in path.relative_to(root).parts):
                raise ValueError('Import a skill directory, not repository metadata')
            if name in directories:
                continue
            if relative == RECEIPT:
                continue
            size = path.stat().st_size
            total += size
            if len(result) >= MAX_FILES or total > MAX_BYTES:
                raise ValueError('External skill import exceeds 1024 files or 64 MiB; select a smaller skill bundle')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            result[relative] = {'sha256': digest, 'mode': stat.S_IMODE(path.stat().st_mode)}
    return result


def _publish(stage: Path, destination: Path) -> None:
    # Unlike POSIX rename, RENAME_NOREPLACE also preserves a concurrent empty directory.
    if sys.platform.startswith('linux'):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise ValueError('Atomic create-only import requires Linux renameat2 support')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(destination))
    elif os.name == 'nt':
        stage.rename(destination)
    else:
        raise ValueError('External skill import supports Linux and retained Windows source only')


def inventory(root: Path) -> dict:
    root = _project(root)
    directory = _path(root / '.agents/skills')
    entries = []
    truncated = False
    if directory.is_dir():
        with os.scandir(directory) as candidates:
            for index, item in enumerate(candidates):
                if index >= MAX_FILES:
                    truncated = True
                    break
                if item.name.startswith('.') or not item.is_dir(follow_symlinks=False):
                    continue
                try:
                    folder = _path(Path(item.path))
                    path = folder / 'SKILL.md'
                    if not path.is_file():
                        continue
                    entry = metadata(path)
                    if entry['name'] != folder.name:
                        raise ValueError('Skill name must match its directory')
                    entries.append({**entry, 'path': path.relative_to(root).as_posix(),
                                    'importReceiptPresent': os.path.lexists(folder / RECEIPT)})
                except (OSError, UnicodeError, ValueError) as exc:
                    entries.append({'path': '.agents/skills/' + item.name, 'error': str(exc)})
    return {'skills': sorted(entries, key=lambda entry: entry['path']), 'truncated': truncated,
            'scope': 'project-local; metadata only; receipt and content hashes not checked'}


def add(root: Path, source: Path, *, upstream: str | None = None, revision: str | None = None,
        license_file: Path | None = None, dry_run: bool = False) -> dict:
    root, source = _project(root), _path(harness_state.external_location(source))
    if not source.is_dir():
        raise ValueError('Project and source skill directories must already exist')
    entry = metadata(source / 'SKILL.md')
    name = entry['name']
    if name != source.name or name in RESERVED:
        raise ValueError('Use the original skill directory name; Harness native names are reserved')
    if bool(upstream) != bool(revision):
        raise ValueError('Supply both --upstream and --revision, or neither for a local skill')
    if upstream and (not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', upstream)
                     or not re.fullmatch(r'[0-9a-f]{40}', revision or '')):
        raise ValueError('Provenance requires a GitHub repository URL and a full lowercase commit SHA')
    destination = _path(root / '.agents/skills' / name)
    if os.path.lexists(destination):
        raise ValueError('Existing skill preserved; review external updates separately: ' + str(destination))
    if destination.parent.is_dir() and any(item.name.casefold() == name.casefold() for item in destination.parent.iterdir()):
        raise ValueError('A case-equivalent skill directory already exists; preserve it')
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Source and destination skill trees must not overlap')
    if os.path.lexists(source / RECEIPT):
        raise ValueError('Import the original upstream bundle, not an already imported copy')
    files = _files(source)
    license_path = _path(harness_state.external_location(license_file)) if license_file else None
    if license_path and (not license_path.is_file() or license_path.stat().st_size > MAX_HEADER_BYTES):
        raise ValueError('License file must be an ordinary text file of at most 128 KiB')
    license_name = 'UPSTREAM-LICENSE.txt'
    if license_path and license_name in files:
        raise ValueError('Bundle already contains UPSTREAM-LICENSE.txt; preserve it without --license-file')
    report = {**entry, 'path': destination.relative_to(root).as_posix(), 'status': 'preview' if dry_run else 'added',
              'files': len(files) + bool(license_path), 'ownership': 'external', 'upstream': upstream,
              'revision': revision, 'provenance': 'user-declared; not network-verified' if upstream else 'local'}
    if dry_run:
        return report
    directory = _path(root / '.agents')
    directory.mkdir(exist_ok=True)
    _path(destination.parent).mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.harness-import-', dir=directory) as temporary:
        stage = Path(temporary) / name
        stage.mkdir()
        for relative, record in files.items():
            original = _path(source / relative)
            with original.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Source changed during import; no skill was installed')
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(record['mode'])
        if license_path:
            (stage / license_name).write_bytes(license_path.read_bytes())
        copied = _files(stage)
        if _files(source) != files:
            raise ValueError('Source changed during import; no skill was installed')
        (stage / RECEIPT).write_text(json.dumps({'schemaVersion': 1, 'skill': name, 'upstream': upstream,
                                              'revision': revision, 'provenance': report['provenance'], 'files': copied},
                                             indent=2) + '\n', encoding='utf-8')
        _path(destination)
        if os.path.lexists(destination):
            raise ValueError('Destination appeared during import; existing skill preserved')
        # rename publishes the whole bundle. No source scripts or hooks are executed.
        _publish(stage, destination)
    return report


def verify(root: Path, name: str) -> dict:
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
        raise ValueError('Select a kebab-case skill name')
    folder = _path(_project(root) / '.agents/skills' / name)
    receipt_path = _path(folder / RECEIPT)
    if receipt_path.stat().st_size > 1024 * 1024:
        raise ValueError('External skill receipt is too large')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if not isinstance(receipt, dict) or type(receipt.get('schemaVersion')) is not int or receipt['schemaVersion'] != 1 or receipt.get('skill') != name:
        raise ValueError('Unsupported external skill receipt')
    recorded = receipt.get('files')
    if not isinstance(recorded, dict) or not recorded or len(recorded) > MAX_FILES:
        raise ValueError('Invalid external skill file records')
    for path, record in recorded.items():
        if (not isinstance(record, dict) or not isinstance(record.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', record['sha256']) or type(record.get('mode')) is not int):
            raise ValueError('Invalid external skill file record')
    current = _files(folder)
    changed = sorted(path for path in recorded.keys() | current.keys() if recorded.get(path) != current.get(path))
    return {'skill': name, 'status': 'changed' if changed else 'unchanged', 'changedFiles': changed,
            'verification': 'local receipt comparison; not upstream authenticity or runtime validation'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inventory(args.root), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
