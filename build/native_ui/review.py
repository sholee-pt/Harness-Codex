"""Require byte-identical upstream render/input/theme/permission source."""
import argparse
import json
from pathlib import Path
import subprocess

ALLOWED = {
    'codex-rs/tui/src/main.rs', 'codex-rs/tui/src/chatwidget/replay.rs',
    'codex-rs/tui/src/chatwidget/session_flow.rs',
    'codex-rs/Cargo.lock', 'codex-rs/tui/src/chatwidget.rs',
    'codex-rs/tui/src/chatwidget/constructor.rs',
    'codex-rs/tui/src/chatwidget/input_submission.rs',
    'codex-rs/tui/src/chatwidget/model_popups.rs',
    'codex-rs/tui/src/chatwidget/model_popup_state.rs',
    'codex-rs/tui/src/chatwidget/tests.rs',
}


def review(root):
    # just 1.51 removes empty lines in the upstream justfile. Retain that
    # unrelated file byte-for-byte, only after proving all nonblank lines match.
    original = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:justfile'])
    current = (root / 'justfile').read_bytes()
    if current != original:
        lines = lambda value: [line for line in value.decode('utf-8').splitlines() if line.strip()]
        if lines(current) != lines(original):
            raise ValueError('Unexpected non-formatting change to the upstream justfile')
        (root / 'justfile').write_bytes(original)
    changed = set(subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only'], text=True).splitlines())
    unexpected = sorted(changed - ALLOWED)
    print(json.dumps({'changedTrackedFiles': sorted(changed), 'unexpectedChanges': unexpected,
                      'sourceChangesRestrictedToReviewedHooks': not unexpected}, indent=2))
    if unexpected:
        raise ValueError('Native UI patch extends beyond its reviewed integration points')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    review(parser.parse_args().root)
