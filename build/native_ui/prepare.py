"""Apply the bounded Harness extension to an exact, otherwise clean Codex source."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def prepare(root):
    metadata = json.loads((HERE / 'upstream.json').read_text())
    git = ['git', '-c', 'safe.directory=' + root.as_posix(), '-c', 'core.longpaths=true', '-C', str(root)]
    revision = subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()
    if revision != metadata['commit'] or subprocess.check_output([*git, 'status', '--porcelain'], text=True).strip():
        raise ValueError('Native UI builds require the pinned clean upstream source')
    edits = {
        'codex-rs/tui/src/chatwidget.rs': [
            ('mod model_popups;', 'mod model_popups;\nmod harness_routing;'),
            ('    model_popup_request_id: Option<uuid::Uuid>,',
             '    model_popup_request_id: Option<uuid::Uuid>,\n    harness_routing: Arc<std::sync::Mutex<harness_routing::Routing>>,')],
        'codex-rs/tui/src/chatwidget/constructor.rs': [
            ('            model_popup_request_id: None,',
             '            model_popup_request_id: None,\n            harness_routing: harness_routing::new_state(),')],
        'codex-rs/tui/src/chatwidget/model_popup_state.rs': [
            ('    pub(super) fn show_model_selection_view(&mut self, mut params: SelectionViewParams) {',
             '    pub(super) fn show_model_selection_view(&mut self, mut params: SelectionViewParams) {\n        self.add_harness_auto_choice(&mut params.items);')],
        'codex-rs/tui/src/chatwidget/model_popups.rs': [
            ('        let thread_id = self.thread_id();\n        vec![Box::new(move |tx| {',
             '        let thread_id = self.thread_id();\n        let harness_state = Arc::clone(&self.harness_routing);\n        vec![Box::new(move |tx| {\n            if let Ok(mut state) = harness_state.lock() { state.active = false; }')],
        'codex-rs/tui/src/chatwidget/input_submission.rs': [
            ('        let effective_mode = self.effective_collaboration_mode();',
             '        self.apply_harness_routing(&text, !local_images.is_empty() || !remote_image_urls.is_empty());\n        let effective_mode = self.effective_collaboration_mode();')],
        'codex-rs/tui/src/chatwidget/tests.rs': [
            ('//! Exercises `ChatWidget` event handling and rendering invariants.',
             '//! Exercises `ChatWidget` event handling and rendering invariants.')],
    }
    for name, replacements in edits.items():
        path = root / name
        content = path.read_text(encoding='utf-8')
        for old, new in replacements:
            if content.count(old) != 1:
                raise ValueError(f'Upstream integration point changed: {name}')
            content = content.replace(old, new)
        path.write_text(content, encoding='utf-8', newline='\n')
    for name in ('harness_routing.rs',):
        (root / 'codex-rs/tui/src/chatwidget' / name).write_bytes((HERE / name).read_bytes())
    tests = root / 'codex-rs/tui/src/chatwidget/tests.rs'
    tests.write_text(tests.read_text(encoding='utf-8') + '\nmod harness_routing_tests;\n', encoding='utf-8', newline='\n')
    (root / 'codex-rs/tui/src/chatwidget/tests/harness_routing_tests.rs').write_bytes((HERE / 'harness_routing_tests.rs').read_bytes())
    print(json.dumps({'upstream': revision, 'modified': list(edits),
        'extensionSha256': hashlib.sha256((HERE / 'harness_routing.rs').read_bytes()).hexdigest(),
        'rendererModified': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    prepare(parser.parse_args().root.resolve())
