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
import harness_teamplay  # noqa: E402
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

    def test_v60_to_v65_records_remain_readable(self) -> None:
        self.assertTrue({"6.0", "6.1", "6.2", "6.3", "6.4", "6.5"}.issubset(
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


if __name__ == "__main__":
    unittest.main()
