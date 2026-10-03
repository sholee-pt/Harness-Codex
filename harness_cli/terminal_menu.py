"""Small keyboard menu with a plain-input fallback and no runtime dependencies."""
from __future__ import annotations

from contextlib import contextmanager
import os
import select
import shutil
import sys
import unicodedata

from .presentation import clean


def escape_key(fd):
    if not select.select([fd], [], [], .08)[0]:
        return '\x1b'
    sequence = os.read(fd, 1).decode('ascii', errors='replace')
    if sequence not in ('[', 'O'):
        return ''
    for _ in range(31):
        if not select.select([fd], [], [], .08)[0]:
            return ''
        char = os.read(fd, 1).decode('ascii', errors='replace')
        sequence += char
        if '@' <= char <= '~':
            break
    return {'[A': 'up', '[B': 'down', '[D': 'left', 'OA': 'up', 'OB': 'down', 'OD': 'left'}.get(sequence, '')


@contextmanager
def keyboard():
    if not sys.stdin.isatty():
        raise OSError('No interactive input')
    fd = sys.stdin.fileno()
    if os.name == 'nt':
        import msvcrt
        def read():
            char = msvcrt.getwch()
            if char in ('\x00', '\xe0'):
                return {'H': 'up', 'P': 'down', 'K': 'left'}.get(msvcrt.getwch(), '')
            return char
        yield read
    else:
        import termios
        import tty
        saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            def read():
                char = os.read(fd, 1).decode('ascii', errors='replace')
                if not char:
                    raise KeyboardInterrupt('Terminal input closed')
                if char == '\x1b':
                    return escape_key(fd)
                return char
            yield read
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def next_selection(index, key, count):
    if key == '\x03':
        raise KeyboardInterrupt
    if key in ('up', 'k'):
        return (index - 1) % count, False
    if key in ('down', 'j'):
        return (index + 1) % count, False
    return index, key in ('\r', '\n')


def fit_row(text, width):
    result, used = [], 0
    for char in clean(text).replace('\n', ' ').replace('\t', ' '):
        size = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1
        if used + size > width:
            break
        result.append(char)
        used += size
    return ''.join(result)


def clipped_row(text, width):
    text = clean(text).replace('\n', ' ').replace('\t', ' ')
    fitted = fit_row(text, width)
    return fitted if fitted == text else fit_row(text, max(0, width - 1)) + '…'


def wrapped_rows(text, width):
    if width < 2:
        raise ValueError('Wrapped text needs at least two terminal columns')
    rows = []
    for line in clean(text).replace('\t', ' ').split('\n'):
        current, used = [], 0
        for char in line:
            size = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1
            if used + size > width:
                rows.append(''.join(current))
                current, used = [], 0
            current.append(char)
            used += size
        rows.append(''.join(current))
    return rows


def help_rows(width, back):
    rows = []
    for item in ['Up/Down: select', 'Enter: accept', 'Ctrl+C: cancel', *(['Left: back'] if back else [])]:
        if rows and fit_row(rows[-1] + '   ' + item, width) == rows[-1] + '   ' + item:
            rows[-1] += '   ' + item
        else:
            rows.append(item)
    return rows


def plain_choice(progress, title, labels, summary, initial, back_index):
    progress.line('')
    for line in summary:
        progress.line(line)
    progress.line('\n' + title + '\n')
    for index, label in enumerate(labels):
        progress.line(f'  {index}. {label}')
    progress.line('')
    while True:
        try:
            answer = progress.ask(f'Select a number [{initial}]' + ('; b: back' if back_index >= 0 else '') + ': ').strip()
        except EOFError:
            raise KeyboardInterrupt('Terminal input closed') from None
        if back_index >= 0 and answer.casefold() == 'b':
            return -1
        if not answer:
            return -1 if initial == back_index else initial
        if answer.isascii() and answer.isdecimal() and len(answer) < 5 and int(answer) < len(labels):
            return -1 if int(answer) == back_index else int(answer)
        progress.line(f'Enter a number from 0 to {len(labels) - 1}.')


def choose(progress, title, labels, *, back=False, summary=(), initial=0):
    if not labels:
        raise ValueError('No choices are available')
    labels = list(labels)
    back_index = len(labels) if back else -1
    if back:
        labels.append('Back to the previous step')
    initial = initial if 0 <= initial < len(labels) else 0
    stream = progress.stream
    try:
        interactive = sys.stdin.isatty() and stream.isatty() and os.environ.get('TERM') != 'dumb' and shutil.get_terminal_size((80, 24)).lines >= 4
        if interactive:
            sys.stdin.fileno()
            stream.fileno()
    except (AttributeError, OSError, ValueError):
        interactive = False
    if not interactive:
        return plain_choice(progress, title, labels, summary, initial, back_index)
    index, drawn, detail_page = initial, 0, None
    color = 'NO_COLOR' not in os.environ
    with progress.lock:
        progress.paused = True
        progress.clear()
    try:
        with keyboard() as read:
            while True:
                size = shutil.get_terminal_size((80, 24))
                height = max(1, size.lines - 1)
                if drawn:
                    stream.write(f'\x1b[{min(drawn, height)}A')
                    for _ in range(min(drawn, height)):
                        stream.write('\r\x1b[2K\n')
                    stream.write(f'\x1b[{min(drawn, height)}A')
                    drawn = 0
                width = max(1, size.columns - 1)
                controls = help_rows(width, back)
                usable = width >= 27 and height >= len(controls) + 3
                if not usable:
                    break
                if detail_page is not None:
                    content = [*wrapped_rows(labels[index], width), '',
                               *wrapped_rows(title, width), *[row for line in summary for row in wrapped_rows(line, width)]]
                    capacity = height - len(controls) - 1
                    pages = (len(content) + capacity - 1) // capacity
                    detail_page = min(detail_page, pages - 1)
                    rows = [clipped_row(f'Tab: next/list  {detail_page + 1}/{pages}', width),
                            *content[detail_page * capacity:(detail_page + 1) * capacity], *controls]
                else:
                    if height >= len(summary) + 15:
                        rows = ['', *[clipped_row(line, width) for line in summary], '', clipped_row(title, width), '', *controls, '']
                    else:
                        rows = [clipped_row(title, width), *controls]
                    if color:
                        rows = ['\x1b[1;36m' + row + '\x1b[0m' if row == clipped_row(title, width) else row for row in rows]
                    rows.append(f'{index + 1}/{len(labels)}  Tab: details')
                    count = min(8, max(1, height - len(rows)))
                    start = max(0, min(index - count // 2, len(labels) - count))
                    for choice in range(start, min(len(labels), start + count)):
                        text = clipped_row(('> ' if choice == index else '  ') + labels[choice], width)
                        rows.append(('\x1b[1;36m' + text + '\x1b[0m') if color and choice == index else text)
                for row in rows:
                    stream.write('\r\x1b[2K' + row + '\n')
                stream.flush()
                drawn = len(rows)
                key = read()
                if back and key in ('b', 'B', 'left', '\x08', '\x7f'):
                    return -1
                if key == '\t':
                    detail_page = 0 if detail_page is None else detail_page + 1 if detail_page + 1 < pages else None
                    continue
                previous = index
                index, accepted = next_selection(index, key, len(labels))
                if index != previous and detail_page is not None:
                    detail_page = 0
                if accepted:
                    return -1 if index == back_index else index
    finally:
        with progress.lock:
            if drawn:
                drawn = min(drawn, max(1, shutil.get_terminal_size((80, 24)).lines - 1))
                stream.write(f'\x1b[{drawn}A')
                for _ in range(drawn):
                    stream.write('\r\x1b[2K\n')
                stream.write(f'\x1b[{drawn}A\r')
                stream.flush()
            progress.paused = False
    progress.line('Small terminal: use the numbered choices below. Ctrl+C cancels.')
    return plain_choice(progress, title, labels, summary, index, back_index)
