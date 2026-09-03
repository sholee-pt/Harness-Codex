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

import harness_metadata  # noqa: E402
import harness_coordination  # noqa: E402
import harness_change_discipline  # noqa: E402
import harness_plan_builder  # noqa: E402
import harness_relay_receipt  # noqa: E402
import harness_runtime_receipt  # noqa: E402
import harness_runtime_receipt_schema1  # noqa: E402
import harness_teamplay  # noqa: E402
import harness_topology  # noqa: E402
import harness_apply  # noqa: E402
import validate_runtime_plan as runtime_plan  # noqa: E402


def fixture_manifest() -> dict:
    topology_fixture = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "coordinated-cross-contract-topology.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        "schemaVersion": harness_metadata.MANIFEST_SCHEMA_VERSION,
        "generator": {
            "name": "Harness",
            "version": harness_metadata.HARNESS_VERSION,
            "runtime": harness_metadata.RUNTIME,
        },
        "application": {
            "mode": "journaled",
            "transactionSchemaVersion": harness_metadata.TRANSACTION_SCHEMA_VERSION,
        },
        "instructionFile": "AGENTS.md",
        "project": {
            "summary": "Runtime teamplay fixture",
            "evidence": [{"path": "README.md", "sha256": "0" * 64, "claim": "Fixture."}],
            "rationale": {"summary": "Exercises runtime-only validation.", "uncertainties": []},
        },
        "topology": topology_fixture["topology"],
        "capabilityPolicies": topology_fixture["capabilityPolicies"],
        "managedFiles": [],
    }


def write_manifest(root: Path) -> dict:
    manifest = fixture_manifest()
    path = root / ".harness" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def valid_plan(root: Path, manifest: dict) -> dict:
    return {
        "schemaVersion": 1,
        "source": {
            "manifestSha256": runtime_plan.manifest_sha256(root / ".harness" / "manifest.json"),
            "topologySha256": runtime_plan.topology_sha256(manifest),
        },
        "task": {
            "summary": "Prepare and review a contract change.",
            "completionCriteria": ["proposal produced", "review completed"],
            "criticality": "high",
        },
        "execution": {
            "class": "coordinated",
            "pattern": "producer-reviewer",
            "adapter": "runtime-probed",
            "capabilityPolicyRef": "direct-default",
            "retention": "ephemeral",
        },
        "participants": [
            {
                "agent": "api_producer",
                "runtimeRole": "producer",
                "boundaryRefs": ["api-contract"],
                "readScopes": ["contracts/api.schema"],
                "writeScopes": ["contracts/api.schema"],
                "isolation": "worktree",
            },
            {
                "agent": "contract_reviewer",
                "runtimeRole": "reviewer",
                "boundaryRefs": ["api-contract", "storage-contract"],
                "readScopes": ["contracts/generated/**"],
                "writeScopes": [],
                "isolation": "read-only",
            },
        ],
        "tasks": [
            {
                "id": "prepare-change",
                "owner": "api_producer",
                "dependsOn": [],
                "inputs": ["contracts/api.schema"],
                "outputs": ["change-proposal"],
                "required": True,
                "verification": ["schema-check"],
            },
            {
                "id": "review-change",
                "owner": "contract_reviewer",
                "dependsOn": ["prepare-change"],
                "inputs": ["change-proposal"],
                "outputs": ["review-findings"],
                "required": True,
                "verification": ["cross-contract-check"],
            },
        ],
        "communication": {
            "allowedTypes": sorted(harness_teamplay.MESSAGE_TYPES),
            "maxRounds": 2,
            "maxMessagesPerAgent": 8,
            "broadcastPolicy": "leader-only",
            "challengeRequiresEvidence": True,
        },
        "stopping": {
            "maxReassignments": 1,
            "failOnMissingRequiredArtifact": True,
            "failOnWriteScopeViolation": True,
            "failOnUnresolvedCriticalChallenge": True,
        },
        "retention": runtime_plan.default_retention(),
    }


def valid_packet() -> dict:
    return {
        "schemaVersion": harness_coordination.PACKET_SCHEMA_VERSION,
        "status": "complete",
        "taskId": "prepare-change",
        "participant": "api_producer",
        "summary": "Prepared the contract change.",
        "findings": [
            {
                "claim": "The generated contract must be reviewed.",
                "evidenceRefs": ["contracts/api.schema:1"],
                "severity": "medium",
                "affectedAgents": ["contract_reviewer"],
            }
        ],
        "challenges": [
            {
                "targetAgent": "contract_reviewer",
                "claim": "Review must include the generated contract.",
                "evidenceRefs": ["contracts/api.schema:1"],
                "requestedAction": "Check the generated contract boundary.",
            }
        ],
        "artifacts": ["change-proposal"],
        "changedPaths": ["contracts/api.schema"],
        "verification": ["schema-check"],
        "incompleteWork": [],
        "unresolvedRisks": [],
    }


class RuntimeFixtureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = write_manifest(self.root)
        self.plan = valid_plan(self.root, self.manifest)

    def validate(self, plan: dict | None = None) -> dict:
        return runtime_plan.validate_runtime_plan(self.root, plan or self.plan)


class TeamSelectionTests(unittest.TestCase):
    def test_direct_task_does_not_create_team(self) -> None:
        self.assertEqual(harness_teamplay.select_execution({"agentCount": 4})["class"], "direct")

    def test_two_agents_alone_do_not_select_coordinated(self) -> None:
        result = harness_teamplay.select_execution({"agentCount": 2})
        self.assertEqual(result, {"class": "direct", "pattern": None})

    def test_parallel_independent_tasks_use_delegation(self) -> None:
        result = harness_teamplay.select_execution({"agentCount": 3, "independentTasks": 3})
        self.assertEqual(result, {"class": "delegated", "pattern": "fan-out/fan-in"})

    def test_repeated_cross_boundary_negotiation_selects_coordinated(self) -> None:
        result = harness_teamplay.select_execution(
            {"agentCount": 2, "crossBoundaryAgreement": True}
        )
        self.assertEqual(result["class"], "coordinated")

    def test_single_review_pass_uses_delegated_producer_reviewer(self) -> None:
        result = harness_teamplay.select_execution({"agentCount": 2, "reviewPasses": 1})
        self.assertEqual(result, {"class": "delegated", "pattern": "producer-reviewer"})


class RuntimePlanValidationTests(RuntimeFixtureTestCase):
    def test_runtime_plan_is_bound_to_manifest_hash(self) -> None:
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["retention"], "ephemeral")

    def test_runtime_plan_cli_is_machine_readable_and_no_write(self) -> None:
        plan_path = self.root / "runtime-plan.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        manifest_path = self.root / ".harness" / "manifest.json"
        before = manifest_path.read_bytes()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "validate_runtime_plan.py"),
                "--root",
                str(self.root),
                "--plan",
                str(plan_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["valid"])
        self.assertEqual(before, manifest_path.read_bytes())

    def test_stale_runtime_plan_is_rejected(self) -> None:
        self.plan["source"]["manifestSha256"] = "f" * 64
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "stale"):
            self.validate()

    def test_runtime_plan_references_only_known_agents(self) -> None:
        self.plan["participants"][0]["agent"] = "unknown_agent"
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "unknown persistent agent"):
            self.validate()

    def test_runtime_role_is_not_persisted_as_agent(self) -> None:
        before = (self.root / ".harness" / "manifest.json").read_bytes()
        self.validate()
        after = (self.root / ".harness" / "manifest.json").read_bytes()
        self.assertEqual(before, after)
        self.assertTrue(
            all("runtimeRole" not in agent for agent in self.manifest["topology"]["agents"])
        )

    def test_runtime_plan_dependency_graph_is_acyclic(self) -> None:
        self.plan["tasks"][0]["dependsOn"] = ["review-change"]
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "acyclic"):
            self.validate()

    def test_every_required_output_has_an_owner(self) -> None:
        self.plan["tasks"][1]["outputs"] = ["change-proposal"]
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "more than one owner"):
            self.validate()

    def test_required_task_requires_verification(self) -> None:
        self.plan["tasks"][0]["verification"] = []
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "needs an output and verification"):
            self.validate()

    def test_coordinated_plan_requires_finite_round_budget(self) -> None:
        self.plan["communication"]["maxRounds"] = 0
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "positive communication budgets"):
            self.validate()

    def test_coordinated_plan_requires_stopping_condition(self) -> None:
        self.plan["stopping"]["failOnUnresolvedCriticalChallenge"] = False
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "must be true"):
            self.validate()


class ScopeAndWorktreeTests(RuntimeFixtureTestCase):
    def _make_second_writer(self) -> None:
        self.plan["participants"][0]["writeScopes"] = ["contracts/**"]
        reviewer = self.plan["participants"][1]
        reviewer["runtimeRole"] = "integrator"
        reviewer["writeScopes"] = ["contracts/generated/**"]
        reviewer["isolation"] = "worktree"

    def test_team_message_cannot_expand_write_scope(self) -> None:
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "cannot expand write scope"):
            runtime_plan.validate_message(
                {
                    "type": "request",
                    "taskId": "review-change",
                    "from": "contract_reviewer",
                    "to": "api_producer",
                    "round": 1,
                    "requestedAction": "Edit storage.",
                    "writeScopes": ["contracts/storage.schema"],
                },
                participants={"api_producer", "contract_reviewer"},
                task_ids={"prepare-change", "review-change"},
                leader="api_producer",
                max_rounds=2,
            )

    def test_concurrent_writer_overlap_is_rejected(self) -> None:
        self._make_second_writer()
        self.plan["tasks"][1]["dependsOn"] = []
        self.plan["tasks"][1]["inputs"] = ["contracts/generated/**"]
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "concurrent runtime writers"):
            self.validate()

    def test_ordered_overlap_requires_complete_handoff_scope(self) -> None:
        self._make_second_writer()
        self.plan["handoffs"] = [
            {
                "fromTask": "prepare-change",
                "toTask": "review-change",
                "scope": "contracts/generated/narrow/**",
                "frozenSha256": "a" * 64,
                "verification": "Verify the frozen hash.",
            }
        ]
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "complete verified handoff"):
            self.validate()

    def test_reviewer_is_read_only(self) -> None:
        self.plan["participants"][1]["writeScopes"] = ["contracts/generated/**"]
        self.plan["participants"][1]["isolation"] = "worktree"
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "read-only"):
            self.validate()

    def test_writer_requires_isolated_worktree_or_equivalent(self) -> None:
        del self.plan["participants"][0]["isolation"]
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "isolated worktree"):
            self.validate()

    def test_frozen_input_change_invalidates_downstream_validation(self) -> None:
        handoff = {"frozenSha256": "a" * 64}
        self.assertTrue(runtime_plan.frozen_handoff_is_current(handoff, "a" * 64))
        self.assertFalse(runtime_plan.frozen_handoff_is_current(handoff, "b" * 64))


class CommunicationTests(RuntimeFixtureTestCase):
    def _challenge(self) -> dict:
        return {
            "type": "challenge",
            "taskId": "review-change",
            "from": "contract_reviewer",
            "to": "api_producer",
            "round": 1,
            "claim": "The contracts conflict.",
            "evidenceRefs": ["contracts/api.schema:1"],
            "affectedScopes": ["contracts/api.schema"],
            "requestedAction": "Resolve the field mismatch.",
        }

    def _validate_message(self, message: dict, *, leader: str = "api_producer") -> dict:
        return runtime_plan.validate_message(
            message,
            participants={"api_producer", "contract_reviewer"},
            task_ids={"prepare-change", "review-change"},
            leader=leader,
            max_rounds=2,
        )

    def test_challenge_requires_evidence(self) -> None:
        message = self._challenge()
        message["evidenceRefs"] = []
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "must not be empty"):
            self._validate_message(message)

    def test_challenge_requires_requested_action(self) -> None:
        message = self._challenge()
        del message["requestedAction"]
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "requestedAction"):
            self._validate_message(message)

    def test_broadcast_is_leader_only(self) -> None:
        message = self._challenge()
        message["to"] = "broadcast"
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "leader-only"):
            self._validate_message(message, leader="api_producer")

    def test_message_budget_is_enforced(self) -> None:
        messages = [self._challenge(), self._challenge()]
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "maxMessagesPerAgent"):
            runtime_plan.validate_message_batch(
                messages,
                participants={"api_producer", "contract_reviewer"},
                task_ids={"prepare-change", "review-change"},
                leader="api_producer",
                max_rounds=2,
                max_messages_per_agent=1,
            )

    def test_reassignment_budget_is_enforced(self) -> None:
        self.plan["stopping"]["maxReassignments"] = 4
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "at most 3"):
            self.validate()

    def test_complete_message_requires_artifact_and_verification(self) -> None:
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "artifacts"):
            self._validate_message(
                {
                    "type": "complete",
                    "taskId": "prepare-change",
                    "from": "api_producer",
                    "to": "contract_reviewer",
                    "round": 1,
                    "artifacts": [],
                    "verification": ["schema-check"],
                    "incomplete": [],
                    "unresolvedRisks": [],
                    "frozenSha256": "a" * 64,
                }
            )


class CoordinationPacketTests(RuntimeFixtureTestCase):
    def _validate_packet(self, packet: dict | None = None) -> dict:
        self.validate()
        return harness_coordination.validate_coordination_packet(
            packet or valid_packet(),
            participants=harness_coordination.participant_map(self.plan),
            tasks=harness_coordination.task_map(self.plan),
        )

    def test_complete_packet_is_valid_but_not_live_execution_proof(self) -> None:
        report = self._validate_packet()
        self.assertTrue(report["valid"])
        self.assertFalse(report["provesLiveSubagentExecution"])
        self.assertEqual(report["findingCount"], 1)
        self.assertEqual(report["challengeCount"], 1)

    def test_packet_participant_must_own_task(self) -> None:
        packet = valid_packet()
        packet["participant"] = "contract_reviewer"
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "does not own"
        ):
            self._validate_packet(packet)

    def test_finding_requires_evidence(self) -> None:
        packet = valid_packet()
        packet["findings"][0]["evidenceRefs"] = []
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "must not be empty"
        ):
            self._validate_packet(packet)

    def test_finding_names_known_affected_agents(self) -> None:
        packet = valid_packet()
        packet["findings"][0]["affectedAgents"] = ["unknown_agent"]
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "unknown participants"
        ):
            self._validate_packet(packet)

    def test_challenge_targets_another_known_agent(self) -> None:
        packet = valid_packet()
        packet["challenges"][0]["targetAgent"] = "api_producer"
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "another participant"
        ):
            self._validate_packet(packet)

    def test_changed_path_must_stay_inside_write_scope(self) -> None:
        packet = valid_packet()
        packet["changedPaths"] = ["contracts/storage.schema"]
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "exceeds"
        ):
            self._validate_packet(packet)

    def test_read_only_participant_cannot_report_changed_path(self) -> None:
        packet = valid_packet()
        packet.update(
            {
                "taskId": "review-change",
                "participant": "contract_reviewer",
                "artifacts": ["review-findings"],
                "changedPaths": ["contracts/generated/review.md"],
            }
        )
        packet["challenges"][0]["targetAgent"] = "api_producer"
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "exceeds"
        ):
            self._validate_packet(packet)

    def test_complete_packet_requires_outputs_and_verification(self) -> None:
        packet = valid_packet()
        packet["artifacts"] = []
        packet["verification"] = []
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "requires verification"
        ):
            self._validate_packet(packet)

    def test_complete_packet_accounts_for_declared_verification(self) -> None:
        packet = valid_packet()
        packet["verification"] = ["unrelated-check"]
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError,
            "missing required task verification",
        ):
            self._validate_packet(packet)

    def test_noncomplete_packet_describes_incomplete_work(self) -> None:
        packet = valid_packet()
        packet["status"] = "partial"
        with self.assertRaisesRegex(
            harness_coordination.CoordinationPacketError, "must describe incomplete work"
        ):
            self._validate_packet(packet)

    def test_packet_cli_is_machine_readable_and_no_write(self) -> None:
        plan_path = self.root / "runtime-plan.json"
        packet_path = self.root / "coordination-packet.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        packet_path.write_text(json.dumps(valid_packet()), encoding="utf-8")
        manifest_path = self.root / ".harness" / "manifest.json"
        before = manifest_path.read_bytes()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "validate_coordination_packet.py"),
                "--root",
                str(self.root),
                "--plan",
                str(plan_path),
                "--packet",
                str(packet_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["valid"])
        self.assertFalse(report["provesLiveSubagentExecution"])
        self.assertEqual(before, manifest_path.read_bytes())


class CapabilityFallbackTests(unittest.TestCase):
    def test_parallel_delegation_uses_codex_parent_relay(self) -> None:
        result = harness_teamplay.select_adapter(
            "coordinated", {"parallel-delegation", "shared-task-state"}
        )
        self.assertEqual(result["adapter"], "codex-subagent-relay")
        self.assertEqual(result["communication"], "parent-relay")
        self.assertEqual(result["taskControl"], "parent")
        self.assertFalse(result["fallbackUsed"])

    def test_peer_capabilities_do_not_enable_unverified_direct_p2p(self) -> None:
        result = harness_teamplay.select_adapter(
            "coordinated",
            {"parallel-delegation", "peer-messaging", "shared-task-state"},
        )
        self.assertEqual(result["adapter"], "codex-subagent-relay")
        self.assertEqual(result["communication"], "parent-relay")

    def test_missing_subagent_delegation_uses_sequential_relay(self) -> None:
        result = harness_teamplay.select_adapter("coordinated", set())
        self.assertEqual(result["adapter"], "sequential-relay")
        self.assertTrue(result["fallbackUsed"])

    def test_legacy_parallel_delegation_alias_is_normalized(self) -> None:
        result = harness_teamplay.select_adapter(
            "coordinated", {"parallel-subagent-delegation"}
        )
        self.assertEqual(result["adapter"], "codex-subagent-relay")
        self.assertFalse(result["fallbackUsed"])

    def test_unknown_capability_is_rejected(self) -> None:
        with self.assertRaisesRegex(harness_teamplay.TeamplayError, "not registered"):
            harness_teamplay.select_adapter("coordinated", {"imaginary-runtime"})

    def test_fallback_preserves_input_output_verification(self) -> None:
        result = harness_teamplay.select_adapter("coordinated", set())
        self.assertEqual(set(result["preserves"]), {"input", "output", "verification"})

    def test_runtime_specific_tool_syntax_is_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = write_manifest(root)
            plan = valid_plan(root, manifest)
            plan["task"]["summary"] = "Use TeamCreate for this task."
            with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "runtime-specific tool"):
                runtime_plan.validate_runtime_plan(root, plan)


class RetentionAndPrivacyTests(RuntimeFixtureTestCase):
    def test_ephemeral_workspace_is_default(self) -> None:
        self.assertEqual(runtime_plan.default_retention(), self.plan["retention"])

    def test_full_audit_requires_explicit_opt_in(self) -> None:
        self.plan["execution"]["retention"] = "full-audit"
        self.plan["retention"] = {
            "mode": "full-audit",
            "storeRawMessages": True,
            "storeRawArtifacts": True,
            "storeHashes": True,
            "explicitUserOptIn": False,
            "storageLocation": "runtime-selected",
            "retentionDuration": "one day",
            "purgeMethod": "explicit purge",
        }
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "explicit user opt-in"):
            self.validate()

    def test_redacted_retention_omits_raw_messages(self) -> None:
        self.plan["execution"]["retention"] = "redacted"
        self.plan["retention"]["mode"] = "redacted"
        self.plan["retention"]["storeRawMessages"] = True
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "cannot store raw"):
            self.validate()

    def test_runtime_plan_does_not_store_absolute_repository_path(self) -> None:
        self.plan["task"]["repositoryPath"] = str(self.root)
        with self.assertRaisesRegex(runtime_plan.RuntimePlanError, "absolute repository-path"):
            self.validate()

    def test_provisional_greenfield_team_is_not_persisted(self) -> None:
        before = (self.root / ".harness" / "manifest.json").read_bytes()
        self.plan["execution"]["evidenceStatus"] = "provisional"
        self.plan["execution"]["persistenceAllowed"] = False
        producer = self.plan["participants"][0]
        del producer["agent"]
        producer["runtimeParticipantId"] = "provisional-producer"
        self.plan["tasks"][0]["owner"] = "provisional-producer"
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(before, (self.root / ".harness" / "manifest.json").read_bytes())


class CompatibilityTests(RuntimeFixtureTestCase):
    def test_runtime_plan_does_not_modify_manifest(self) -> None:
        before = (self.root / ".harness" / "manifest.json").read_bytes()
        self.validate()
        self.assertEqual(before, (self.root / ".harness" / "manifest.json").read_bytes())

    def test_generation_plan_schema_remains_3(self) -> None:
        self.assertEqual(harness_metadata.PLAN_SCHEMA_VERSION, 3)

    def test_manifest_schema_remains_5(self) -> None:
        self.assertEqual(harness_metadata.MANIFEST_SCHEMA_VERSION, 5)

    def test_transaction_schema_remains_2(self) -> None:
        self.assertEqual(harness_metadata.TRANSACTION_SCHEMA_VERSION, 2)

    def test_evaluation_schema_remains_2(self) -> None:
        self.assertEqual(harness_metadata.EVALUATION_SCHEMA_VERSION, 2)

    def test_v60_to_v67_records_remain_readable(self) -> None:
        self.assertTrue({"6.0", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7"}.issubset(
            harness_metadata.READABLE_EVALUATION_VERSIONS
        ))

    def test_no_new_runtime_dependency(self) -> None:
        environment = (REPO_ROOT / "environment.yml").read_text(encoding="utf-8")
        dependency_lines = [
            line.strip()
            for line in environment.splitlines()
            if line.startswith("  - ")
        ]
        self.assertEqual(dependency_lines, ["- defaults", "- python=3.11"])


class DeterministicPlanBuilderTests(unittest.TestCase):
    def _draft(self, name: str = "minimal-plan.json") -> dict:
        plan = json.loads((REPO_ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))
        for artifact in plan["artifacts"]:
            if artifact["path"] == ".agents/skills/project-harness/SKILL.md":
                artifact["content"] = artifact["content"].replace(
                    harness_change_discipline.PROJECT_BLOCK,
                    harness_plan_builder.PROJECT_PLACEHOLDER,
                )
                artifact["content"] += (
                    "\n" + harness_plan_builder.PROJECT_TEAMPLAY_PLACEHOLDER + "\n"
                )
            elif artifact["path"].startswith(".codex/agents/"):
                artifact["content"] = artifact["content"].replace(
                    harness_change_discipline.WRITER_BLOCK,
                    harness_plan_builder.WRITER_PLACEHOLDER,
                )
                before, closing = artifact["content"].rsplit('"""', 1)
                artifact["content"] = (
                    before
                    + "\n"
                    + harness_plan_builder.AGENT_TEAMPLAY_PLACEHOLDER
                    + "\n\"\"\""
                    + closing
                )
        return plan

    def test_builder_materializes_schema3_plan_before_apply(self) -> None:
        draft = self._draft()
        materialized = harness_plan_builder.materialize_plan(draft)
        self.assertEqual(materialized["schemaVersion"], 3)
        self.assertNotIn(harness_plan_builder.PROJECT_PLACEHOLDER, json.dumps(materialized))
        self.assertNotIn(
            harness_plan_builder.PROJECT_TEAMPLAY_PLACEHOLDER, json.dumps(materialized)
        )
        project = next(
            item["content"]
            for item in materialized["artifacts"]
            if item["path"] == ".agents/skills/project-harness/SKILL.md"
        )
        self.assertEqual(project.count(harness_teamplay.PROJECT_BLOCK), 1)
        application = harness_apply.build_application(
            REPO_ROOT / "tests" / "fixtures" / "minimal-project", materialized
        )
        self.assertTrue(application["report"]["valid"])

    def test_installed_minimal_draft_example_is_self_contained(self) -> None:
        example = json.loads(
            (REPO_ROOT / ".agents" / "skills" / "harness" / "references" / "minimal-draft-plan.json").read_text(
                encoding="utf-8"
            )
        )
        materialized = harness_plan_builder.materialize_plan(example)
        application = harness_apply.build_application(
            REPO_ROOT / "tests" / "fixtures" / "minimal-project", materialized
        )
        self.assertTrue(application["report"]["valid"])

    def test_builder_materializes_every_writer_contract(self) -> None:
        materialized = harness_plan_builder.materialize_plan(
            self._draft("coordinated-cross-contract-plan.json")
        )
        writer_contents = [
            item["content"]
            for item in materialized["artifacts"]
            if item["path"].startswith(".codex/agents/")
        ]
        self.assertEqual(len(writer_contents), 2)
        self.assertTrue(
            all(harness_change_discipline.WRITER_BLOCK in content for content in writer_contents)
        )
        self.assertTrue(all(harness_teamplay.AGENT_BLOCK in content for content in writer_contents))

    def test_builder_canonicalizes_registered_capability_aliases(self) -> None:
        draft = self._draft()
        policy = draft["capabilityPolicies"][0]
        policy.update(
            {
                "semanticMode": "deterministic-orchestration",
                "requiredCapabilities": ["parallel-subagent-delegation"],
                "preferredRuntimeMapping": "runtime-native",
                "probe": {"mode": "runtime-check"},
                "fallback": {
                    "semanticMode": "deterministic-orchestration",
                    "implementation": "Use sequential parent relay.",
                    "preserves": ["input", "output", "verification"],
                },
            }
        )

        materialized = harness_plan_builder.materialize_plan(draft)

        self.assertEqual(
            materialized["capabilityPolicies"][0]["requiredCapabilities"],
            ["parallel-delegation"],
        )
        harness_topology.validate_contract(
            materialized["topology"], materialized["capabilityPolicies"]
        )

    def test_builder_rejects_unregistered_capability(self) -> None:
        draft = self._draft()
        draft["capabilityPolicies"][0]["requiredCapabilities"] = ["imaginary-runtime"]
        with self.assertRaisesRegex(harness_plan_builder.PlanBuilderError, "not registered"):
            harness_plan_builder.materialize_plan(draft)

    def test_materialized_plan_rejects_capability_aliases(self) -> None:
        draft = self._draft()
        draft["capabilityPolicies"][0]["requiredCapabilities"] = [
            "parallel-subagent-delegation"
        ]
        with self.assertRaisesRegex(harness_topology.TopologyError, "is an alias"):
            harness_topology.validate_contract(
                draft["topology"], draft["capabilityPolicies"]
            )

    def test_missing_project_teamplay_placeholder_is_rejected(self) -> None:
        draft = self._draft()
        project = next(
            item
            for item in draft["artifacts"]
            if item["path"] == ".agents/skills/project-harness/SKILL.md"
        )
        project["content"] = project["content"].replace(
            harness_plan_builder.PROJECT_TEAMPLAY_PLACEHOLDER, ""
        )
        with self.assertRaisesRegex(harness_plan_builder.PlanBuilderError, "exactly once"):
            harness_plan_builder.materialize_plan(draft)

    def test_duplicate_agent_teamplay_placeholder_is_rejected(self) -> None:
        draft = self._draft("coordinated-cross-contract-plan.json")
        agent = next(
            item for item in draft["artifacts"] if item["path"].startswith(".codex/agents/")
        )
        agent["content"] += harness_plan_builder.AGENT_TEAMPLAY_PLACEHOLDER
        with self.assertRaisesRegex(harness_plan_builder.PlanBuilderError, "exactly once"):
            harness_plan_builder.materialize_plan(draft)

    def test_missing_project_placeholder_is_rejected(self) -> None:
        draft = self._draft()
        draft["artifacts"][-1]["content"] = "missing"
        with self.assertRaisesRegex(harness_plan_builder.PlanBuilderError, "exactly once"):
            harness_plan_builder.materialize_plan(draft)

    def test_duplicate_writer_placeholder_is_rejected(self) -> None:
        draft = self._draft("coordinated-cross-contract-plan.json")
        writer = next(
            item for item in draft["artifacts"] if item["path"].startswith(".codex/agents/")
        )
        writer["content"] += harness_plan_builder.WRITER_PLACEHOLDER
        with self.assertRaisesRegex(harness_plan_builder.PlanBuilderError, "exactly once"):
            harness_plan_builder.materialize_plan(draft)

    def test_placeholder_in_unowned_artifact_is_rejected(self) -> None:
        draft = self._draft()
        draft["artifacts"].append(
            {
                "path": ".agents/skills/helper/reference.md",
                "mode": "0644",
                "content": harness_plan_builder.PROJECT_PLACEHOLDER,
            }
        )
        with self.assertRaisesRegex(harness_plan_builder.PlanBuilderError, "unsupported artifact"):
            harness_plan_builder.materialize_plan(draft)

    def test_builder_cli_writes_only_the_requested_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "draft.json"
            output = root / "plan.json"
            source.write_text(json.dumps(self._draft()), encoding="utf-8")
            before = source.read_bytes()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "harness_plan_builder.py"),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["schemaVersion"], 3)


def successful_runtime_jsonl(participants: list[str]) -> list[str]:
    events: list[dict] = [{"type": "thread.started", "thread_id": "parent-thread"}]
    for index, participant in enumerate(participants):
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
                    "prompt": "sensitive task text",
                    "agents_states": {
                        child: {"status": "running", "message": "sensitive child text"}
                    },
                },
            }
        )
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "type": "collab_tool_call",
                    "tool": "wait",
                    "status": "completed",
                    "sender_thread_id": "parent-thread",
                    "receiver_thread_ids": [child],
                    "prompt": None,
                    "agents_states": {
                        child: {"status": "completed", "message": "sensitive result"}
                    },
                },
            }
        )
    events.append(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 50,
                "output_tokens": 20,
            },
        }
    )
    return [json.dumps(event) for event in events]


def runtime_observation(
    participants: list[str], *, wait_attempts: int = 1, wait_time_ms: int = 10
) -> dict:
    return {
        "schemaVersion": 1,
        "source": "local-session-observer",
        "parentThreadId": "parent-thread",
        "children": [
            {
                "participant": participant,
                "childThreadId": f"child-{index}",
                "parentThreadId": "parent-thread",
                "threadSource": "subagent",
                "agentRole": participant,
                "waitAttempts": wait_attempts,
                "waitTimeMs": wait_time_ms,
            }
            for index, participant in enumerate(participants)
        ],
    }


class LegacyRuntimeReceiptTests(RuntimeFixtureTestCase):
    def _build(self, lines: list[str], **overrides: object) -> dict:
        participants = [item["agent"] for item in self.plan["participants"]]
        values = {
            "plan": self.plan,
            "lines": lines,
            "observation_bindings": runtime_observation(participants),
            "codex_cli_version": "0.152.1",
            "execution_mode": "persistent",
            "repository_id": "repo-" + "b" * 16,
            "harness_commit": "a" * 40,
            "salt": b"runtime-receipt-salt",
            "fallbacks": None,
        }
        values.update(overrides)
        return harness_runtime_receipt_schema1.build_runtime_receipt(**values)

    def test_complete_runtime_chain_proves_observation_not_truth_beyond_events(self) -> None:
        participants = [item["agent"] for item in self.plan["participants"]]
        receipt = self._build(successful_runtime_jsonl(participants))
        self.assertEqual(receipt["captureCompleteness"], "complete")
        self.assertEqual(receipt["evidenceStrength"], "cross-validated-runtime")
        self.assertTrue(receipt["provesLiveSubagentExecution"])
        self.assertTrue(all(item["completed"] for item in receipt["agents"]))
        self.assertNotIn("parent-thread", json.dumps(receipt))
        self.assertNotIn("child-0", json.dumps(receipt))

    def test_missing_child_id_blocks_wait_eligibility(self) -> None:
        participant = self.plan["participants"][0]["agent"]
        receipt = self._build(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "collab_tool_call",
                            "tool": "spawn_agent",
                            "status": "completed",
                            "sender_thread_id": "parent-thread",
                            "receiver_thread_ids": [],
                            "agents_states": {},
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
        state = receipt["agents"][0]
        self.assertFalse(state["spawned"])
        self.assertIn("missing-child-id", state["failureCodes"])
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_role_mismatch_fails_closed(self) -> None:
        participant = self.plan["participants"][0]["agent"]
        observation = runtime_observation(
            [item["agent"] for item in self.plan["participants"]]
        )
        observation["children"][0]["agentRole"] = "contract_reviewer"
        receipt = self._build(
            successful_runtime_jsonl([participant]), observation_bindings=observation
        )
        self.assertIn("role-mismatch", receipt["agents"][0]["failureCodes"])

    def test_empty_receiver_wait_is_recorded_as_blocked(self) -> None:
        participant = self.plan["participants"][0]["agent"]
        lines = successful_runtime_jsonl([participant])[:2]
        lines.append(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "collab_tool_call",
                        "tool": "wait",
                        "status": "completed",
                        "sender_thread_id": "parent-thread",
                        "receiver_thread_ids": [],
                        "agents_states": {},
                    },
                }
            )
        )
        receipt = self._build(lines)
        self.assertIn("empty-wait-blocked", receipt["agents"][0]["failureCodes"])

    def test_wait_budget_exhaustion_is_fail_closed(self) -> None:
        participant = self.plan["participants"][0]["agent"]
        events = [json.loads(line) for line in successful_runtime_jsonl([participant])[:2]]
        for _ in range(harness_runtime_receipt.MAX_WAIT_ATTEMPTS_PER_AGENT + 1):
            events.append(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "collab_tool_call",
                        "tool": "wait",
                        "status": "completed",
                        "sender_thread_id": "parent-thread",
                        "receiver_thread_ids": ["child-0"],
                        "agents_states": {"child-0": {"status": "running", "message": None}},
                    },
                }
            )
        receipt = self._build(
            [json.dumps(event) for event in events],
            observation_bindings=runtime_observation(
                [item["agent"] for item in self.plan["participants"]],
                wait_attempts=harness_runtime_receipt.MAX_WAIT_ATTEMPTS_PER_AGENT + 1,
            ),
        )
        self.assertIn("wait-budget-exhausted", receipt["agents"][0]["failureCodes"])

    def test_unsupported_cli_version_cannot_claim_observation(self) -> None:
        participants = [item["agent"] for item in self.plan["participants"]]
        receipt = self._build(
            successful_runtime_jsonl(participants), codex_cli_version="0.153.0"
        )
        self.assertEqual(receipt["parser"]["compatibility"], "unsupported")
        self.assertFalse(receipt["provesLiveSubagentExecution"])
        self.assertTrue(all(not item["observed"] for item in receipt["agents"]))

    def test_known_public_stream_omission_fails_closed(self) -> None:
        receipt = self._build(
            [
                json.dumps({"type": "thread.started", "thread_id": "parent-thread"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "collab_tool_call",
                            "tool": "wait",
                            "sender_thread_id": "parent-thread",
                            "receiver_thread_ids": [],
                            "prompt": None,
                            "agents_states": {},
                            "status": "completed",
                        },
                    }
                ),
                json.dumps({"type": "turn.completed"}),
            ]
        )
        self.assertEqual(receipt["runtime"]["emptyWaitCount"], 1)
        self.assertTrue(all(not item["spawned"] for item in receipt["agents"]))
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_missing_observation_binding_cannot_map_role_or_claim_live(self) -> None:
        participants = [item["agent"] for item in self.plan["participants"]]
        receipt = self._build(
            successful_runtime_jsonl(participants), observation_bindings=None
        )
        self.assertTrue(
            all(
                "missing-observation-binding" in item["failureCodes"]
                for item in receipt["agents"]
            )
        )
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_prompt_and_agent_message_do_not_change_event_fingerprints(self) -> None:
        participants = [item["agent"] for item in self.plan["participants"]]
        baseline_lines = successful_runtime_jsonl(participants)
        changed_events = [json.loads(line) for line in baseline_lines]
        for event in changed_events:
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "collab_tool_call":
                item["prompt"] = "different sensitive task"
                for state in item.get("agents_states", {}).values():
                    state["message"] = "different sensitive result"
        baseline = self._build(baseline_lines)
        changed = self._build([json.dumps(event) for event in changed_events])
        self.assertEqual(
            [item["spawnFingerprint"] for item in baseline["agents"]],
            [item["spawnFingerprint"] for item in changed["agents"]],
        )
        self.assertEqual(
            [item["completionFingerprint"] for item in baseline["agents"]],
            [item["completionFingerprint"] for item in changed["agents"]],
        )
        self.assertNotIn("sensitive", json.dumps(changed))

    def test_missing_parent_thread_prevents_live_execution_claim(self) -> None:
        participant = self.plan["participants"][0]["agent"]
        lines = successful_runtime_jsonl([participant])[1:]
        receipt = self._build(lines)
        self.assertTrue(receipt["agents"][0]["completed"])
        self.assertFalse(receipt["provesLiveSubagentExecution"])
        self.assertNotEqual(receipt["captureCompleteness"], "complete")

    def test_unknown_critical_event_fails_closed(self) -> None:
        receipt = self._build(
            [json.dumps({"type": "subagent.experimental", "thread_id": "secret"})]
        )
        self.assertEqual(receipt["parser"]["unknownCriticalEventCount"], 1)
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_contract_preserving_fallback_is_distinct_from_observation(self) -> None:
        participant = self.plan["participants"][0]["agent"]
        receipt = self._build(
            [json.dumps({"type": "turn.completed"})],
            fallbacks=[
                {
                    "participant": participant,
                    "adapter": "direct",
                    "preserves": ["input", "output", "verification"],
                    "reasonCode": "subagent-unavailable",
                    "source": "agent-reported",
                }
            ],
        )
        state = receipt["agents"][0]
        self.assertTrue(state["fallback"])
        self.assertFalse(state["observed"])
        self.assertFalse(receipt["provesLiveSubagentExecution"])

    def test_completed_agent_cannot_also_claim_fallback(self) -> None:
        participant = self.plan["participants"][0]["agent"]
        with self.assertRaisesRegex(
            harness_runtime_receipt.RuntimeReceiptError, "completed participant"
        ):
            self._build(
                successful_runtime_jsonl([participant]),
                fallbacks=[
                    {
                        "participant": participant,
                        "adapter": "direct",
                        "preserves": ["input", "output", "verification"],
                        "reasonCode": "unexpected",
                        "source": "agent-reported",
                    }
                ],
            )

    def test_receipt_hash_detects_tampering(self) -> None:
        participants = [item["agent"] for item in self.plan["participants"]]
        receipt = self._build(successful_runtime_jsonl(participants))
        receipt["measurements"]["inputTokens"] = 999
        with self.assertRaisesRegex(harness_runtime_receipt.RuntimeReceiptError, "hash"):
            harness_runtime_receipt.validate_runtime_receipt(receipt)

    def test_privacy_forbidden_field_is_rejected(self) -> None:
        participants = [item["agent"] for item in self.plan["participants"]]
        receipt = self._build(successful_runtime_jsonl(participants))
        receipt["rawPrompt"] = "secret"
        with self.assertRaisesRegex(harness_runtime_receipt.RuntimeReceiptError, "privacy-forbidden"):
            harness_runtime_receipt.validate_runtime_receipt(receipt)

    def test_schema1_cli_is_validation_only_and_preserves_repository_state(self) -> None:
        manifest_path = self.root / ".harness" / "manifest.json"
        before = manifest_path.read_bytes()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "harness_runtime_receipt_schema1.py"),
                "--receipt",
                str(REPO_ROOT / "tests" / "fixtures" / "runtime-receipt-schema1-golden.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertTrue(json.loads(completed.stdout)["valid"])
        self.assertEqual(before, manifest_path.read_bytes())


def valid_relay_receipt(plan: dict) -> dict:
    first_hash = "a" * 64
    second_hash = "b" * 64
    return harness_relay_receipt.seal_relay_receipt({
        "schemaVersion": harness_relay_receipt.RELAY_RECEIPT_SCHEMA_VERSION,
        "runtimePlanSha256": harness_relay_receipt.sha256(plan),
        "packetRevisions": [
            {"revision": 0, "packetSha256": first_hash, "affectedAgents": []},
            {
                "revision": 1,
                "packetSha256": second_hash,
                "affectedAgents": ["contract_reviewer"],
            },
        ],
        "reviews": [
            {
                "reviewId": "review-r0",
                "taskId": "review-change",
                "participant": "contract_reviewer",
                "revision": 0,
                "inputPacketSha256": first_hash,
                "reviewSha256": "c" * 64,
                "status": "changes-requested",
            },
            {
                "reviewId": "review-r1",
                "taskId": "review-change",
                "participant": "contract_reviewer",
                "revision": 1,
                "inputPacketSha256": second_hash,
                "reviewSha256": "d" * 64,
                "status": "accepted",
            },
        ],
        "reruns": [{"revision": 1, "agents": ["contract_reviewer"]}],
        "integration": {
            "packetSha256": second_hash,
            "reviewIds": ["review-r1"],
            "verdict": "accept",
        },
    })


class RelayReceiptTests(RuntimeFixtureTestCase):
    def test_review_receipt_preserves_coordination_packet_schema1(self) -> None:
        report = harness_relay_receipt.validate_relay_receipt(
            valid_relay_receipt(self.plan), plan=self.plan
        )
        self.assertTrue(report["valid"])
        self.assertEqual(harness_coordination.PACKET_SCHEMA_VERSION, 1)
        self.assertFalse(report["provesLiveSubagentExecution"])

    def test_review_must_echo_the_exact_input_packet_hash(self) -> None:
        receipt = valid_relay_receipt(self.plan)
        receipt["reviews"][1]["inputPacketSha256"] = "e" * 64
        with self.assertRaisesRegex(harness_relay_receipt.RelayReceiptError, "echo"):
            harness_relay_receipt.validate_relay_receipt(receipt, plan=self.plan)

    def test_stale_review_cannot_support_final_integration(self) -> None:
        receipt = valid_relay_receipt(self.plan)
        receipt["integration"]["reviewIds"] = ["review-r0"]
        with self.assertRaisesRegex(harness_relay_receipt.RelayReceiptError, "stale"):
            harness_relay_receipt.validate_relay_receipt(receipt, plan=self.plan)

    def test_unaffected_agent_rerun_is_rejected(self) -> None:
        receipt = valid_relay_receipt(self.plan)
        receipt["reruns"][0]["agents"].append("api_producer")
        with self.assertRaisesRegex(harness_relay_receipt.RelayReceiptError, "unaffected"):
            harness_relay_receipt.validate_relay_receipt(receipt, plan=self.plan)

    def test_missing_affected_agent_rerun_is_rejected(self) -> None:
        receipt = valid_relay_receipt(self.plan)
        receipt["reruns"][0]["agents"] = []
        with self.assertRaisesRegex(harness_relay_receipt.RelayReceiptError, "omits"):
            harness_relay_receipt.validate_relay_receipt(receipt, plan=self.plan)

    def test_relay_receipt_hash_detects_tampering(self) -> None:
        receipt = valid_relay_receipt(self.plan)
        receipt["integration"]["verdict"] = "reject"
        with self.assertRaisesRegex(harness_relay_receipt.RelayReceiptError, "hash"):
            harness_relay_receipt.validate_relay_receipt(receipt, plan=self.plan)

    def test_revision_count_cannot_exceed_plan_round_budget(self) -> None:
        receipt = valid_relay_receipt(self.plan)
        unsigned = dict(receipt)
        unsigned.pop("integrity")
        unsigned["packetRevisions"].append(
            {"revision": 2, "packetSha256": "e" * 64, "affectedAgents": []}
        )
        unsigned["packetRevisions"].append(
            {"revision": 3, "packetSha256": "f" * 64, "affectedAgents": []}
        )
        unsigned["reruns"].extend(
            [{"revision": 2, "agents": []}, {"revision": 3, "agents": []}]
        )
        unsigned["integration"]["packetSha256"] = "f" * 64
        receipt = harness_relay_receipt.seal_relay_receipt(unsigned)
        with self.assertRaisesRegex(harness_relay_receipt.RelayReceiptError, "round budget"):
            harness_relay_receipt.validate_relay_receipt(receipt, plan=self.plan)

    def test_accept_verdict_requires_accepted_review(self) -> None:
        receipt = valid_relay_receipt(self.plan)
        unsigned = dict(receipt)
        unsigned.pop("integrity")
        unsigned["reviews"][1]["status"] = "changes-requested"
        receipt = harness_relay_receipt.seal_relay_receipt(unsigned)
        with self.assertRaisesRegex(harness_relay_receipt.RelayReceiptError, "accepted cited"):
            harness_relay_receipt.validate_relay_receipt(receipt, plan=self.plan)

    def test_relay_receipt_cli_seals_without_repository_write(self) -> None:
        plan_path = self.root / "runtime-plan.json"
        draft_path = self.root / "relay-draft.json"
        output_path = self.root / "relay-receipt.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        draft = valid_relay_receipt(self.plan)
        draft.pop("integrity")
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        manifest_path = self.root / ".harness" / "manifest.json"
        before = manifest_path.read_bytes()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "harness_relay_receipt.py"),
                "--root",
                str(self.root),
                "--plan",
                str(plan_path),
                "--receipt",
                str(draft_path),
                "--seal",
                "--output",
                str(output_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        sealed = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertIn("integrity", sealed)
        self.assertTrue(harness_relay_receipt.validate_relay_receipt(sealed, plan=self.plan)["valid"])
        self.assertEqual(before, manifest_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
