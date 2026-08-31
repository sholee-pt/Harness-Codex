from __future__ import annotations

import copy
import json
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
    record["result"]["verificationProfileFingerprint"] = HASH
    return types.seal_record(record)


class MeasurementTests(unittest.TestCase):
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
            "schemaVersion": 1,
            "primaryOutcome": {
                "metric": "verification-pass-rate",
                "direction": "higher-is-better",
                "minimumEffect": 0.1,
            },
            "correctnessGate": "no-regression",
            "secondaryOutcomes": ["output-tokens"],
            "verificationProfileFingerprint": HASH,
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


class DisabledEvaluationTests(unittest.TestCase):
    def test_building_cli_parser_does_not_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            harness_eval.build_parser()
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
