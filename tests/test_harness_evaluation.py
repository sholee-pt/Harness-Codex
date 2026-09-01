from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "evaluation"
sys.path.insert(0, str(SCRIPTS))

import harness_eval  # noqa: E402
import harness_eval_capture as capture  # noqa: E402
import harness_eval_compare as compare  # noqa: E402
import harness_eval_propose as propose  # noqa: E402
import harness_eval_store as store_module  # noqa: E402
import harness_eval_types as types  # noqa: E402
import harness_eval_schema2 as schema2  # noqa: E402
import harness_eval_view as evaluation_view  # noqa: E402
import harness_patch_scope  # noqa: E402


FIXED_TIME = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
HASH = "1" * 64


def uuid_text(number: int) -> str:
    return str(uuid.UUID(int=number))


def manual_record(
    repository_id: str,
    run_id: str,
    *,
    arm: str = "unpaired",
    verification: str = "passed",
    output_tokens: int = 10,
    critical_failure: bool = False,
) -> dict:
    record = capture.base_record(
        run_id=run_id,
        repository_id=repository_id,
        task_instance_id=uuid_text(100 + int(uuid.UUID(run_id))),
        started_at="2026-08-31T12:00:00Z",
        capture_mode="manual",
        prompt_fingerprint=HASH,
        source_snapshot_id="git:" + "2" * 40,
        manifest_sha256=HASH,
        topology_sha256=HASH,
        arm=arm,
        category="test",
        classification_source="fixture",
        sandbox="read-only",
        model_ref="model:" + "3" * 32,
        reasoning_effort="minimal",
        configured_execution_class="direct",
        pair_id=uuid_text(500) if arm != "unpaired" else None,
        comparison_id=uuid_text(501) if arm != "unpaired" else None,
        arm_order="first" if arm == "baseline" else "second" if arm == "harness" else "unpaired",
    )
    record["recordState"] = "completed"
    record["timestamps"]["endedAt"] = "2026-08-31T12:01:00Z"
    record["outcome"]["completion"] = "completed"
    record["outcome"]["criticalFailure"] = critical_failure
    record["outcome"]["verification"] = [
        {
            "checkRef": "check:" + "4" * 32,
            "profileFingerprint": HASH,
            "kind": "unit-test",
            "result": verification,
            "exitCode": types.measurement(
                0 if verification == "passed" else 1,
                unit="exit-code",
                state="measured",
                source="verification-runner",
                fidelity="exact",
                completeness="complete",
            ),
        }
    ]
    record["measurements"]["outputTokens"] = types.measurement(
        output_tokens,
        unit="tokens",
        state="measured",
        source="user-annotation",
        fidelity="reported",
        completeness="complete",
    )
    if arm != "unpaired":
        record["comparison"]["isolationStatus"] = "complete"
        declared = record["configuration"]["declaredConfiguration"]
        declared["route"] = schema2.reference_set([], state="measured", source="run-configuration-snapshot", fidelity="exact", completeness="complete")
        declared["agents"] = schema2.reference_set(
            [] if arm == "baseline" else ["agent:" + "5" * 32],
            state="measured",
            source="run-configuration-snapshot",
            fidelity="exact",
            completeness="complete",
        )
        declared["skills"] = schema2.reference_set([], state="measured", source="run-configuration-snapshot", fidelity="exact", completeness="complete")
        declared["qualityPolicies"] = schema2.reference_set([], state="measured", source="run-configuration-snapshot", fidelity="exact", completeness="complete")
        declared["independentReview"] = schema2.value_observation(False, state="measured", source="run-configuration-snapshot", fidelity="exact", completeness="complete")
        for key in ("changeDisciplineVersion", "projectHarnessFingerprint"):
            declared[key] = schema2.value_observation(None, state="not-applicable", source="none", fidelity="unknown", completeness="not-applicable")
        declared["bundleFingerprint"] = schema2.value_observation(
            HASH if arm == "baseline" else "2" * 64,
            state="measured",
            source="run-configuration-snapshot",
            fidelity="exact",
            completeness="complete",
        )
    record["result"]["verificationProfileFingerprint"] = HASH
    record["result"]["resultFingerprint"] = schema2.value_observation(
        HASH,
        state="measured",
        source="git-evaluator",
        fidelity="exact",
        completeness="complete",
    )
    return types.seal_record(record)


class MeasurementTests(unittest.TestCase):
    def test_annotation_correction_count_preserves_unavailable_and_zero(self) -> None:
        base = {
            "schemaVersion": 1,
            "annotationId": uuid_text(10),
            "runId": uuid_text(2),
            "createdAt": "2026-08-31T12:00:00Z",
            "source": "user",
            "acceptance": "accepted",
            "correctionCount": types.unavailable("count"),
            "reopened": False,
            "freeTextStored": False,
            "integrity": {"recordSha256": None},
        }
        types.validate_annotation(types.seal_record(base))
        measured_zero = copy.deepcopy(base)
        measured_zero["correctionCount"] = types.measurement(
            0,
            unit="count",
            state="measured",
            source="user-annotation",
            fidelity="reported",
            completeness="complete",
        )
        types.validate_annotation(types.seal_record(measured_zero))
        invalid = copy.deepcopy(base)
        invalid["acceptance"] = "accepted-with-corrections"
        with self.assertRaises(types.EvaluationError):
            types.validate_annotation(types.seal_record(invalid))

    def test_measured_zero_and_unavailable_null_are_distinct(self) -> None:
        zero = types.measurement(
            0,
            unit="count",
            state="measured",
            source="codex-jsonl",
            fidelity="exact",
            completeness="complete",
        )
        missing = types.unavailable("count")
        self.assertEqual(zero["value"], 0)
        self.assertIsNone(missing["value"])
        with self.assertRaises(types.EvaluationError):
            types.measurement(
                0,
                unit="count",
                state="unavailable",
                source="none",
                fidelity="unknown",
                completeness="unknown",
            )

    def test_reported_measurement_cannot_be_exact(self) -> None:
        with self.assertRaises(types.EvaluationError):
            types.measurement(
                1,
                unit="count",
                state="measured",
                source="agent-report",
                fidelity="exact",
                completeness="partial",
            )

    def test_reasoning_effort_uses_current_codex_labels(self) -> None:
        repository_id = uuid_text(1)
        valid = manual_record(repository_id, uuid_text(2))
        types.validate_run_record(valid)
        invalid = copy.deepcopy(valid)
        invalid["runtime"]["reasoningEffort"] = "extra-high"
        invalid = types.seal_record(invalid)
        with self.assertRaises(types.EvaluationError):
            types.validate_run_record(invalid)


class JsonlCaptureTests(unittest.TestCase):
    def _lines(self, name: str) -> list[str]:
        return (FIXTURES / "jsonl" / name).read_text(encoding="utf-8").splitlines()

    def test_completed_stream_extracts_only_allowed_metadata(self) -> None:
        summary = capture.parse_jsonl(self._lines("completed.jsonl"))
        self.assertTrue(summary.terminal_event_observed)
        self.assertEqual(summary.completion, "completed")
        self.assertEqual(summary.usage["input_tokens"], 100)
        self.assertEqual(summary.counts["command"], 1)
        self.assertIsNone(summary.final_message)
        self.assertNotIn("sensitive fixture message", json.dumps(summary.__dict__))

    def test_failed_and_missing_terminal_are_distinct(self) -> None:
        failed = capture.parse_jsonl(self._lines("failed.jsonl"))
        missing = capture.parse_jsonl(self._lines("missing-terminal.jsonl"))
        self.assertEqual(failed.completion, "failed")
        self.assertTrue(failed.terminal_event_observed)
        self.assertEqual(missing.completion, "unknown")
        self.assertFalse(missing.terminal_event_observed)

    def test_malformed_and_unknown_events_degrade_parser(self) -> None:
        malformed = capture.parse_jsonl(self._lines("malformed-line.jsonl"))
        unknown = capture.parse_jsonl(self._lines("unknown-event.jsonl"))
        self.assertEqual(malformed.malformed_count, 1)
        self.assertEqual(unknown.unknown_count, 1)
        self.assertEqual(malformed.parser_compatibility, "degraded")
        self.assertEqual(unknown.parser_compatibility, "degraded")
        self.assertNotIn("must not be retained", json.dumps(unknown.__dict__))

    def test_missing_usage_remains_unavailable_and_nonzero_exit_fails(self) -> None:
        summary = capture.parse_jsonl(['{"type":"turn.completed"}'])
        record = capture.base_record(
            run_id=uuid_text(2),
            repository_id=uuid_text(1),
            task_instance_id=uuid_text(3),
            started_at="2026-08-31T12:00:00Z",
            capture_mode="runtime-instrumented",
            prompt_fingerprint=HASH,
            source_snapshot_id="git:" + "2" * 40,
            manifest_sha256=None,
            topology_sha256=None,
            arm="unpaired",
            category="test",
            classification_source="fixture",
            sandbox="read-only",
            model_ref=None,
            reasoning_effort="low",
        )
        completed = capture.apply_capture_to_record(
            record,
            summary=summary,
            exit_code=7,
            elapsed_ms=10,
            cleanup_verified=True,
            codex_version="codex-cli 0.151.0",
            ended_at="2026-08-31T12:00:01Z",
        )
        self.assertEqual(completed["outcome"]["completion"], "failed")
        self.assertTrue(completed["outcome"]["criticalFailure"])
        self.assertIsNone(completed["measurements"]["inputTokens"]["value"])


class CanonicalizationTests(unittest.TestCase):
    def test_clock_id_and_canonical_bytes_are_deterministic(self) -> None:
        clock = types.FixedClock(FIXED_TIME)
        ids = types.SequenceUuidProvider([uuid.UUID(int=1), uuid.UUID(int=2)])
        self.assertEqual(types.timestamp_text(clock.now_utc()), "2026-08-31T12:00:00Z")
        self.assertEqual(str(ids.new_uuid()), uuid_text(1))
        self.assertEqual(str(ids.new_uuid()), uuid_text(2))
        self.assertEqual(types.canonical_bytes({"b": 1, "a": 2}), b'{\n  "a": 2,\n  "b": 1\n}\n')

    def test_integrity_detects_corruption(self) -> None:
        record = manual_record(uuid_text(1), uuid_text(2))
        types.verify_integrity(record)
        record["outcome"]["criticalFailure"] = True
        with self.assertRaises(types.EvaluationError):
            types.verify_integrity(record)


class StoreTests(unittest.TestCase):
    def test_state_root_cannot_contain_or_enter_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            with self.assertRaises(store_module.StoreError):
                store_module.ensure_state_outside_repositories(repository / ".state", [repository])
            with self.assertRaises(store_module.StoreError):
                store_module.ensure_state_outside_repositories(parent, [repository])

    def test_lifecycle_is_immutable_and_export_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            state = parent / "state"
            repository.mkdir()
            ids = types.SequenceUuidProvider([uuid.UUID(int=1)])
            evaluation_store = store_module.EvaluationStore(
                state,
                clock=types.FixedClock(FIXED_TIME),
                ids=ids,
            )
            repository_id = evaluation_store.register_repository(repository)
            record = manual_record(repository_id, uuid_text(2))
            pending = copy.deepcopy(record)
            pending["recordState"] = "pending"
            pending["timestamps"]["endedAt"] = None
            pending["outcome"]["completion"] = "unknown"
            pending = types.seal_record(pending)
            evaluation_store.create_pending(pending)
            evaluation_store.complete_run(record)
            with self.assertRaises(store_module.StoreError):
                evaluation_store.complete_run(record)
            exported = evaluation_store.export_repository(repository_id)
            encoded = json.dumps(exported)
            exported_record = exported["records"][0]
            self.assertIsNone(exported_record["task"]["promptFingerprint"])
            self.assertIsNone(exported_record["runtime"]["modelRef"])
            self.assertIsNone(exported_record["result"]["resultFingerprint"])
            self.assertNotIn(str(repository.resolve()), encoded)
            self.assertFalse(exported["localSecretIncluded"])

    def test_eight_processes_can_reserve_runs_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            state = parent / "state"
            repository.mkdir()
            command = [
                sys.executable,
                str(SCRIPTS / "harness_eval.py"),
                "record-start",
                "--root",
                str(repository),
                "--capture",
                "manual",
                "--state-home",
                str(state),
            ]
            processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(8)]
            results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]
            self.assertTrue(all(returncode == 0 for _, _, returncode in results), results)
            evaluation_store = store_module.EvaluationStore(state)
            runs = evaluation_store.list_runs()
            self.assertEqual(len(runs), 8)
            self.assertEqual(len({item["runId"] for item in runs}), 8)

    def test_repository_pseudonyms_are_scoped_and_registry_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first = parent / "first"
            second = parent / "second"
            state = parent / "state"
            first.mkdir()
            second.mkdir()
            evaluation_store = store_module.EvaluationStore(
                state,
                ids=types.SequenceUuidProvider([uuid.UUID(int=1), uuid.UUID(int=2)]),
            )
            first_id = evaluation_store.register_repository(first)
            second_id = evaluation_store.register_repository(second)
            first_ref = evaluation_store.pseudonym(first_id, "agent", "reviewer")
            self.assertEqual(first_ref, evaluation_store.pseudonym(first_id, "agent", "reviewer"))
            self.assertNotEqual(first_ref, evaluation_store.pseudonym(second_id, "agent", "reviewer"))
            registry_text = evaluation_store.registry_path.read_text(encoding="utf-8")
            self.assertNotIn(str(first.resolve()), registry_text)
            self.assertNotIn(str(second.resolve()), registry_text)
            self.assertEqual(len(evaluation_store.secret_path.read_bytes()), 32)

    def test_purge_preserves_active_run_then_removes_registry_mapping_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            state = parent / "state"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(
                state,
                clock=types.FixedClock(FIXED_TIME),
                ids=types.SequenceUuidProvider([uuid.UUID(int=1)]),
            )
            repository_id = evaluation_store.register_repository(repository)
            completed = manual_record(repository_id, uuid_text(2))
            pending = copy.deepcopy(completed)
            pending["recordState"] = "pending"
            pending["timestamps"]["endedAt"] = None
            pending["outcome"]["completion"] = "unknown"
            evaluation_store.create_pending(pending)
            first = evaluation_store.purge_repository(repository_id)
            self.assertEqual(first["activePendingPreserved"], 1)
            self.assertFalse(first["registryMappingRemoved"])
            evaluation_store.complete_run(completed)
            second = evaluation_store.purge_repository(repository_id)
            self.assertTrue(second["registryMappingRemoved"])
            registry = json.loads(evaluation_store.registry_path.read_text(encoding="utf-8"))
            self.assertNotIn(repository_id, registry["repositories"].values())


class ComparisonTests(unittest.TestCase):
    def comparison_plan(self) -> dict:
        return {
            "schemaVersion": 2,
            "primaryOutcome": {
                "metric": "verification-pass-rate",
                "direction": "higher-is-better",
                "minimumEffect": 0.1,
            },
            "correctnessGate": "no-regression",
            "secondaryOutcomes": ["output-tokens"],
            "verificationProfileFingerprint": HASH,
            "intervention": {
                "expectedChangedFactors": ["agent-set"],
                "attributionTarget": "single-factor",
            },
            "taskStratum": {
                "category": "test",
                "complexityLevel": "unknown",
                "impactLevel": "unknown",
                "uncertaintyLevel": "unknown",
                "scopeClass": "single-file",
            },
            "patchScopeProfileFingerprint": None,
        }

    def test_comparison_uses_predeclared_outcome_and_correctness_gate(self) -> None:
        repository_id = uuid_text(1)
        baseline = manual_record(repository_id, uuid_text(2), arm="baseline", verification="passed")
        treatment = manual_record(repository_id, uuid_text(3), arm="harness", verification="failed", output_tokens=1, critical_failure=True)
        value = compare.compare_runs(
            baseline=baseline,
            treatment=treatment,
            plan=self.comparison_plan(),
            comparison_id=uuid_text(10),
            pair_id=uuid_text(500),
            repository_id=repository_id,
            created_at="2026-08-31T12:02:00Z",
        )
        self.assertEqual(value["primaryOutcome"]["direction"], "harmful")
        self.assertTrue(value["correctnessGate"]["criticalRegression"])
        self.assertEqual(value["evidenceClass"], "paired-replay")
        self.assertFalse(value["causalClaimAllowed"])

    def test_proposal_never_auto_applies(self) -> None:
        repository_id = uuid_text(1)
        baseline = manual_record(repository_id, uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(repository_id, uuid_text(3), arm="harness", verification="passed")
        comparisons = []
        for number in range(10, 15):
            comparisons.append(
                compare.compare_runs(
                    baseline=baseline,
                    treatment=treatment,
                    plan=self.comparison_plan(),
                    comparison_id=uuid_text(number),
                    pair_id=uuid_text(500),
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                )
            )
        value = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=comparisons,
            task_category="test",
        )
        self.assertEqual(value["proposalType"], "configuration-proposal")
        self.assertEqual(value["candidateDelta"]["factor"], "agent-set")
        self.assertFalse(value["autoApplicable"])
        self.assertFalse(value["autoApplicable"])
        self.assertFalse(value["language"]["causalClaimAllowed"])

    def test_primary_outcome_direction_is_not_selectable_afterward(self) -> None:
        plan = self.comparison_plan()
        plan["primaryOutcome"]["direction"] = "lower-is-better"
        with self.assertRaises(types.EvaluationError):
            types.validate_comparison_plan(plan)

    def test_auxiliary_records_reject_causal_or_automatic_mutation(self) -> None:
        repository_id = uuid_text(1)
        baseline = manual_record(repository_id, uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(repository_id, uuid_text(3), arm="harness", verification="passed")
        comparison = compare.compare_runs(
            baseline=baseline,
            treatment=treatment,
            plan=self.comparison_plan(),
            comparison_id=uuid_text(10),
            pair_id=uuid_text(500),
            repository_id=repository_id,
            created_at="2026-08-31T12:02:00Z",
        )
        invalid_comparison = copy.deepcopy(comparison)
        invalid_comparison["causalClaimAllowed"] = True
        invalid_comparison = types.seal_record(invalid_comparison)
        with self.assertRaises(types.EvaluationError):
            types.validate_comparison_record(invalid_comparison)
        proposal = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=[comparison, comparison, comparison],
        )
        invalid_proposal = copy.deepcopy(proposal)
        invalid_proposal["autoApplicable"] = True
        invalid_proposal = types.seal_record(invalid_proposal)
        with self.assertRaises(types.EvaluationError):
            types.validate_proposal_record(invalid_proposal)

    def test_failed_isolation_cannot_gain_proposal_support(self) -> None:
        repository_id = uuid_text(1)
        baseline = manual_record(repository_id, uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(repository_id, uuid_text(3), arm="harness", verification="passed")
        treatment["comparison"]["isolationStatus"] = "failed"
        treatment["comparison"]["isolationGaps"] = ["process-cleanup"]
        treatment = types.seal_record(treatment)
        comparisons = [
            compare.compare_runs(
                baseline=baseline,
                treatment=treatment,
                plan=self.comparison_plan(),
                comparison_id=uuid_text(number),
                pair_id=uuid_text(500),
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )
            for number in range(10, 20)
        ]
        value = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=comparisons,
        )
        self.assertEqual(value["evidence"]["supportStrength"], "insufficient")
        self.assertNotEqual(value["proposalType"], "configuration-proposal")


class PairedIsolationTests(unittest.TestCase):
    def test_runtime_environment_uses_an_isolated_user_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            user_home = root / "user"
            codex_home.mkdir()
            environment = capture._isolated_environment(
                codex_home=codex_home, user_home=user_home
            )
            self.assertEqual(environment["CODEX_HOME"], str(codex_home.resolve()))
            self.assertEqual(environment["HOME"], str(user_home.resolve()))
            self.assertEqual(environment["USERPROFILE"], str(user_home.resolve()))
            self.assertTrue(user_home.is_dir())

    def test_known_user_and_admin_harness_skills_downgrade_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex"
            user_home = root / "user"
            admin_root = root / "admin-skills"
            codex_home.mkdir()
            (user_home / ".agents" / "skills" / "harness").mkdir(parents=True)
            (admin_root / "harness").mkdir(parents=True)
            self.assertEqual(
                harness_eval._known_skill_isolation_gaps(
                    codex_home=codex_home,
                    user_home=user_home,
                    admin_skills_root=admin_root,
                ),
                ["admin-harness-skill", "user-harness-skill"],
            )

    def test_arm_orders_are_seeded_and_counterbalanced(self) -> None:
        first = harness_eval._paired_arm_orders(4, "randomized", 123)
        self.assertEqual(first, harness_eval._paired_arm_orders(4, "randomized", 123))
        self.assertEqual(
            harness_eval._paired_arm_orders(4, "counterbalanced", 123),
            [
                ["baseline", "harness"],
                ["harness", "baseline"],
                ["baseline", "harness"],
                ["harness", "baseline"],
            ],
        )
        with self.assertRaises(types.EvaluationError):
            harness_eval._paired_arm_orders(0, "randomized", 123)

    def test_baseline_removal_preserves_user_instruction_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            managed = root / ".codex" / "agents" / "reviewer.toml"
            manifest = root / ".harness" / "manifest.json"
            managed.parent.mkdir(parents=True)
            manifest.parent.mkdir(parents=True)
            block = f"{harness_eval.harness_state.BEGIN_MARKER}\nmanaged\n{harness_eval.harness_state.END_MARKER}"
            original = f"user prefix\n\n{block}\n\nuser suffix\n"
            agents.write_text(original, encoding="utf-8")
            managed.write_text("managed", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "managedFiles": [
                            {"path": "AGENTS.md", "kind": "managed-block"},
                            {"path": ".codex/agents/reviewer.toml", "kind": "file"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            removed = harness_eval._remove_managed_baseline(root)
            harness_eval._assert_baseline_isolated(root, removed)
            self.assertEqual(agents.read_text(encoding="utf-8"), original.replace(block, "", 1))
            self.assertFalse(managed.exists())


class ResultFingerprintTests(unittest.TestCase):
    def test_fingerprint_includes_tracked_diff_and_nonignored_untracked_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            state = Path(directory) / "state"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            evaluation_store = store_module.EvaluationStore(state)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            (root / "new.txt").write_text("first\n", encoding="utf-8")
            first = harness_eval._result_fingerprint(evaluation_store, root)
            (root / "new.txt").write_text("second\n", encoding="utf-8")
            second = harness_eval._result_fingerprint(evaluation_store, root)
            (root / "ignored.txt").write_text("ignored change\n", encoding="utf-8")
            third = harness_eval._result_fingerprint(evaluation_store, root)
            self.assertIsNotNone(first)
            self.assertNotEqual(first, second)
            self.assertEqual(second, third)

    def test_fingerprint_covers_staged_binary_deletion_and_rename_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            state = Path(directory) / "state"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            (root / "delete.txt").write_text("delete\n", encoding="utf-8")
            (root / "rename.txt").write_text("rename\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            evaluation_store = store_module.EvaluationStore(state)

            (root / "tracked.txt").write_text("staged\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            staged = harness_eval._result_fingerprint(evaluation_store, root)
            (root / "binary.bin").write_bytes(bytes(range(256)))
            binary = harness_eval._result_fingerprint(evaluation_store, root)
            (root / "delete.txt").unlink()
            deleted = harness_eval._result_fingerprint(evaluation_store, root)
            subprocess.run(["git", "-C", str(root), "mv", "rename.txt", "renamed.txt"], check=True)
            renamed = harness_eval._result_fingerprint(evaluation_store, root)
            self.assertEqual(len({staged, binary, deleted, renamed}), 4)

    @unittest.skipIf(os.name == "nt", "creating symlinks may require Windows developer mode")
    def test_fingerprint_hashes_symlink_target_without_following_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            evaluation_store = store_module.EvaluationStore(Path(directory) / "state")
            (root / "link").symlink_to("tracked.txt")
            first = harness_eval._result_fingerprint(evaluation_store, root)
            (root / "link").unlink()
            (root / "link").symlink_to("missing.txt")
            second = harness_eval._result_fingerprint(evaluation_store, root)
            self.assertNotEqual(first, second)


def observation_record(
    repository_id: str,
    run_id: str,
    observation_id: str,
    *,
    execution_class: str = "direct",
    kind: str = "supplement",
    supersedes: str | None = None,
    source: str = "user-report",
) -> dict:
    record = {
        "schemaVersion": 1,
        "observationId": observation_id,
        "repositoryId": repository_id,
        "runId": run_id,
        "createdAt": "2026-08-31T12:04:00Z",
        "lifecycle": {"kind": kind, "supersedesObservationId": supersedes},
        "provenance": {"source": source, "fidelity": "reported" if source in {"user-report", "agent-report"} else "exact", "completeness": "partial"},
        "privacy": {"rawReportStored": False, "freeTextStored": False, "rawComponentNamesStored": False},
        "integrity": {"recordSha256": None},
    }
    if kind != "withdrawal":
        record["payload"] = {
            "observedExecution": {
                "executionClass": schema2.value_observation(execution_class, state="measured", source=source, fidelity="reported" if source in {"user-report", "agent-report"} else "exact", completeness="partial"),
                "route": schema2.reference_set([], state="measured", source=source, fidelity="reported" if source in {"user-report", "agent-report"} else "exact", completeness="partial"),
                "agents": schema2.reference_set([], state="measured", source=source, fidelity="reported" if source in {"user-report", "agent-report"} else "exact", completeness="partial"),
                "skills": schema2.reference_set([], state="measured", source=source, fidelity="reported" if source in {"user-report", "agent-report"} else "exact", completeness="partial"),
                "independentReview": schema2.value_observation(False, state="measured", source=source, fidelity="reported" if source in {"user-report", "agent-report"} else "exact", completeness="partial"),
            },
            "measurements": {},
            "verification": [],
        }
    return types.seal_record(record)


class Schema2ContractTests(unittest.TestCase):
    def test_reference_sets_distinguish_measured_empty_from_unavailable(self) -> None:
        measured = schema2.reference_set(
            [], state="measured", source="runtime-event", fidelity="exact", completeness="complete"
        )
        unavailable = schema2.unavailable_references()
        self.assertEqual(measured["refs"], [])
        self.assertIsNone(unavailable["refs"])
        invalid = copy.deepcopy(unavailable)
        invalid["refs"] = []
        with self.assertRaises(types.EvaluationError):
            schema2.validate_reference_set(invalid)

    def test_schema1_run_remains_readable_without_rewrite(self) -> None:
        record = manual_record(uuid_text(1), uuid_text(2))
        legacy = copy.deepcopy(record)
        legacy["schemaVersion"] = 1
        legacy["runtime"]["harnessVersion"] = "5.5"
        legacy["configuration"] = {
            "arm": "unpaired",
            "configuredExecutionClass": "unknown",
            "configuredRouteRef": None,
            "configuredAgentRefs": [],
            "configuredSkillRefs": [],
            "qualityPolicyRefs": [],
            "observedExecution": {"executionClass": "unknown", "routeRef": None, "agentRefs": [], "skillRefs": [], "source": "unknown"},
        }
        legacy["result"] = {"resultFingerprint": None, "verificationProfileFingerprint": HASH, "processCleanupVerified": True}
        legacy = types.seal_record(legacy)
        types.validate_run_record(legacy)
        self.assertEqual(legacy["schemaVersion"], 1)

    def test_protocol_mismatch_blocks_configuration_proposal(self) -> None:
        tests = ComparisonTests()
        plan = tests.comparison_plan()
        plan["intervention"]["expectedChangedFactors"] = ["skill-set"]
        baseline = manual_record(uuid_text(1), uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(uuid_text(1), uuid_text(3), arm="harness", verification="passed")
        comparisons = [
            compare.compare_runs(
                baseline=baseline,
                treatment=treatment,
                plan=plan,
                comparison_id=uuid_text(number),
                pair_id=uuid_text(500),
                repository_id=uuid_text(1),
                created_at="2026-08-31T12:02:00Z",
            )
            for number in range(10, 15)
        ]
        self.assertFalse(comparisons[0]["configurationDelta"]["protocolMatch"])
        self.assertTrue(comparisons[0]["protocolDeviations"])
        proposal = propose.proposal_from_comparisons(
            repository_id=uuid_text(1), proposal_id=uuid_text(30), created_at="2026-08-31T12:03:00Z", comparisons=comparisons
        )
        self.assertEqual(proposal["proposalType"], "experiment-suggestion")
        self.assertEqual(proposal["candidateDelta"]["attributionScope"], "none")

    def test_bundle_proposal_preserves_the_observed_factor_set(self) -> None:
        tests = ComparisonTests()
        plan = tests.comparison_plan()
        plan["intervention"] = {"expectedChangedFactors": ["agent-set", "skill-set"], "attributionTarget": "bundle"}
        baseline = manual_record(uuid_text(1), uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(uuid_text(1), uuid_text(3), arm="harness", verification="passed")
        treatment["configuration"]["declaredConfiguration"]["skills"] = schema2.reference_set(
            ["skill:" + "6" * 32], state="measured", source="run-configuration-snapshot", fidelity="exact", completeness="complete"
        )
        treatment = types.seal_record(treatment)
        comparisons = [
            compare.compare_runs(
                baseline=baseline, treatment=treatment, plan=plan,
                comparison_id=uuid_text(number), pair_id=uuid_text(500), repository_id=uuid_text(1),
                created_at="2026-08-31T12:02:00Z",
            ) for number in range(10, 15)
        ]
        proposal = propose.proposal_from_comparisons(
            repository_id=uuid_text(1), proposal_id=uuid_text(30), created_at="2026-08-31T12:03:00Z", comparisons=comparisons
        )
        self.assertEqual(proposal["proposalType"], "bundle-proposal")
        self.assertEqual(set(proposal["candidateDelta"]["factors"]), {"agent-set", "skill-set"})
        self.assertFalse(proposal["autoApplicable"])

    def test_incomplete_result_fingerprint_keeps_comparison_but_excludes_attribution(self) -> None:
        tests = ComparisonTests()
        baseline = manual_record(uuid_text(1), uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(uuid_text(1), uuid_text(3), arm="harness", verification="passed")
        treatment["result"]["resultFingerprint"] = schema2.unavailable_value()
        treatment = types.seal_record(treatment)
        comparisons = [
            compare.compare_runs(
                baseline=baseline, treatment=treatment, plan=tests.comparison_plan(),
                comparison_id=uuid_text(number), pair_id=uuid_text(500), repository_id=uuid_text(1),
                created_at="2026-08-31T12:02:00Z",
            ) for number in range(10, 15)
        ]
        self.assertEqual(comparisons[0]["isolationStatus"], "complete")
        self.assertFalse(comparisons[0]["resultFingerprintComplete"])
        proposal = propose.proposal_from_comparisons(
            repository_id=uuid_text(1), proposal_id=uuid_text(30), created_at="2026-08-31T12:03:00Z", comparisons=comparisons
        )
        self.assertEqual(proposal["proposalType"], "experiment-suggestion")

    def test_asymmetric_unknown_configuration_cannot_be_attributed(self) -> None:
        tests = ComparisonTests()
        baseline = manual_record(uuid_text(1), uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(uuid_text(1), uuid_text(3), arm="harness", verification="passed")
        treatment["configuration"]["declaredConfiguration"]["agents"] = schema2.unavailable_references()
        treatment = types.seal_record(treatment)
        comparison = compare.compare_runs(
            baseline=baseline,
            treatment=treatment,
            plan=tests.comparison_plan(),
            comparison_id=uuid_text(10),
            pair_id=uuid_text(500),
            repository_id=uuid_text(1),
            created_at="2026-08-31T12:02:00Z",
        )
        self.assertEqual(comparison["configurationDelta"]["state"], "unavailable")
        self.assertFalse(comparison["configurationDelta"]["protocolMatch"])
        proposal = propose.proposal_from_comparisons(
            repository_id=uuid_text(1),
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=[comparison],
        )
        self.assertEqual(proposal["proposalType"], "experiment-suggestion")
        self.assertEqual(proposal["evidence"]["pairCount"], 0)


class ObservationLifecycleTests(unittest.TestCase):
    def test_annotation_chain_has_one_active_value_and_legacy_ambiguity_is_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(
                parent / "state", ids=types.SequenceUuidProvider([uuid.UUID(int=1)])
            )
            repository_id = evaluation_store.register_repository(repository)
            completed = manual_record(repository_id, uuid_text(2))
            pending = copy.deepcopy(completed)
            pending["recordState"] = "pending"
            pending["timestamps"]["endedAt"] = None
            pending["outcome"]["completion"] = "unknown"
            evaluation_store.create_pending(pending)
            evaluation_store.complete_run(completed)

            def annotation(annotation_id: str, supersedes: str | None) -> dict:
                return {
                    "schemaVersion": 2,
                    "annotationId": annotation_id,
                    "repositoryId": repository_id,
                    "runId": uuid_text(2),
                    "createdAt": "2026-08-31T12:05:00Z",
                    "supersedesAnnotationId": supersedes,
                    "source": "user",
                    "acceptance": "accepted",
                    "correctionCount": types.unavailable("count"),
                    "reopened": False,
                    "freeTextStored": False,
                    "integrity": {"recordSha256": None},
                }

            evaluation_store.add_annotation(repository_id, annotation(uuid_text(20), None))
            with self.assertRaises(store_module.StoreError):
                evaluation_store.add_annotation(repository_id, annotation(uuid_text(21), None))
            evaluation_store.add_annotation(repository_id, annotation(uuid_text(22), uuid_text(20)))
            state = evaluation_view.annotation_state(
                evaluation_store.annotations_for_run(repository_id, uuid_text(2)),
                repository_id=repository_id,
                run_id=uuid_text(2),
            )
            self.assertEqual(state["active"]["annotationId"], uuid_text(22))

            legacy = []
            for number in (30, 31):
                legacy.append(types.seal_record({
                    "schemaVersion": 1,
                    "annotationId": uuid_text(number),
                    "runId": uuid_text(2),
                    "createdAt": "2026-08-31T12:05:00Z",
                    "source": "user",
                    "acceptance": "unknown",
                    "correctionCount": types.unavailable("count"),
                    "reopened": False,
                    "freeTextStored": False,
                    "integrity": {"recordSha256": None},
                }))
            legacy_state = evaluation_view.annotation_state(
                legacy, repository_id=repository_id, run_id=uuid_text(2)
            )
            self.assertIsNone(legacy_state["active"])
            self.assertEqual(legacy_state["conflicts"][0]["code"], "annotation-conflict")

    def test_store_enforces_replacement_and_terminal_withdrawal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(
                parent / "state", ids=types.SequenceUuidProvider([uuid.UUID(int=1)])
            )
            repository_id = evaluation_store.register_repository(repository)
            completed = manual_record(repository_id, uuid_text(2))
            pending = copy.deepcopy(completed)
            pending["recordState"] = "pending"
            pending["timestamps"]["endedAt"] = None
            pending["outcome"]["completion"] = "unknown"
            evaluation_store.create_pending(pending)
            evaluation_store.complete_run(completed)
            first = observation_record(repository_id, uuid_text(2), uuid_text(10))
            replacement = observation_record(repository_id, uuid_text(2), uuid_text(11), execution_class="delegated", kind="replacement", supersedes=uuid_text(10))
            withdrawal = observation_record(repository_id, uuid_text(2), uuid_text(12), kind="withdrawal", supersedes=uuid_text(11))
            evaluation_store.add_observation(repository_id, first)
            evaluation_store.add_observation(repository_id, replacement)
            with self.assertRaises(store_module.StoreError):
                evaluation_store.add_observation(
                    repository_id,
                    observation_record(repository_id, uuid_text(2), uuid_text(13), kind="replacement", supersedes=uuid_text(10)),
                )
            evaluation_store.add_observation(repository_id, withdrawal)
            with self.assertRaises(store_module.StoreError):
                evaluation_store.add_observation(
                    repository_id,
                    observation_record(repository_id, uuid_text(2), uuid_text(14), kind="replacement", supersedes=uuid_text(12)),
                )
            state = evaluation_view.observation_graph(
                evaluation_store.observations_for_run(repository_id, uuid_text(2)), repository_id=repository_id, run_id=uuid_text(2)
            )
            self.assertEqual(state["active"], [])

    def test_equal_authority_observations_conflict_but_runtime_value_wins_over_report(self) -> None:
        repository_id = uuid_text(1)
        run = manual_record(repository_id, uuid_text(2))
        first = observation_record(repository_id, uuid_text(2), uuid_text(10), execution_class="direct")
        second = observation_record(repository_id, uuid_text(2), uuid_text(11), execution_class="delegated")
        view = evaluation_view.derived_evaluation_view(run, [first, second], [])
        self.assertTrue(any(item["code"] == "observed-value-mismatch" for item in view["activeConflicts"]))
        run["configuration"]["observedExecution"]["executionClass"] = schema2.value_observation(
            "direct", state="measured", source="runtime-event", fidelity="exact", completeness="complete"
        )
        run = types.seal_record(run)
        view = evaluation_view.derived_evaluation_view(run, [second], [])
        self.assertEqual(view["selectedValues"]["observedExecution.executionClass"]["value"], "direct")
        self.assertFalse(view["activeConflicts"])

    def test_raw_component_ids_are_validated_against_run_snapshot_and_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(
                parent / "state", ids=types.SequenceUuidProvider([uuid.UUID(int=1), uuid.UUID(int=10)])
            )
            repository_id = evaluation_store.register_repository(repository)
            run = manual_record(repository_id, uuid_text(2))
            reviewer_ref = evaluation_store.pseudonym(repository_id, "agent", "reviewer")
            run["configuration"]["declaredConfiguration"]["agents"] = schema2.reference_set(
                [reviewer_ref], state="measured", source="run-configuration-snapshot", fidelity="exact", completeness="complete"
            )
            run = types.seal_record(run)
            report = parent / "report.json"
            report.write_text(json.dumps({
                "schemaVersion": 1,
                "captureMode": "agent-reported",
                "observedExecution": {
                    "executionClass": "delegated", "routeRef": None, "agentRefs": ["reviewer"],
                    "skillRefs": [], "independentReview": True, "completeness": "partial",
                },
                "measurements": {}, "verification": [],
            }), encoding="utf-8")
            value = harness_eval._observation_from_report(
                evaluation_store=evaluation_store, repository_id=repository_id, run=run,
                report_path=report, kind="supplement", supersedes=None,
            )
            encoded = json.dumps(value)
            self.assertIn(reviewer_ref, encoded)
            self.assertNotIn('"reviewer"', encoded)
            bad = json.loads(report.read_text(encoding="utf-8"))
            bad["observedExecution"]["agentRefs"] = ["not_declared"]
            report.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(types.EvaluationError, "invalid-component-id"):
                harness_eval._observation_from_report(
                    evaluation_store=evaluation_store, repository_id=repository_id, run=run,
                    report_path=report, kind="supplement", supersedes=None,
                )


class PatchScopeTests(unittest.TestCase):
    def test_patch_scope_reports_untracked_and_out_of_scope_paths_without_raw_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repo"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('base')\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            (root / "src" / "main.py").write_text("print('changed')\n", encoding="utf-8")
            (root / "notes.txt").write_text("out of scope\n", encoding="utf-8")
            evaluation_store = store_module.EvaluationStore(parent / "state", ids=types.SequenceUuidProvider([uuid.UUID(int=1)]))
            repository_id = evaluation_store.register_repository(root)
            result = harness_patch_scope.evaluate(
                root=root,
                profile={
                    "schemaVersion": 1, "id": "source-only", "allowedScopes": ["src/**"],
                    "allowUntracked": False, "maximumChangedPaths": 2,
                    "maximumAddedLines": None, "maximumDeletedLines": None,
                },
                repository_id=repository_id,
                store=evaluation_store,
            )
            self.assertFalse(result["withinDeclaredScope"])
            self.assertEqual(result["untrackedCount"], 1)
            self.assertEqual(result["outOfScopeCount"], 1)
            self.assertNotIn("notes.txt", json.dumps(result))

    def test_rename_counts_both_affected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repo"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / "before.txt").write_text("same\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "mv", "before.txt", "after.txt"], check=True)
            evaluation_store = store_module.EvaluationStore(parent / "state", ids=types.SequenceUuidProvider([uuid.UUID(int=1)]))
            repository_id = evaluation_store.register_repository(root)
            result = harness_patch_scope.evaluate(
                root=root,
                profile={
                    "schemaVersion": 1,
                    "id": "rename",
                    "allowedScopes": ["before.txt", "after.txt"],
                    "allowUntracked": False,
                    "maximumChangedPaths": 1,
                    "maximumAddedLines": None,
                    "maximumDeletedLines": None,
                },
                repository_id=repository_id,
                store=evaluation_store,
            )
            self.assertEqual(result["changedTrackedCount"], 2)
            self.assertTrue(result["maximumChangedPathsExceeded"])


class DisabledEvaluationTests(unittest.TestCase):
    def test_change_discipline_suite_has_four_valid_behavioral_cases(self) -> None:
        suite = types.load_json(FIXTURES / "change-discipline-cases.json")
        cases, candidates, behavior_tags = harness_eval._validate_probe_suite(
            suite,
            kind="change-discipline",
        )
        self.assertEqual(
            [case["caseId"] for case in cases],
            [
                "materially-ambiguous-requirement",
                "one-line-function-change",
                "file-scoped-bug-fix",
                "reproducible-bug",
            ],
        )
        self.assertEqual(len(candidates), 4)
        self.assertIn("limits-change-scope", behavior_tags)

    def test_change_discipline_scoring_requires_selection_and_behavior_contract(self) -> None:
        expected = {
            "selection": "surgical-file-edit",
            "requiredBehaviors": ["limits-change-scope"],
            "forbiddenBehaviors": ["changes-unrelated-files"],
        }
        passing = harness_eval._score_probe_case(
            selected={
                "selection": "surgical-file-edit",
                "behaviors": ["limits-change-scope"],
            },
            expected=expected,
            kind="change-discipline",
            behavior_tags=["limits-change-scope", "changes-unrelated-files"],
        )
        failing = harness_eval._score_probe_case(
            selected={
                "selection": "surgical-file-edit",
                "behaviors": ["limits-change-scope", "changes-unrelated-files"],
            },
            expected=expected,
            kind="change-discipline",
            behavior_tags=["limits-change-scope", "changes-unrelated-files"],
        )
        self.assertTrue(passing["matched"])
        self.assertFalse(failing["matched"])

    def test_change_discipline_templates_are_self_contained_for_writers(self) -> None:
        project_harness = (
            REPO_ROOT / ".agents" / "skills" / "harness" / "assets" / "project-harness.md"
        ).read_text(encoding="utf-8")
        agent_template = (
            REPO_ROOT / ".agents" / "skills" / "harness" / "assets" / "agent.toml"
        ).read_text(encoding="utf-8")
        self.assertIn("## Change discipline", project_harness)
        self.assertIn("Define verification before implementation", project_harness)
        self.assertIn("surface material ambiguity and simpler alternatives", agent_template)
        self.assertIn("report completion only after the checks pass", agent_template)

    def test_change_discipline_fixture_validates_without_live_codex(self) -> None:
        parser = harness_eval.build_parser()
        args = parser.parse_args(
            [
                "change-discipline-suite",
                "--cases",
                str(FIXTURES / "change-discipline-cases.json"),
                "--validate-only",
            ]
        )
        self.assertEqual(args.handler(args), 0)

    def test_building_cli_parser_does_not_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            harness_eval.build_parser()
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
