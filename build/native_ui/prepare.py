"""Apply the bounded Harness extension to an exact, otherwise clean Codex source."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib

HERE = Path(__file__).resolve().parent


def normalize_workspace_versions(root):
    """The upstream tag bumps workspace version but retains 0.0.0 path locks.

    Normalize only local workspace package versions; keep every external source,
    version and checksum untouched, then let Cargo enforce --locked as usual.
    """
    cargo = root / 'codex-rs'
    workspace = tomllib.loads((cargo / 'Cargo.toml').read_text(encoding='utf-8'))['workspace']
    version = workspace['package']['version']
    names = set()
    for member in workspace['members']:
        package = tomllib.loads((cargo / member / 'Cargo.toml').read_text(encoding='utf-8')).get('package', {})
        if package.get('version') == {'workspace': True}:
            names.add(package['name'])
    path = cargo / 'Cargo.lock'
    content = path.read_text(encoding='utf-8')
    blocks = content.split('[[package]]')
    for index, block in enumerate(blocks[1:], 1):
        item = tomllib.loads(block)
        if item.get('name') in names and 'source' not in item and item.get('version') == '0.0.0':
            blocks[index] = block.replace('version = "0.0.0"', f'version = "{version}"', 1)
    content = '[[package]]'.join(blocks)
    for name in names:
        content = content.replace(f'"{name} 0.0.0"', f'"{name} {version}"')
    path.write_text(content, encoding='utf-8', newline='\n')


def prepare(root):
    metadata = json.loads((HERE / 'upstream.json').read_text())
    git = ['git', '-c', 'safe.directory=' + root.as_posix(), '-c', 'core.longpaths=true', '-C', str(root)]
    revision = subprocess.check_output([*git, 'rev-parse', 'HEAD'], text=True).strip()
    if revision != metadata['commit'] or subprocess.check_output([*git, 'status', '--porcelain'], text=True).strip():
        raise ValueError('Native UI builds require the pinned clean upstream source')
    normalize_workspace_versions(root)
    edits = {
        'codex-rs/tui/src/main.rs': [
            ('use clap::Parser;', '#![recursion_limit = "256"]\n\nuse clap::Parser;')],
        'codex-rs/tui/src/chatwidget.rs': [
            ('mod model_popups;', 'mod model_popups;\nmod harness_routing;'),
            ('    model_popup_request_id: Option<uuid::Uuid>,',
             '    model_popup_request_id: Option<uuid::Uuid>,\n    harness_routing: Arc<std::sync::Mutex<harness_routing::Routing>>,'),
            ('        self.refresh_status_line_if_workspace_headline_due();',
             '        self.refresh_harness_status();\n        self.refresh_status_line_if_workspace_headline_due();')],
        'codex-rs/tui/src/chatwidget/status_surfaces.rs': [
            ('    fn model_with_reasoning_display_name(&self) -> String {',
             '    pub(super) fn model_with_reasoning_display_name(&self) -> String {'),
            ('StatusLineItem::ModelName => Some(self.model_display_name().to_string()),',
             'StatusLineItem::ModelName => Some(self.harness_model_status(self.model_display_name().to_string())),'),
            ('StatusLineItem::ModelWithReasoning => Some(self.model_with_reasoning_display_name()),',
             'StatusLineItem::ModelWithReasoning => Some(self.harness_model_status(self.model_with_reasoning_display_name())),')],
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
        'codex-rs/tui/src/chatwidget/replay.rs': [
            ('    pub(crate) fn replay_thread_turns(&mut self, turns: Vec<Turn>, replay_kind: ReplayKind) {',
             '    pub(crate) fn replay_thread_turns(&mut self, turns: Vec<Turn>, replay_kind: ReplayKind) {\n        if !turns.is_empty() { self.inherit_harness_task_from_native_history(); }')],
        'codex-rs/tui/src/chatwidget/session_flow.rs': [
            ('    pub(crate) fn handle_thread_session(&mut self, session: ThreadSessionState) {',
             '    pub(crate) fn handle_thread_session(&mut self, session: ThreadSessionState) {\n        self.report_harness_integration_problem();')],
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
    snapshots = root / 'codex-rs/tui/src/chatwidget/tests/snapshots'
    snapshots.mkdir(exist_ok=True)
    for path in (HERE / 'snapshots').glob('*.snap'):
        (snapshots / path.name).write_bytes(path.read_bytes())
    print(json.dumps({'upstream': revision, 'modified': ['codex-rs/Cargo.lock', *edits],
        'extensionSha256': hashlib.sha256((HERE / 'harness_routing.rs').read_bytes()).hexdigest(),
        'rendererModified': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    prepare(parser.parse_args().root.resolve())
