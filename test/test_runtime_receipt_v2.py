from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO_ROOT / "test"))

import harness_runtime_receipt as receipt2  # noqa: E402
import test_runtime_teamplay as runtime_fixture  # noqa: E402


def participant_names(plan: dict) -> list[str]:
    return [item.get("agent", item.get("runtimeParticipantId")) for item in plan["participants"]]


def public_core_lines() -> list[str]:
    return [
        json.dumps({"type": "thread.started", "thread_id": "parent-thread"}),
        json.dumps({"type": "turn.started"}),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 50,
                    "output_tokens": 20,
                },
            }
        ),
    ]


def public_collab_lines(
    plan: dict,
    *,
    terminal_statuses: dict[str, str] | None = None,
    prompt: str = "sensitive task text",
) -> list[str]:
    terminal_statuses = terminal_statuses or {}
    events: list[dict] = [
        {"type": "thread.started", "thread_id": "parent-thread"},
        {"type": "turn.started"},
    ]
    for index, participant in enumerate(participant_names(plan)):
        child = f"child-{index}"
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "type": "collab_tool_call",
                    "tool": "spawn_agent",
                    "status": "completed",
                    "sender_thread_id": "parent-thread",
                    "receiver_thread_ids": [child],
                    "prompt": prompt,
                    "agents_states": {child: {"status": "running", "message": "hidden"}},
                },
            }
        )
        status = terminal_statuses.get(participant, "completed")
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "type": "collab_tool_call",
                    "tool": "wait",
                    "status": "completed",
                    "sender_thread_id": "parent-thread",
                    "receiver_thread_ids": [child],
                    "agents_states": {child: {"status": status, "message": "hidden"}},
                },
            }
        )
    events.append({"type": "turn.completed", "usage": {"input_tokens": 100}})
    return [json.dumps(event) for event in events]


def control_plane_report(
    plan: dict,
    *,
    agent_overrides: dict[str, dict] | None = None,
    task_resolutions: dict[str, tuple[str, bool]] | None = None,
) -> dict:
    agent_overrides = agent_overrides or {}
    task_resolutions = task_resolutions or {}
    agents = []
    for index, participant in enumerate(participant_names(plan)):
        entry = {
            "participant": participant,
            "spawnRequested": True,
            "receiverHandle": f"/root/{participant}",
            "spawnInstanceId": f"spawn-{index}",
            "listed": True,
            "waitAttempts": 1,
            "waitTimeMs": 10,
            "waitStatus": "completed",
            "resultCollected": True,
        }
        entry.update(agent_overrides.get(participant, {}))
        agents.append(entry)
    tasks = []
    for task in plan["tasks"]:
        resolution, validated = task_resolutions.get(
            task["id"], ("delegated-output", True)
        )
        participant = None if resolution == "direct-output" else task["owner"]
        tasks.append(
            {
                "taskId": task["id"],
                "participant": participant,
                "resolution": resolution,
                "validated": validated,
            }
        )
    return {
        "schemaVersion": 1,
        "source": "codex-control-plane",
        "agents": agents,
        "tasks": tasks,
    }


def local_bindings(plan: dict, control: dict, *, role_overrides: dict[str, str] | None = None) -> dict:
    role_overrides = role_overrides or {}
    by_participant = {item["participant"]: item for item in control["agents"]}
    return {
        "schemaVersion": 2,
        "source": "local-session-observer",
        "profileId": receipt2.LOCAL_SUBAGENT_PROFILE,
        "parentThreadId": "parent-thread",
        "children": [
            {
                "participant": participant,
                "receiverHandle": by_participant[participant]["receiverHandle"],
                "spawnInstanceId": by_participant[participant]["spawnInstanceId"],
                "childThreadId": f"child-{index}",
                "parentThreadId": "parent-thread",
                "threadSource": "subagent",
                "agentRole": role_overrides.get(participant, participant),
            }
            for index, participant in enumerate(participant_names(plan))
        ],
    }


def local_activity_lines(
    plan: dict,
    *,
    terminal_kinds: dict[str, str] | None = None,
    include_terminal: bool = True,
) -> list[str]:
    terminal_kinds = terminal_kinds or {}
    events: list[dict] = []
    ordinal = 1
    for index, participant in enumerate(participant_names(plan)):
        for kind in (["started", terminal_kinds.get(participant, "completed")] if include_terminal else ["started"]):
            events.append(
                {
                    "timestamp": "2026-09-03T00:00:00Z",
                    "ordinal": ordinal,
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "thread_id": "parent-thread",
                        "turn_id": "turn-sensitive",
                        "item": {
                            "type": "SubAgentActivity",
                            "id": f"item-{ordinal}",
                            "kind": kind,
                            "agent_thread_id": f"child-{index}",
                            "agent_path": f"/root/{participant}",
                        },
                        "started_at_ms": 1,
                        "completed_at_ms": 2,
                    },
                }
            )
            ordinal += 1
    return [json.dumps(event) for event in events]


class RuntimeReceiptV2Tests(unittest.TestCase):
    def test_running_writer_fallback_warns_without_claiming_quiescence(self):
        control = control_plane_report(self.plan, agent_overrides={
            'api_producer': {'waitAttempts': 3, 'waitTimeMs': 300000, 'waitStatus': 'running', 'resultCollected': False}},
            task_resolutions={'prepare-change': ('fallback-output', True)})
        fallbacks = [{'participant': 'api_producer', 'taskIds': ['prepare-change'], 'adapter': 'direct',
                      'preserves': ['input', 'output', 'verification'], 'reasonCode': 'wait-budget-exhausted', 'source': 'agent-reported'}]
        result = self._build(control_plane=control, fallbacks=fallbacks)
        self.assertEqual(result['collaborationCompleteness'], 'partial')
        self.assertTrue(any('no observed quiescence' in message for message in result['warnings']))
        self.assertTrue(receipt2.validate_runtime_receipt(result)['valid'])

        result = self._build(control_plane=control, fallbacks=fallbacks,
            lines=public_collab_lines(self.plan, terminal_statuses={'api_producer': 'failed'}),
            public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE,
            observation_bindings=local_bindings(self.plan, control))
        self.assertFalse(any('no observed quiescence' in message for message in result['warnings']))
        self.assertTrue(receipt2.validate_runtime_receipt(result)['valid'])

    def test_fallback_report_order_does_not_change_canonical_warnings(self):
        participants = participant_names(self.plan)
        control = control_plane_report(self.plan,
            agent_overrides={name: {'waitStatus': 'running', 'resultCollected': False} for name in participants},
            task_resolutions={item['id']: ('fallback-output', True) for item in self.plan['tasks']})
        fallbacks = [{'participant': name, 'taskIds': [item['id'] for item in self.plan['tasks'] if item['owner'] == name],
                      'adapter': 'direct', 'preserves': ['input', 'output', 'verification'],
                      'reasonCode': 'wait-budget-exhausted', 'source': 'agent-reported'} for name in participants]
        forward = self._build(control_plane=control, fallbacks=fallbacks)
        reverse = self._build(control_plane=control, fallbacks=list(reversed(fallbacks)))
        self.assertEqual(forward['warnings'], reverse['warnings'])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        manifest = runtime_fixture.write_manifest(self.root)
        self.plan = runtime_fixture.valid_plan(self.root, manifest)

    def _build(self, **overrides: object) -> dict:
        control = control_plane_report(self.plan)
        values: dict[str, object] = {
            "plan": self.plan,
            "lines": public_core_lines(),
            "public_profile_id": receipt2.PUBLIC_CORE_PROFILE,
            "control_plane": control,
            "observation_bindings": None,
            "codex_cli_version": "0.152.1",
            "execution_mode": "persistent",
            "repository_id": "repo-" + "b" * 16,
            "harness_commit": "a" * 40,
            "salt": b"runtime-receipt-salt",
            "local_lines": None,
            "local_profile_id": None,
            "fallbacks": None,
        }
        values.update(overrides)
        return receipt2.build_runtime_receipt(**values)

    def _single_agent_plan(self) -> dict:
        plan = copy.deepcopy(self.plan)
        plan["participants"] = plan["participants"][:1]
        plan["tasks"] = plan["tasks"][:1]
        return plan

    def test_canonical_handle_completion_does_not_require_session_binding(self) -> None:
        plan = self._single_agent_plan()
        receipt = self._build(plan=plan, control_plane=control_plane_report(plan))
        agent = receipt["agents"][0]
        self.assertTrue(agent["receiverHandleAcknowledged"])
        self.assertFalse(agent["sessionBound"])
        self.assertTrue(agent["completed"])
        self.assertEqual(agent["completionSources"], ["control-plane-wait"])
        self.assertEqual(agent["completionEvidenceStrength"], "control-plane")
        self.assertEqual(receipt["collaborationCompleteness"], "complete")
        self.assertTrue(receipt["provesLiveSubagentExecution"])

    def test_missing_handle_falls_back_without_wait(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        task_id = plan["tasks"][0]["id"]
        control = control_plane_report(
            plan,
            agent_overrides={
                participant: {
                    "receiverHandle": None,
                    "spawnInstanceId": None,
                    "listed": False,
                    "waitAttempts": 0,
                    "waitTimeMs": 0,
                    "waitStatus": "not-waited",
                    "resultCollected": False,
                }
            },
            task_resolutions={task_id: ("fallback-output", True)},
        )
        receipt = self._build(
            plan=plan,
            control_plane=control,
            fallbacks=[
                {
                    "participant": participant,
                    "taskIds": [task_id],
                    "adapter": "direct",
                    "preserves": ["input", "output", "verification"],
                    "reasonCode": "missing-receiver-handle",
                    "source": "agent-reported",
                }
            ],
        )
        agent = receipt["agents"][0]
        self.assertFalse(agent["receiverHandleAcknowledged"])
        self.assertFalse(agent["completed"])
        self.assertEqual(agent["waitAttempts"], 0)
        self.assertEqual(agent["failureSource"], "mixed")
        self.assertEqual(agent["fallbackReasonCode"], "missing-receiver-handle")
        self.assertEqual(receipt["taskAccountingStatus"], "complete-fallback")
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_missing_handle_wait_attempt_is_recorded_as_invalid_control(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        control = control_plane_report(
            plan,
            agent_overrides={
                participant: {
                    "receiverHandle": None,
                    "spawnInstanceId": None,
                    "listed": False,
                    "waitAttempts": 1,
                    "waitTimeMs": 10,
                    "waitStatus": "completed",
                    "resultCollected": False,
                }
            },
        )
        receipt = self._build(plan=plan, control_plane=control)
        self.assertIn(
            "wait-on-unknown-handle", receipt["agents"][0]["failureCodes"]
        )

    def test_noncompleted_wait_cannot_claim_collected_result(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        control = control_plane_report(
            plan,
            agent_overrides={
                participant: {
                    "waitStatus": "failed",
                    "resultCollected": True,
                }
            },
        )
        with self.assertRaisesRegex(receipt2.RuntimeReceiptError, "completed wait"):
            self._build(plan=plan, control_plane=control)

    def test_unknown_handle_cannot_be_waited(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        control = control_plane_report(
            plan,
            agent_overrides={participant: {"listed": False, "waitAttempts": 1}},
        )
        receipt = self._build(plan=plan, control_plane=control)
        self.assertIn("unknown-receiver-handle", receipt["agents"][0]["failureCodes"])
        self.assertIn("wait-on-unknown-handle", receipt["agents"][0]["failureCodes"])
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_duplicate_terminal_events_do_not_complete_missing_participant_coverage(self) -> None:
        bindings = local_bindings(self.plan, control_plane_report(self.plan))
        public = public_collab_lines(self.plan)
        public_waits = [line for line in public if json.loads(line).get("item", {}).get("tool") == "wait"]
        public_other = [line for line in public if line not in public_waits]
        local = local_activity_lines(self.plan)
        local_terminals = [line for line in local if json.loads(line)["payload"]["item"]["kind"] == "completed"]
        local_other = [line for line in local if line not in local_terminals]
        for repetitions in (1, 2, 5):
            for source in ("public-jsonl", "local-rollout"):
                with self.subTest(source=source, repetitions=repetitions):
                    arguments = {"observation_bindings": bindings}
                    if source == "public-jsonl":
                        arguments.update(lines=[*public_other[:-1], *([public_waits[0]] * repetitions), public_other[-1]],
                                         public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE)
                    else:
                        arguments.update(local_lines=[*local_other, *([local_terminals[0]] * repetitions)],
                                         local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE)
                    receipt = self._build(**arguments)
                    profile = next(item for item in receipt["eventProfiles"] if item["source"] == source)
                    self.assertEqual(profile["collaborationCompleteness"], "partial")
                    self.assertTrue(receipt2.validate_runtime_receipt(receipt)["valid"])
        complete = self._build(lines=[*public, *public_waits], public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE,
                               observation_bindings=bindings, local_lines=[*local, *local_terminals],
                               local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE)
        self.assertEqual([item["collaborationCompleteness"] for item in complete["eventProfiles"]], ["complete", "complete"])
        self.assertTrue(receipt2.validate_runtime_receipt(complete)["valid"])

    def test_started_without_terminal_is_partial(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        control = control_plane_report(
            plan,
            agent_overrides={
                participant: {
                    "waitStatus": "running",
                    "resultCollected": False,
                }
            },
            task_resolutions={plan["tasks"][0]["id"]: ("none", False)},
        )
        bindings = local_bindings(plan, control)
        receipt = self._build(
            plan=plan,
            control_plane=control,
            observation_bindings=bindings,
            local_lines=local_activity_lines(plan, include_terminal=False),
            local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE,
        )
        self.assertFalse(receipt["agents"][0]["completed"])
        self.assertEqual(receipt["collaborationCompleteness"], "partial")
        self.assertEqual(receipt["taskAccountingStatus"], "partial")

    def test_running_and_completed_at_different_sources_are_not_conflict(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        bindings = local_bindings(plan, control)
        participant = participant_names(plan)[0]
        receipt = self._build(
            plan=plan,
            lines=public_collab_lines(plan, terminal_statuses={participant: "running"}),
            public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE,
            control_plane=control,
            observation_bindings=bindings,
            local_lines=local_activity_lines(plan),
            local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE,
        )
        self.assertFalse(receipt["runtime"]["conflictDetected"])
        self.assertTrue(receipt["agents"][0]["completed"])
        self.assertEqual(receipt["agents"][0]["completionEvidenceStrength"], "cross-validated")

    def test_incompatible_terminal_outcomes_fail_closed(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        bindings = local_bindings(plan, control)
        participant = participant_names(plan)[0]
        receipt = self._build(
            plan=plan,
            control_plane=control,
            observation_bindings=bindings,
            local_lines=local_activity_lines(
                plan, terminal_kinds={participant: "errored"}
            ),
            local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE,
        )
        self.assertTrue(receipt["runtime"]["conflictDetected"])
        self.assertEqual(receipt["collaborationCompleteness"], "conflicted")
        self.assertIn("completion-conflict", receipt["agents"][0]["failureCodes"])
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_some_delegated_and_some_fallback_is_complete_mixed(self) -> None:
        participants = participant_names(self.plan)
        fallback_participant = participants[1]
        fallback_task = self.plan["tasks"][1]["id"]
        control = control_plane_report(
            self.plan,
            agent_overrides={
                fallback_participant: {
                    "waitStatus": "failed",
                    "resultCollected": False,
                }
            },
            task_resolutions={fallback_task: ("fallback-output", True)},
        )
        receipt = self._build(
            control_plane=control,
            fallbacks=[
                {
                    "participant": fallback_participant,
                    "taskIds": [fallback_task],
                    "adapter": "direct",
                    "preserves": ["input", "output", "verification"],
                    "reasonCode": "wait-failed",
                    "source": "agent-reported",
                }
            ],
        )
        by_participant = {item["participant"]: item for item in receipt["agents"]}
        self.assertTrue(by_participant[participants[0]]["completed"])
        self.assertTrue(by_participant[fallback_participant]["fallback"])
        self.assertEqual(by_participant[fallback_participant]["failureSource"], "mixed")
        self.assertEqual(receipt["taskAccountingStatus"], "complete-mixed")

    def test_direct_task_accounting_is_explicit(self) -> None:
        task_resolutions = {
            task["id"]: ("direct-output", True) for task in self.plan["tasks"]
        }
        control = control_plane_report(
            self.plan,
            agent_overrides={
                participant: {
                    "spawnRequested": False,
                    "receiverHandle": None,
                    "spawnInstanceId": None,
                    "listed": False,
                    "waitAttempts": 0,
                    "waitTimeMs": 0,
                    "waitStatus": "not-waited",
                    "resultCollected": False,
                }
                for participant in participant_names(self.plan)
            },
            task_resolutions=task_resolutions,
        )
        receipt = self._build(control_plane=control)
        self.assertEqual(receipt["taskAccountingStatus"], "complete-direct")
        self.assertEqual(receipt["collaborationCompleteness"], "not-exposed")

    def test_unregistered_profile_cannot_claim_not_exposed_for_direct_execution(self) -> None:
        task_resolutions = {
            task["id"]: ("direct-output", True) for task in self.plan["tasks"]
        }
        control = control_plane_report(
            self.plan,
            agent_overrides={
                participant: {
                    "spawnRequested": False,
                    "receiverHandle": None,
                    "spawnInstanceId": None,
                    "listed": False,
                    "waitAttempts": 0,
                    "waitTimeMs": 0,
                    "waitStatus": "not-waited",
                    "resultCollected": False,
                }
                for participant in participant_names(self.plan)
            },
            task_resolutions=task_resolutions,
        )
        receipt = self._build(
            control_plane=control,
            public_profile_id="unknown-public-surface",
        )
        self.assertEqual(receipt["eventProfiles"][0]["compatibility"], "unsupported")
        self.assertEqual(receipt["collaborationCompleteness"], "unobserved")

    def test_conflicting_parent_terminal_events_fail_closed(self) -> None:
        plan = self._single_agent_plan()
        lines = public_core_lines() + [json.dumps({"type": "turn.failed"})]
        receipt = self._build(
            plan=plan,
            lines=lines,
            control_plane=control_plane_report(plan),
        )
        self.assertTrue(receipt["runtime"]["conflictDetected"])
        self.assertEqual(receipt["collaborationCompleteness"], "conflicted")
        self.assertIn("completion-conflict", receipt["agents"][0]["failureCodes"])

    def test_unsupported_profile_does_not_stop_valid_handle_execution(self) -> None:
        plan = self._single_agent_plan()
        receipt = self._build(
            plan=plan,
            control_plane=control_plane_report(plan),
            public_profile_id="private-user-profile-name",
        )
        self.assertEqual(receipt["eventProfiles"][0]["profileId"], "unregistered-public")
        self.assertEqual(receipt["eventProfiles"][0]["compatibility"], "unsupported")
        self.assertTrue(receipt["agents"][0]["completed"])
        self.assertTrue(receipt["provesLiveSubagentExecution"])

    def test_new_cli_version_keeps_known_wire_contract(self) -> None:
        plan = self._single_agent_plan()
        receipt = self._build(
            plan=plan,
            control_plane=control_plane_report(plan),
            codex_cli_version="0.153.0",
        )
        profile = receipt["eventProfiles"][0]
        self.assertEqual(profile["profileId"], receipt2.PUBLIC_CORE_PROFILE)
        self.assertEqual(profile["compatibility"], "supported")
        self.assertEqual(profile["collaborationCompleteness"], "not-exposed")
        self.assertTrue(receipt["agents"][0]["completed"])

    def test_core_profile_with_collaboration_event_is_conflicted(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        bindings = local_bindings(plan, control)
        receipt = self._build(
            plan=plan,
            lines=public_collab_lines(plan),
            public_profile_id=receipt2.PUBLIC_CORE_PROFILE,
            control_plane=control,
            observation_bindings=bindings,
        )
        self.assertEqual(receipt["collaborationCompleteness"], "conflicted")
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_public_and_local_shapes_work_with_future_version_labels(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        for version in ("0.154.0", "99.42.7", "codex-cli nightly-custom"):
            with self.subTest(version=version):
                receipt = self._build(plan=plan, control_plane=control,
                    observation_bindings=local_bindings(plan, control),
                    lines=public_collab_lines(plan), public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE,
                    local_lines=local_activity_lines(plan), local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE,
                    codex_cli_version=version)
                self.assertTrue(receipt["provesLiveSubagentExecution"])
                self.assertEqual([p["compatibility"] for p in receipt["eventProfiles"]], ["supported", "supported"])
                self.assertEqual(receipt["codexCliVersion"], version)

    def test_changed_event_shape_degrades_without_fabricating_a_conflict(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        lines = [json.loads(line) for line in public_collab_lines(plan)]
        for event in lines:
            if isinstance(event.get("item"), dict):
                event["item"].pop("sender_thread_id", None)
        receipt = self._build(plan=plan, control_plane=control,
            observation_bindings=local_bindings(plan, control), codex_cli_version="future-build",
            lines=[json.dumps(line) for line in lines], public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE)
        self.assertEqual(receipt["eventProfiles"][0]["compatibility"], "degraded")
        self.assertFalse(receipt["runtime"]["conflictDetected"])
        self.assertTrue(receipt["agents"][0]["completed"])

    def test_surface_fingerprint_excludes_prompt_and_unknown_fields(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        bindings = local_bindings(plan, control)
        baseline_lines = public_collab_lines(plan, prompt="first secret")
        changed = [json.loads(line) for line in baseline_lines]
        for event in changed:
            event["private_field_name"] = "second secret"
            if isinstance(event.get("item"), dict):
                event["item"]["prompt"] = "second secret"
        baseline = self._build(
            plan=plan,
            lines=baseline_lines,
            public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE,
            control_plane=control,
            observation_bindings=bindings,
        )
        altered = self._build(
            plan=plan,
            lines=[json.dumps(event) for event in changed],
            public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE,
            control_plane=control,
            observation_bindings=bindings,
        )
        self.assertEqual(
            baseline["eventProfiles"][0]["surfaceFingerprint"],
            altered["eventProfiles"][0]["surfaceFingerprint"],
        )
        self.assertNotIn("secret", json.dumps(altered))

    def test_binding_role_conflict_fails_closed(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        participant = participant_names(plan)[0]
        bindings = local_bindings(
            plan, control, role_overrides={participant: "wrong-role"}
        )
        receipt = self._build(
            plan=plan,
            control_plane=control,
            observation_bindings=bindings,
            local_lines=local_activity_lines(plan),
            local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE,
        )
        self.assertTrue(receipt["runtime"]["conflictDetected"])
        self.assertFalse(receipt["agents"][0]["sessionBound"])

    def test_public_parent_binding_conflict_has_agent_failure_source(self) -> None:
        plan = self._single_agent_plan()
        control = control_plane_report(plan)
        bindings = local_bindings(plan, control)
        events = [json.loads(line) for line in public_collab_lines(plan)]
        for event in events:
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "collab_tool_call":
                item["sender_thread_id"] = "different-parent"
        receipt = self._build(
            plan=plan,
            lines=[json.dumps(event) for event in events],
            public_profile_id=receipt2.PUBLIC_COLLAB_PROFILE,
            control_plane=control,
            observation_bindings=bindings,
        )
        agent = receipt["agents"][0]
        self.assertEqual(receipt["collaborationCompleteness"], "conflicted")
        self.assertIn("binding-conflict", agent["failureCodes"])
        self.assertEqual(agent["failureSource"], "binding")

    def test_turn_started_is_not_unknown_structure(self) -> None:
        plan = self._single_agent_plan()
        receipt = self._build(plan=plan, control_plane=control_plane_report(plan))
        self.assertEqual(receipt["eventProfiles"][0]["unknownStructureCount"], 0)
        self.assertEqual(receipt["streamCompleteness"], "complete")

    def test_agent_reported_source_cannot_establish_completion(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        task_id = plan["tasks"][0]["id"]
        control = control_plane_report(
            plan,
            agent_overrides={
                participant: {
                    "receiverHandle": None,
                    "spawnInstanceId": None,
                    "listed": False,
                    "waitAttempts": 0,
                    "waitTimeMs": 0,
                    "waitStatus": "not-waited",
                    "resultCollected": False,
                }
            },
            task_resolutions={task_id: ("fallback-output", True)},
        )
        receipt = self._build(
            plan=plan,
            control_plane=control,
            fallbacks=[
                {
                    "participant": participant,
                    "taskIds": [task_id],
                    "adapter": "direct",
                    "preserves": ["input", "output", "verification"],
                    "reasonCode": "subagent-unavailable",
                    "source": "agent-reported",
                }
            ],
        )
        self.assertFalse(receipt["agents"][0]["completed"])
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_fallback_reason_code_is_closed(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        task_id = plan["tasks"][0]["id"]
        control = control_plane_report(
            plan,
            agent_overrides={
                participant: {
                    "receiverHandle": None,
                    "spawnInstanceId": None,
                    "listed": False,
                    "waitAttempts": 0,
                    "waitTimeMs": 0,
                    "waitStatus": "not-waited",
                    "resultCollected": False,
                }
            },
            task_resolutions={task_id: ("fallback-output", True)},
        )
        with self.assertRaisesRegex(receipt2.RuntimeReceiptError, "reasonCode"):
            self._build(
                plan=plan,
                control_plane=control,
                fallbacks=[
                    {
                        "participant": participant,
                        "taskIds": [task_id],
                        "adapter": "direct",
                        "preserves": ["input", "output", "verification"],
                        "reasonCode": "free-form-reason",
                        "source": "agent-reported",
                    }
                ],
            )

    def test_fallback_success_does_not_erase_runtime_conflict(self) -> None:
        plan = self._single_agent_plan()
        participant = participant_names(plan)[0]
        task_id = plan["tasks"][0]["id"]
        control = control_plane_report(
            plan,
            agent_overrides={
                participant: {
                    "waitStatus": "failed",
                    "resultCollected": False,
                }
            },
            task_resolutions={task_id: ("fallback-output", True)},
        )
        receipt = self._build(
            plan=plan,
            control_plane=control,
            observation_bindings=local_bindings(plan, control),
            local_lines=local_activity_lines(plan),
            local_profile_id=receipt2.LOCAL_SUBAGENT_PROFILE,
            fallbacks=[
                {
                    "participant": participant,
                    "taskIds": [task_id],
                    "adapter": "direct",
                    "preserves": ["input", "output", "verification"],
                    "reasonCode": "wait-failed",
                    "source": "agent-reported",
                }
            ],
        )
        self.assertEqual(receipt["taskAccountingStatus"], "complete-fallback")
        self.assertEqual(receipt["collaborationCompleteness"], "conflicted")
        self.assertTrue(receipt["runtime"]["conflictDetected"])

    def test_schema2_hash_and_privacy_are_enforced(self) -> None:
        plan = self._single_agent_plan()
        receipt = self._build(plan=plan, control_plane=control_plane_report(plan))
        receipt["measurements"]["inputTokens"] = 999
        with self.assertRaisesRegex(receipt2.RuntimeReceiptError, "hash"):
            receipt2.validate_runtime_receipt(receipt)
        clean = self._build(plan=plan, control_plane=control_plane_report(plan))
        clean["receiverHandle"] = "/root/secret"
        with self.assertRaisesRegex(receipt2.RuntimeReceiptError, "privacy-forbidden"):
            receipt2.validate_runtime_receipt(clean)

    def test_schema1_golden_receipt_remains_valid(self) -> None:
        golden = json.loads(
            (REPO_ROOT / "test" / "fixtures" / "runtime-receipt-schema1-golden.json").read_text(
                encoding="utf-8"
            )
        )
        report = receipt2.validate_runtime_receipt(golden)
        self.assertEqual(report["receiptSchemaVersion"], 1)
        self.assertTrue(report["valid"])

    def test_schema2_cli_preserves_repository_state(self) -> None:
        plan = self.plan
        control = control_plane_report(plan)
        plan_path = self.root / "runtime-plan.json"
        jsonl_path = self.root / "events.jsonl"
        control_path = self.root / "control.json"
        salt_path = self.root / "salt.bin"
        output_path = self.root / "receipt.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        jsonl_path.write_text("\n".join(public_core_lines()) + "\n", encoding="utf-8")
        control_path.write_text(json.dumps(control), encoding="utf-8")
        salt_path.write_bytes(b"runtime-receipt-salt")
        manifest_path = self.root / ".harness" / "manifest.json"
        before = manifest_path.read_bytes()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "harness_runtime_receipt.py"),
                "--root",
                str(self.root),
                "--plan",
                str(plan_path),
                "--jsonl",
                str(jsonl_path),
                "--public-profile",
                receipt2.PUBLIC_CORE_PROFILE,
                "--control-plane-report",
                str(control_path),
                "--codex-cli-version",
                "0.152.1",
                "--execution-mode",
                "persistent",
                "--repository-id",
                "repo-" + "b" * 16,
                "--harness-commit",
                "a" * 40,
                "--salt-file",
                str(salt_path),
                "--output",
                str(output_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["receiptSchemaVersion"], 2)
        self.assertEqual(before, manifest_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
