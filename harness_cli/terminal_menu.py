"""Small keyboard menu with a plain-input fallback and no runtime dependencies."""
from __future__ import annotations

from contextlib import contextmanager
import os
import select
import shutil
import sys

from .presentation import clean


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
                return {'H': 'up', 'P': 'down'}.get(msvcrt.getwch(), '')
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
                    sequence = ''
                    for _ in range(2):
                        if not select.select([fd], [], [], .08)[0]:
                            break
                        sequence += os.read(fd, 1).decode('ascii', errors='replace')
                    return {'[A': 'up', '[B': 'down'}.get(sequence, '\x1b')
                return char
            yield read
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def next_selection(index, key, count):
    if key in ('\x03', '\x04', '\x1b'):
        raise KeyboardInterrupt
    if key in ('up', 'k'):
        return (index - 1) % count, False
    if key in ('down', 'j'):
        return (index + 1) % count, False
    return index, key in ('\r', '\n')


def choose(progress, title, labels):
    if not labels:
        raise ValueError('No choices are available')
    stream = progress.stream
    try:
        interactive = sys.stdin.isatty() and stream.isatty() and os.environ.get('TERM') != 'dumb'
        if interactive:
            sys.stdin.fileno()
            stream.fileno()
    except (AttributeError, OSError, ValueError):
        interactive = False
    if not interactive:
        progress.line('\n' + title)
        for index, label in enumerate(labels):
            progress.line(f'  {index}. {label}')
        while True:
            answer = progress.ask('Select a number [0]: ').strip()
            if not answer:
                return 0
            if answer.isascii() and answer.isdecimal() and len(answer) < 5 and int(answer) < len(labels):
                return int(answer)
            progress.line(f'Enter a number from 0 to {len(labels) - 1}.')
    index, drawn = 0, 0
    color = 'NO_COLOR' not in os.environ
    with progress.lock:
        progress.paused = True
        progress.clear()
    try:
        with keyboard() as read:
            while True:
                if drawn:
                    stream.write(f'\x1b[{drawn}A')
                width = max(20, shutil.get_terminal_size((80, 24)).columns - 1)
                start = max(0, min(index - 4, len(labels) - 8))
                rows = [clean(title), 'Up/Down: select   Enter: accept   Esc: cancel']
                for choice in range(start, min(len(labels), start + 8)):
                    label = clean(labels[choice]).replace('\n', ' ').replace('\t', ' ')
                    text = ('> ' if choice == index else '  ') + label
                    text = text[:width]
                    rows.append(('\x1b[1;36m' + text + '\x1b[0m') if color and choice == index else text)
                for row in rows:
                    stream.write('\r\x1b[2K' + row + '\n')
                stream.flush()
                drawn = len(rows)
                index, accepted = next_selection(index, read(), len(labels))
                if accepted:
                    return index
    finally:
        with progress.lock:
            progress.paused = False
