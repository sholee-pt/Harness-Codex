from __future__ import annotations

import json
import contextlib
import io
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness_metadata  # noqa: E402
import harness_ops  # noqa: E402


class OperationsEvidenceTests(unittest.TestCase):
    def _workspace(self, parent: Path) -> Path:
        root = parent / "workspace"
        manifest = root / ".harness" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": harness_metadata.MANIFEST_SCHEMA_VERSION,
                    "generator": {
                        "name": "Harness",
                        "version": harness_metadata.HARNESS_VERSION,
                        "runtime": "codex",
                    },
                    "workspace": {"kind": "plain-directory", "scope": "project-local"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return root

    def _hook(
        self,
        root: Path,
        event: str,
        *,
        turn: str = "turn-one",
        prompt: str = "private prompt",
        agent_type: str = "private-reviewer",
        agent_id: str = "private-instance",
        response: str = "private response",
    ) -> dict:
        value = {
            "hook_event_name": event,
            "session_id": "private-session",
            "cwd": str(root),
        }
        if event != "SessionEnd":
            value["turn_id"] = turn
        if event == "UserPromptSubmit":
            value["prompt"] = prompt
        elif event in {"SubagentStart", "SubagentStop"}:
            value["agent_type"] = agent_type
            value["agent_id"] = agent_id
        elif event == "Stop":
            value["last_assistant_message"] = response
        return value

    def test_each_user_turn_is_a_distinct_work_item_without_raw_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self._workspace(parent)
            state = parent / "state"
            first = harness_ops.record_hook_event(
                self._hook(root, "UserPromptSubmit", prompt="secret first request"),
                state_root=state,
            )
            time.sleep(0.001)
            second = harness_ops.record_hook_event(
                self._hook(
                    root,
                    "UserPromptSubmit",
                    turn="turn-two",
                    prompt="secret correction request",
                ),
                state_root=state,
            )
            harness_ops.record_hook_event(
                self._hook(
                    root,
                    "SubagentStart",
                    turn="turn-two",
                    agent_type="secret-agent-name",
                    agent_id="secret-agent-id",
                ),
                state_root=state,
            )
            harness_ops.record_hook_event(
                self._hook(
                    root,
                    "SubagentStop",
                    turn="turn-two",
                    agent_type="secret-agent-name",
                    agent_id="secret-agent-id",
                ),
                state_root=state,
            )
            harness_ops.record_hook_event(
                self._hook(
                    root,
                    "Stop",
                    turn="turn-two",
                    response="secret model response",
                ),
                state_root=state,
            )

            self.assertNotEqual(first["workItemRef"], second["workItemRef"])
            annotation = harness_ops.annotate(
                root=root,
                work_item_ref=second["workItemRef"],
                relation="correction",
                category="bugfix",
                execution_class="delegated",
                agent_selection="appropriate",
                outcome="verified",
                verification="passed",
                evidence_source="verification",
                state_root=state,
            )
            self.assertTrue(annotation["valid"])
            report = harness_ops.audit(root, state_root=state)
            self.assertTrue(report["valid"])
            self.assertEqual(report["workItemCount"], 2)
            self.assertEqual(report["annotatedWorkItemCount"], 1)
            self.assertEqual(report["relationCounts"]["correction"], 1)
            self.assertEqual(report["agentSelectionCounts"]["appropriate"], 1)
            self.assertEqual(report["outcomeCounts"]["verified"], 1)
            self.assertEqual(report["danglingAgentInstanceCount"], 0)
            self.assertEqual(report["status"], "insufficient-evidence")
            first_item = next(
                item for item in report["workItems"]
                if item["workItemRef"] == first["workItemRef"]
            )
            self.assertEqual(first_item["correctionCount"], 1)

            event_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in state.rglob("operations/events/*.json")
            )
            for raw_value in (
                "secret first request",
                "secret correction request",
                "secret model response",
                "secret-agent-name",
                "secret-agent-id",
                "private-session",
                str(root),
            ):
                self.assertNotIn(raw_value, event_text)

    def test_hook_replay_is_idempotent_and_contradiction_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self._workspace(parent)
            state = parent / "state"
            hook = self._hook(root, "UserPromptSubmit", prompt="one")
            first = harness_ops.record_hook_event(hook, state_root=state)
            replay = harness_ops.record_hook_event(hook, state_root=state)
            self.assertTrue(first["created"])
            self.assertFalse(replay["created"])
            with self.assertRaisesRegex(harness_ops.OperationsError, "contradicts"):
                harness_ops.record_hook_event(
                    self._hook(root, "UserPromptSubmit", prompt="different"),
                    state_root=state,
                )

    def test_indexed_hooks_do_not_read_prior_history_and_replay_checks_its_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, state = self._workspace(parent), parent / "state"
            for index in range(12):
                harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn=str(index)), state_root=state)
            with mock.patch.object(harness_ops, '_read_events', side_effect=AssertionError('cumulative history scan')), \
                    mock.patch.object(harness_ops, '_read_event', wraps=harness_ops._read_event) as read:
                result = harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn="new"), state_root=state)
                self.assertTrue(result['created'])
                self.assertEqual(read.call_count, 0)
                result = harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn="new"), state_root=state)
                self.assertFalse(result['created'])
                self.assertEqual(read.call_count, 1)
            self.assertEqual(harness_ops.audit(root, state_root=state)['workItemCount'], 13)

    def test_interrupted_index_write_rebuilds_without_duplicate_or_last_active_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, state = self._workspace(parent), parent / "state"
            first = harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit"), state_root=state)
            with mock.patch.object(harness_ops, '_write_index', side_effect=OSError('interrupted index write')):
                with self.assertRaises(OSError):
                    harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn="next"), state_root=state)
            second = harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn="next"), state_root=state)
            self.assertFalse(second['created'])
            harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit"), state_root=state)
            result = harness_ops.annotate(root=root, work_item_ref=None, relation='correction', category='feature',
                execution_class='direct', agent_selection='not-applicable', outcome='unknown', verification='unknown',
                evidence_source='agent-reported', state_root=state)
            self.assertEqual(result['workItemRef'], second['workItemRef'])
            report = harness_ops.audit(root, state_root=state)
            self.assertEqual(report['workItemCount'], 2)
            self.assertEqual(next(item for item in report['workItems'] if item['workItemRef'] == first['workItemRef'])['correctionCount'], 1)

    def test_index_corruption_or_removal_rebuilds_and_replayed_record_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, state = self._workspace(parent), parent / "state"
            hook = self._hook(root, "UserPromptSubmit")
            harness_ops.record_hook_event(hook, state_root=state)
            index_path = next(state.rglob('operations/index.json'))
            index = json.loads(index_path.read_text())
            index['count'], index['replay'], index['lifecycle'] = 0, {}, {}
            index_path.write_text(json.dumps(index))
            self.assertFalse(harness_ops.record_hook_event(hook, state_root=state)['created'])
            index_path.unlink()
            self.assertFalse(harness_ops.record_hook_event(hook, state_root=state)['created'])
            event_path = next(state.rglob('operations/events/*.json'))
            event = json.loads(event_path.read_text())
            event['payload']['promptFingerprint'] = '0' * 64
            event_path.write_text(json.dumps(event))
            with self.assertRaises(harness_ops.OperationsError):
                harness_ops.record_hook_event(hook, state_root=state)
            self.assertFalse(harness_ops.audit(root, state_root=state)['valid'])

    def test_purge_removes_index_and_releases_capacity_without_retaining_raw_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, state = self._workspace(parent), parent / "state"
            with mock.patch.object(harness_ops, 'MAX_EVENTS_PER_REPOSITORY', 2):
                for turn in ('first', 'second'):
                    harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn=turn), state_root=state)
                self.assertFalse(harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn='first'), state_root=state)['created'])
                with self.assertRaisesRegex(harness_ops.OperationsError, 'event limit'):
                    harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn='third'), state_root=state)
                index_path = next(state.rglob('operations/index.json'))
                content = index_path.read_text()
                for raw in ('private prompt', 'private-session', 'first', 'second', str(root)):
                    self.assertNotIn(raw, content)
                with contextlib.redirect_stdout(io.StringIO()):
                    harness_ops.command_purge(SimpleNamespace(root=str(root), state_home=str(state)))
                self.assertFalse(index_path.exists())
                self.assertTrue(harness_ops.record_hook_event(self._hook(root, "UserPromptSubmit", turn='third'), state_root=state)['created'])

    def test_branched_annotation_history_is_reported_and_cannot_be_extended(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, state = self._workspace(parent), parent / "state"
            recorded = harness_ops.record_hook_event(self._hook(root, 'UserPromptSubmit'), state_root=state)
            arguments = dict(root=root, work_item_ref=recorded['workItemRef'], relation='new-task', category='feature',
                execution_class='direct', agent_selection='not-applicable', outcome='unknown', verification='unknown',
                evidence_source='agent-reported', state_root=state)
            harness_ops.annotate(**arguments)
            second = harness_ops.annotate(**arguments)
            path = next(state.rglob('operations/events/' + second['annotationEventId'] + '.json'))
            event = json.loads(path.read_text())
            event['payload']['supersedesEventId'] = None
            path.write_text(json.dumps(harness_ops._seal(event)))
            self.assertFalse(harness_ops.audit(root, state_root=state)['valid'])
            with self.assertRaisesRegex(harness_ops.OperationsError, 'branched'):
                harness_ops.annotate(**arguments)

    def test_annotation_requires_evidence_consistent_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self._workspace(parent)
            state = parent / "state"
            result = harness_ops.record_hook_event(
                self._hook(root, "UserPromptSubmit"), state_root=state
            )
            common = {
                "root": root,
                "work_item_ref": result["workItemRef"],
                "relation": "new-task",
                "category": "feature",
                "execution_class": "direct",
                "agent_selection": "not-applicable",
                "state_root": state,
            }
            with self.assertRaisesRegex(harness_ops.OperationsError, "user-reported"):
                harness_ops.annotate(
                    **common,
                    outcome="user-accepted",
                    verification="unknown",
                    evidence_source="agent-reported",
                )
            with self.assertRaisesRegex(harness_ops.OperationsError, "passed verification"):
                harness_ops.annotate(
                    **common,
                    outcome="verified",
                    verification="failed",
                    evidence_source="verification",
                )
            with self.assertRaisesRegex(harness_ops.OperationsError, "requires an earlier"):
                harness_ops.annotate(
                    **{**common, "relation": "correction"},
                    outcome="needs-revision",
                    verification="failed",
                    evidence_source="user-reported",
                )

    def test_non_harness_workspace_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "ordinary-project"
            root.mkdir()
            state = parent / "state"
            result = harness_ops.record_hook_event(
                self._hook(root, "UserPromptSubmit"), state_root=state
            )
            self.assertEqual(
                result,
                {"recorded": False, "reason": "not-a-local-harness-workspace"},
            )
            self.assertFalse(state.exists())

    def test_audit_fails_closed_on_tampered_event_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = self._workspace(parent)
            state = parent / "state"
            harness_ops.record_hook_event(
                self._hook(root, "UserPromptSubmit"), state_root=state
            )
            event_path = next(state.rglob("operations/events/*.json"))
            event = json.loads(event_path.read_text(encoding="utf-8"))
            event["payload"]["promptFingerprint"] = "0" * 64
            event_path.write_text(json.dumps(event), encoding="utf-8")
            report = harness_ops.audit(root, state_root=state)
            self.assertFalse(report["valid"])
            self.assertEqual(report["status"], "state-invalid")
            self.assertEqual(report["invalidEventCount"], 1)

    def test_hooks_template_is_opt_in_and_never_overwrites(self) -> None:
        config = harness_ops.hook_configuration()
        self.assertEqual(
            set(config["hooks"]),
            {"UserPromptSubmit", "SubagentStart", "SubagentStop", "Stop", "SessionEnd"},
        )
        command = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertIn("harness_ops.py", command)
        self.assertIn("hook", command)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "hooks.json"
            args = harness_ops.build_parser().parse_args(
                ["hooks-template", "--output", str(output)]
            )
            self.assertEqual(harness_ops.command_hooks_template(args), 0)
            with self.assertRaisesRegex(harness_ops.OperationsError, "refusing to overwrite"):
                harness_ops.command_hooks_template(args)

    def test_event_repository_and_filename_must_match_the_selected_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, other = self._workspace(parent / 'first'), self._workspace(parent / 'second')
            state = parent / 'state'
            first = harness_ops.record_hook_event(self._hook(root, 'UserPromptSubmit'), state_root=state)
            second = harness_ops.record_hook_event(self._hook(other, 'UserPromptSubmit'), state_root=state)
            store = harness_ops.harness_eval_store.EvaluationStore(state)
            source = next(harness_ops._events_root(store, first['repositoryId']).glob('*.json'))
            foreign = harness_ops._events_root(store, second['repositoryId']) / source.name
            foreign.write_bytes(source.read_bytes())
            report = harness_ops.audit(other, state_root=state)
            self.assertFalse(report['valid'])
            self.assertEqual(report['invalidEventCount'], 1)
            foreign.unlink()
            copied = source.with_name('00000000-0000-4000-8000-000000000000.json')
            copied.write_bytes(source.read_bytes())
            report = harness_ops.audit(root, state_root=state)
            self.assertFalse(report['valid'])
            self.assertEqual(report['invalidEventCount'], 1)


if __name__ == "__main__":
    unittest.main()
