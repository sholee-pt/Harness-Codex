from __future__ import annotations

import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
FIXTURES = REPO_ROOT / "test" / "fixtures" / "evaluation"
sys.path.insert(0, str(SCRIPTS))

import harness_eval  # noqa: E402
import harness_eval_capture as capture  # noqa: E402
import harness_eval_compare as compare  # noqa: E402
import harness_eval_propose as propose  # noqa: E402
import harness_eval_store as store_module  # noqa: E402
import harness_eval_types as types  # noqa: E402
import harness_eval_schema2 as schema2  # noqa: E402
import harness_eval_view as evaluation_view  # noqa: E402
import harness_apply  # noqa: E402
import harness_plan_builder  # noqa: E402
import harness_patch_scope  # noqa: E402
import harness_state  # noqa: E402
import harness_workspace  # noqa: E402
import harness_metadata
import validate_harness  # noqa: E402


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
    harness_version: str | None = None,
    pair_id: str | None = None,
    capture_mode: str = "manual",
) -> dict:
    record = capture.base_record(
        run_id=run_id,
        repository_id=repository_id,
        task_instance_id=uuid_text(100 + int(uuid.UUID(run_id))),
        started_at="2026-08-31T12:00:00Z",
        capture_mode=capture_mode,
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
        pair_id=(pair_id or uuid_text(500)) if arm != "unpaired" else None,
        comparison_id=uuid_text(501) if arm != "unpaired" else None,
        arm_order="first" if arm == "baseline" else "second" if arm == "harness" else "unpaired",
    )
    record["recordState"] = "completed"
    record["runtime"]["codexVersion"] = "codex-fixture"
    if harness_version is not None:
        record["runtime"]["harnessVersion"] = harness_version
        record["runtime"].pop("evaluationContract", None)
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


def verified_eligibility(
    comparisons: list[dict],
    plan: dict,
    *,
    excluded: dict[str, tuple[str, ...]] | None = None,
) -> propose.ProposalEligibility:
    excluded = excluded or {}
    relevant_ids = tuple(sorted(item["comparisonId"] for item in comparisons))
    basis_ids = tuple(
        item for item in relevant_ids if item not in excluded
    )
    return propose.ProposalEligibility(
        relevant_comparison_ids=relevant_ids,
        attribution_basis_ids=basis_ids,
        excluded_comparison_ids=tuple(sorted(excluded)),
        exclusion_reasons=excluded,
        verified_plan_sha256=types.digest_bytes(types.canonical_bytes(plan)),
        attribution_target=plan["intervention"]["attributionTarget"],
        concrete_attribution_allowed=bool(basis_ids),
    )


def persist_completed(
    evaluation_store: store_module.EvaluationStore,
    record: dict,
) -> None:
    pending = copy.deepcopy(record)
    pending["recordState"] = "pending"
    pending["timestamps"]["endedAt"] = None
    pending["outcome"]["completion"] = "unknown"
    evaluation_store.create_pending(pending)
    evaluation_store.complete_run(record)


def measured_patch_scope(
    profile_fingerprint: str,
    *,
    within_scope: bool = True,
    completeness: str = "complete",
) -> dict:
    return {
        "state": "measured",
        "profileFingerprint": profile_fingerprint,
        "changedTrackedCount": 1,
        "untrackedCount": 0,
        "outOfScopeCount": 0 if within_scope else 1,
        "changedPathRefs": ["path:" + "7" * 32],
        "outOfScopePathRefs": [] if within_scope else ["path:" + "8" * 32],
        "withinDeclaredScope": within_scope,
        "maximumChangedPathsExceeded": False,
        "source": "git-evaluator",
        "fidelity": "exact",
        "completeness": completeness,
    }


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

    def test_reasoning_effort_preserves_future_labels_and_rejects_malformed_values(self) -> None:
        repository_id = uuid_text(1)
        valid = manual_record(repository_id, uuid_text(2))
        types.validate_run_record(valid)
        for effort in ("extra-high", "adaptive", "none", "max", "ultra"):
            record = copy.deepcopy(valid)
            record["runtime"]["reasoningEffort"] = effort
            types.validate_run_record(types.seal_record(record))
        for effort in ("", "high\n", "x" * 257, [], None):
            invalid = copy.deepcopy(valid)
            invalid["runtime"]["reasoningEffort"] = effort
            with self.subTest(effort=effort), self.assertRaises(types.EvaluationError):
                types.validate_run_record(types.seal_record(invalid))


class JsonlCaptureTests(unittest.TestCase):
    def test_normal_capture_checks_cleanup_instead_of_assuming_success(self):
        popen = subprocess.Popen
        def child(command, **options):
            return popen([sys.executable, '-B', '-c', 'import sys; sys.stdin.read(); print(\'{"type":"turn.completed"}\')'], **options)
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(capture, 'codex_preflight', return_value='fixture'), mock.patch.object(capture.subprocess, 'Popen', side_effect=child), mock.patch.object(capture, '_terminate_process_tree', return_value=False) as cleanup:
                summary, exit_code, _, verified, _ = capture.run_codex_jsonl(repository=Path(directory), prompt='fixture', sandbox='read-only', timeout_seconds=10)
            self.assertEqual(summary.completion, 'completed')
            self.assertEqual(exit_code, 0)
            self.assertFalse(verified)
            cleanup.assert_called_once()

    @unittest.skipIf(os.name == 'nt', 'POSIX process-group cleanup')
    def test_normal_capture_terminates_a_surviving_descendant(self):
        popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descendant = "import time; from pathlib import Path; time.sleep(1); Path('escaped.txt').write_text('escaped')"
            parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{descendant!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); sys.stdin.read(); print('{{\"type\":\"turn.completed\"}}')"
            def child(command, **options):
                return popen([sys.executable, '-B', '-c', parent], cwd=root, **options)
            with mock.patch.object(capture, 'codex_preflight', return_value='fixture'), mock.patch.object(capture.subprocess, 'Popen', side_effect=child):
                summary, exit_code, _, _, _ = capture.run_codex_jsonl(repository=root, prompt='fixture', sandbox='read-only', timeout_seconds=10)
            self.assertEqual(summary.completion, 'completed')
            self.assertEqual(exit_code, 0)
            time.sleep(1.1)
            self.assertFalse((root / 'escaped.txt').exists())

    def test_prompt_backpressure_cannot_bypass_capture_timeout(self):
        children = []
        popen = subprocess.Popen
        def child(command, **options):
            process = popen([sys.executable, '-B', '-c', 'import time; time.sleep(30)'], **options)
            children.append(process)
            return process
        with tempfile.TemporaryDirectory() as directory:
            try:
                with mock.patch.object(capture, 'codex_preflight', return_value='fixture'), mock.patch.object(capture.subprocess, 'Popen', side_effect=child):
                    summary, _, elapsed, cleanup, _ = capture.run_codex_jsonl(repository=Path(directory), prompt='x' * (1024 * 1024), sandbox='read-only', timeout_seconds=1)
                self.assertEqual(summary.completion, 'interrupted')
                self.assertEqual(cleanup, os.name != 'nt')
                self.assertLess(elapsed, 15000)
                self.assertIsNotNone(children[0].poll())
                self.assertTrue(children[0].stdin.closed)
            finally:
                for process in children:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)

    def test_interruption_and_parser_error_terminate_and_reap_real_child(self):
        for error in (KeyboardInterrupt, ValueError):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                children = []
                popen = subprocess.Popen
                def child(command, **options):
                    process = popen([sys.executable, '-B', '-c', "import sys,time; print('{}',flush=True); sys.stdin.read(); time.sleep(30)"], **options)
                    children.append(process)
                    return process
                try:
                    with mock.patch.object(capture, 'codex_preflight', return_value='fixture'), mock.patch.object(capture.subprocess, 'Popen', side_effect=child), mock.patch.object(capture.JsonlAccumulator, 'feed', side_effect=error):
                        with self.assertRaises(error):
                            capture.run_codex_jsonl(repository=Path(directory), prompt='fixture', sandbox='read-only', timeout_seconds=10)
                    self.assertIsNotNone(children[0].poll())
                    self.assertTrue(children[0].stdin.closed)
                    self.assertTrue(children[0].stdout.closed)
                finally:
                    for process in children:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)

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

    def test_current_collaboration_item_is_counted_without_retaining_content(self) -> None:
        summary = capture.parse_jsonl(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "collab_tool_call",
                            "tool": "spawn_agent",
                            "prompt": "sensitive delegated task",
                            "status": "completed",
                        },
                    }
                )
            ]
        )
        self.assertEqual(summary.counts["subagent"], 1)
        self.assertEqual(summary.unknown_count, 0)
        self.assertNotIn("sensitive delegated task", json.dumps(summary.__dict__))

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
    def test_repair_reports_misplaced_records_and_preserves_unreadable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(repository)
            run = manual_record(repository_id, uuid_text(2))
            persist_completed(evaluation_store, run)
            root = evaluation_store.repository_root(repository_id)
            record = observation_record(repository_id, run["runId"], uuid_text(10))
            for relative in (f"annotations/{run['runId']}/{uuid_text(10)}.json", f"observations/{uuid_text(11)}.json", f"runs/pending/{uuid_text(10)}.json"):
                with self.subTest(relative=relative):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    data = json.dumps(record).encode()
                    path.write_bytes(data)
                    report = evaluation_store.repair_repository(repository_id)
                    self.assertTrue(any(item["path"] == relative for item in report["invalid"]))
                    self.assertEqual(path.read_bytes(), data)
                    repaired = evaluation_store.repair_repository(repository_id, quarantine=True)
                    self.assertEqual(repaired["quarantined"], 1)
                    self.assertFalse(path.exists())
            unreadable = root / "observations" / f"{uuid_text(12)}.json"
            unreadable.write_bytes(b"{")
            read_text, read_bytes = Path.read_text, Path.read_bytes
            def text(path, *args, **kwargs):
                if path == unreadable:
                    raise PermissionError("fixture")
                return read_text(path, *args, **kwargs)
            def content(path, *args, **kwargs):
                if path == unreadable:
                    raise PermissionError("fixture")
                return read_bytes(path, *args, **kwargs)
            with mock.patch.object(Path, "read_text", text), mock.patch.object(Path, "read_bytes", content):
                report = evaluation_store.repair_repository(repository_id, quarantine=True)
            self.assertEqual(report["quarantined"], 0)
            self.assertTrue(any(item["digest"] == "unreadable" for item in report["invalid"]))
            self.assertEqual(unreadable.read_bytes(), b"{")

    def test_duplicate_run_pair_and_plan_comparison_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(repository)
            plan = ComparisonTests().comparison_plan()
            comparison = compare.compare_runs(
                baseline=manual_record(
                    repository_id, uuid_text(2), arm="baseline", verification="failed"
                ),
                treatment=manual_record(
                    repository_id, uuid_text(3), arm="harness", verification="passed"
                ),
                plan=plan,
                comparison_id=uuid_text(10),
                pair_id=uuid_text(500),
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )
            evaluation_store.write_auxiliary(
                repository_id, "comparisons", comparison["comparisonId"], comparison
            )
            duplicate = copy.deepcopy(comparison)
            duplicate["comparisonId"] = uuid_text(11)
            duplicate = types.seal_record(duplicate)
            with self.assertRaisesRegex(store_module.StoreError, "run pair and plan"):
                evaluation_store.write_auxiliary(
                    repository_id, "comparisons", duplicate["comparisonId"], duplicate
                )

    def test_changed_derived_view_allows_fresh_comparison_for_the_same_run_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(repository)
            plan = ComparisonTests().comparison_plan()
            baseline = manual_record(
                repository_id, uuid_text(2), arm="baseline", verification="failed"
            )
            treatment = manual_record(
                repository_id, uuid_text(3), arm="harness", verification="passed"
            )
            persist_completed(evaluation_store, baseline)
            persist_completed(evaluation_store, treatment)
            original = compare.compare_runs(
                baseline=baseline,
                treatment=treatment,
                plan=plan,
                comparison_id=uuid_text(10),
                pair_id=uuid_text(500),
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )
            evaluation_store.write_auxiliary(
                repository_id, "comparisons", original["comparisonId"], original
            )
            annotation = types.seal_record({
                "schemaVersion": 2,
                "annotationId": uuid_text(20),
                "repositoryId": repository_id,
                "runId": baseline["runId"],
                "createdAt": "2026-08-31T12:05:00Z",
                "supersedesAnnotationId": None,
                "source": "user",
                "acceptance": "accepted",
                "correctionCount": types.unavailable("count"),
                "reopened": False,
                "freeTextStored": False,
                "integrity": {"recordSha256": None},
            })
            evaluation_store.add_annotation(repository_id, annotation)
            baseline_view = evaluation_view.derived_evaluation_view(
                baseline,
                evaluation_store.observations_for_run(repository_id, baseline["runId"]),
                evaluation_store.annotations_for_run(repository_id, baseline["runId"]),
            )
            treatment_view = evaluation_view.derived_evaluation_view(
                treatment, [], []
            )
            refreshed = compare.compare_runs(
                baseline=baseline,
                treatment=treatment,
                plan=plan,
                comparison_id=uuid_text(11),
                pair_id=uuid_text(500),
                repository_id=repository_id,
                created_at="2026-08-31T12:06:00Z",
                baseline_view=baseline_view,
                treatment_view=treatment_view,
            )
            evaluation_store.write_auxiliary(
                repository_id, "comparisons", refreshed["comparisonId"], refreshed
            )
            eligibility = harness_eval._proposal_eligibility(
                evaluation_store=evaluation_store,
                repository_id=repository_id,
                comparisons=[original, refreshed],
                comparison_plan=plan,
                task_category="test",
                complexity_level="unknown",
                impact_level="unknown",
            )
            self.assertIn(
                "derived-view-changed",
                eligibility.exclusion_reasons[original["comparisonId"]],
            )
            self.assertEqual(
                eligibility.attribution_basis_ids,
                (refreshed["comparisonId"],),
                eligibility.exclusion_reasons,
            )

    def test_auxiliary_write_and_repair_enforce_storage_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            other_repository = parent / "other"
            repository.mkdir()
            other_repository.mkdir()
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(repository)
            other_repository_id = evaluation_store.register_repository(other_repository)
            plan = ComparisonTests().comparison_plan()
            comparison = compare.compare_runs(
                baseline=manual_record(repository_id, uuid_text(2), arm="baseline"),
                treatment=manual_record(repository_id, uuid_text(3), arm="harness"),
                plan=plan,
                comparison_id=uuid_text(10),
                pair_id=uuid_text(500),
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )
            with self.assertRaisesRegex(store_module.StoreError, "filename id"):
                evaluation_store.write_auxiliary(
                    repository_id, "comparisons", uuid_text(11), comparison
                )
            with self.assertRaisesRegex(store_module.StoreError, "storage scope"):
                evaluation_store.write_auxiliary(
                    other_repository_id,
                    "comparisons",
                    comparison["comparisonId"],
                    comparison,
                )
            misplaced = (
                evaluation_store.repository_root(repository_id)
                / "comparisons"
                / f"{uuid_text(12)}.json"
            )
            misplaced.write_text(types.canonical_text(comparison), encoding="utf-8")
            wrong_scope = compare.compare_runs(
                baseline=manual_record(other_repository_id, uuid_text(4), arm="baseline"),
                treatment=manual_record(other_repository_id, uuid_text(5), arm="harness"),
                plan=plan,
                comparison_id=uuid_text(13),
                pair_id=uuid_text(502),
                repository_id=other_repository_id,
                created_at="2026-08-31T12:03:00Z",
            )
            wrong_scope_path = (
                evaluation_store.repository_root(repository_id)
                / "comparisons"
                / f"{wrong_scope['comparisonId']}.json"
            )
            wrong_scope_path.write_text(
                types.canonical_text(wrong_scope), encoding="utf-8"
            )
            report = evaluation_store.repair_repository(repository_id)
            self.assertEqual(
                {item["path"] for item in report["invalid"]},
                {
                    f"comparisons/{uuid_text(12)}.json",
                    f"comparisons/{uuid_text(13)}.json",
                },
            )

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

    @unittest.skipUnless(os.name == "nt", "Windows realpath uses Win32 missing-path errors")
    def test_register_repository_survives_parent_creation_during_windows_resolution(self) -> None:
        import ntpath

        native_final_path = ntpath._getfinalpathname
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            state = parent / "state"
            evaluation_store = store_module.EvaluationStore(
                state, ids=types.SequenceUuidProvider([uuid.UUID(int=1)])
            )
            repositories = state / "repositories"
            target = repositories / uuid_text(1)

            def create_parent_after_missing_lookup(path):
                try:
                    return native_final_path(path)
                except OSError as exc:
                    if (
                        ntpath.normcase(str(path)) == ntpath.normcase(str(target))
                        and exc.winerror == 3
                    ):
                        # Reproduce another process creating only the parent:
                        # later target lookups now fail with WinError 2, so
                        # non-strict realpath can retain a \\?\ prefix.
                        repositories.mkdir(parents=True, exist_ok=True)
                    raise

            with mock.patch.object(
                ntpath, "_getfinalpathname", side_effect=create_parent_after_missing_lookup
            ):
                repository_id = evaluation_store.register_repository(repository)
            self.assertEqual(repository_id, uuid_text(1))
            self.assertEqual(evaluation_store.repository_root(repository_id), target.resolve())
            self.assertTrue((target / "runs" / "pending").is_dir())

    def assert_repository_parent_link_is_rejected(self, *, outside: bool) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            state = parent / "state"
            state.mkdir()
            repository = parent / "repo"
            repository.mkdir()
            target = parent / "outside" if outside else state / "other"
            target.mkdir()
            sentinel = target / "sentinel.txt"
            sentinel.write_bytes(b"existing contents\n")
            before = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
            link = state / "repositories"
            if os.name == "nt":
                quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                subprocess.run(
                    [
                        "powershell", "-NoProfile", "-Command",
                        f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} | Out-Null",
                    ],
                    check=True, capture_output=True,
                )
            else:
                link.symlink_to(target, target_is_directory=True)
            try:
                evaluation_store = store_module.EvaluationStore(
                    state, ids=types.SequenceUuidProvider([uuid.UUID(int=1)])
                )
                with self.assertRaisesRegex(store_module.StoreError, "symlink or reparse point"):
                    evaluation_store.register_repository(repository)
                self.assertEqual(list(target.iterdir()), [sentinel])
                self.assertEqual((sentinel.read_bytes(), sentinel.stat().st_mtime_ns), before)
            finally:
                if os.name == "nt":
                    link.rmdir()
                else:
                    link.unlink()

    def test_repository_parent_link_outside_state_is_rejected(self) -> None:
        self.assert_repository_parent_link_is_rejected(outside=True)

    def test_repository_parent_link_inside_state_is_rejected(self) -> None:
        self.assert_repository_parent_link_is_rejected(outside=False)

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
            self.assertFalse(second["registryMappingRemoved"])
            registry = json.loads(evaluation_store.registry_path.read_text(encoding="utf-8"))
            self.assertIn(repository_id, registry["repositories"].values())
            self.assertEqual(evaluation_store.register_repository(repository), repository_id)


class ComparisonTests(unittest.TestCase):
    def test_swapped_failures_cannot_qualify_token_savings(self):
        baseline = manual_record(uuid_text(80), uuid_text(1), arm='baseline', output_tokens=100)
        treatment = manual_record(uuid_text(80), uuid_text(2), arm='harness', output_tokens=10)
        for record, results in ((baseline, ['passed', 'failed']), (treatment, ['failed', 'passed'])):
            template = record['outcome']['verification'][0]
            record['outcome']['verification'] = [dict(template, checkRef='check:' + str(i + 1) * 32, result=result,
                exitCode=dict(template['exitCode'], value=0 if result == 'passed' else 1)) for i, result in enumerate(results)]
            record.update(types.seal_record(record))
            types.validate_run_record(record)
        treatment['outcome']['verification'].reverse()
        treatment.update(types.seal_record(treatment))
        plan = self.comparison_plan()
        plan['primaryOutcome'] = {'metric': 'output-tokens', 'direction': 'lower-is-better', 'minimumEffect': 1}
        plan['secondaryOutcomes'] = ['verification-pass-rate']
        result = compare.compare_runs(baseline=baseline, treatment=treatment, plan=plan,
            comparison_id=uuid_text(10), pair_id=uuid_text(500), repository_id=uuid_text(80), created_at='2026-09-25T00:00:00Z')
        self.assertEqual(result['correctnessGate']['status'], 'failed')
        self.assertTrue(result['correctnessGate']['criticalRegression'])
        self.assertNotEqual(result['primaryOutcome']['direction'], 'beneficial')
        bypass = compare.correctness_gate(baseline, treatment, 'none')
        self.assertTrue(bypass['passed'])
        self.assertTrue(bypass['criticalRegression'])

    def test_unknown_correctness_is_descriptive_and_cannot_support_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluation_store = store_module.EvaluationStore(root / 'state')
            project = root / 'project'
            project.mkdir()
            repository_id = evaluation_store.register_repository(project)
            plan = self.comparison_plan()
            plan['primaryOutcome'] = {'metric': 'output-tokens', 'direction': 'lower-is-better', 'minimumEffect': 1}
            plan['secondaryOutcomes'] = []
            pair_id = uuid_text(80)
            baseline = manual_record(repository_id, uuid_text(81), arm='baseline', pair_id=pair_id, output_tokens=100)
            treatment = manual_record(repository_id, uuid_text(82), arm='harness', pair_id=pair_id, output_tokens=10)
            for record in (baseline, treatment):
                record['outcome']['verification'] = []
                record.update(types.seal_record(record))
                persist_completed(evaluation_store, record)
            value = compare.compare_runs(baseline=baseline, treatment=treatment, plan=plan,
                comparison_id=uuid_text(83), pair_id=pair_id, repository_id=repository_id, created_at='2026-09-25T00:00:00Z')
            self.assertEqual(value['correctnessGate']['status'], 'unknown')
            self.assertFalse(value['correctnessGate']['passed'])
            self.assertEqual(value['primaryOutcome']['delta'], -90)
            # Old stored comparisons without the new status must also be rechecked.
            value['correctnessGate'].pop('status')
            value['correctnessGate']['passed'] = True
            value = types.seal_record(value)
            eligibility = harness_eval._proposal_eligibility(evaluation_store=evaluation_store, repository_id=repository_id,
                comparisons=[value], comparison_plan=plan, task_category='test', complexity_level='unknown', impact_level='unknown')
            self.assertFalse(eligibility.attribution_basis_ids)
            self.assertIn('correctness-verification-unknown', str(eligibility.exclusion_reasons))
            self.assertTrue(compare.correctness_gate(baseline, treatment, 'none')['passed'])

    def test_correctness_requires_matching_complete_check_sets(self):
        baseline = manual_record(uuid_text(80), uuid_text(1), arm='baseline')
        treatment = manual_record(uuid_text(80), uuid_text(2), arm='harness')
        self.assertEqual(compare.correctness_gate(baseline, treatment, 'no-regression')['status'], 'passed')
        for change in ('missing', 'not-run', 'different-check'):
            altered = copy.deepcopy(treatment)
            if change == 'missing':
                altered['outcome']['verification'] = []
            elif change == 'not-run':
                altered['outcome']['verification'][0]['result'] = 'not-run'
            else:
                altered['outcome']['verification'][0]['checkRef'] = 'check:' + '5' * 32
            self.assertEqual(compare.correctness_gate(baseline, altered, 'no-regression')['status'], 'unknown')

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

    def test_comparison_uses_plan_specified_outcome_and_correctness_gate(self) -> None:
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
        plan = self.comparison_plan()
        comparisons = []
        for number in range(10, 15):
            pair_id = uuid_text(500 + number)
            comparisons.append(
                compare.compare_runs(
                    baseline=manual_record(
                        repository_id, uuid_text(1000 + number), arm="baseline",
                        verification="failed", pair_id=pair_id,
                    ),
                    treatment=manual_record(
                        repository_id, uuid_text(2000 + number), arm="harness",
                        verification="passed", pair_id=pair_id,
                    ),
                    plan=plan,
                    comparison_id=uuid_text(number),
                    pair_id=pair_id,
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
            comparison_plan=plan,
            eligibility=verified_eligibility(comparisons, plan),
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

    def test_zero_delta_is_tie_even_when_minimum_effect_is_zero(self) -> None:
        self.assertEqual(compare._direction(0.0, "higher-is-better", 0.0), "tie")
        self.assertEqual(compare._direction(0.0, "lower-is-better", 1.0), "tie")
        self.assertEqual(compare._direction(0.5, "higher-is-better", 1.0), "tie")
        self.assertEqual(compare._direction(1.0, "higher-is-better", 1.0), "beneficial")
        self.assertEqual(compare._direction(-1.0, "higher-is-better", 1.0), "harmful")

    def test_bundle_target_requires_at_least_two_factors(self) -> None:
        plan = self.comparison_plan()
        plan["intervention"] = {
            "expectedChangedFactors": ["agent-set"],
            "attributionTarget": "bundle",
        }
        with self.assertRaisesRegex(types.EvaluationError, "at least two"):
            types.validate_comparison_plan(plan)

    def test_plan_is_required_for_positive_and_negative_attribution(self) -> None:
        repository_id = uuid_text(1)
        plan = self.comparison_plan()
        positive = [
            compare.compare_runs(
                baseline=manual_record(repository_id, uuid_text(2), arm="baseline", verification="failed"),
                treatment=manual_record(repository_id, uuid_text(3), arm="harness", verification="passed"),
                plan=plan,
                comparison_id=uuid_text(number),
                pair_id=uuid_text(500),
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )
            for number in range(10, 13)
        ]
        without_plan = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=positive,
        )
        self.assertEqual(without_plan["proposalType"], "experiment-suggestion")
        self.assertEqual(without_plan["candidateDelta"]["attributionScope"], "none")

        harmful = []
        for number in range(20, 23):
            harmful.append(
                compare.compare_runs(
                    baseline=manual_record(repository_id, uuid_text(4), arm="baseline", verification="passed"),
                    treatment=manual_record(repository_id, uuid_text(5), arm="harness", verification="failed"),
                    plan=plan,
                    comparison_id=uuid_text(number),
                    pair_id=uuid_text(500),
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                )
            )
        negative_without_plan = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(31),
            created_at="2026-08-31T12:03:00Z",
            comparisons=harmful,
        )
        self.assertEqual(negative_without_plan["proposalType"], "experiment-suggestion")
        self.assertEqual(negative_without_plan["candidateDelta"]["attributionScope"], "none")

    def test_two_of_three_is_weak_support_and_ties_cannot_create_strong_support(self) -> None:
        repository_id = uuid_text(1)
        plan = self.comparison_plan()
        plan["primaryOutcome"] = {
            "metric": "output-tokens",
            "direction": "lower-is-better",
            "minimumEffect": 1,
        }
        plan["secondaryOutcomes"] = []
        comparisons = []
        for number, tokens in zip(range(10, 13), (5, 5, 15)):
            pair_id = uuid_text(500 + number)
            comparisons.append(
                compare.compare_runs(
                    baseline=manual_record(
                        repository_id, uuid_text(1000 + number), arm="baseline",
                        output_tokens=10, pair_id=pair_id,
                    ),
                    treatment=manual_record(
                        repository_id, uuid_text(2000 + number), arm="harness",
                        output_tokens=tokens, pair_id=pair_id,
                    ),
                    plan=plan,
                    comparison_id=uuid_text(number),
                    pair_id=pair_id,
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                )
            )
        weak = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=comparisons,
            comparison_plan=plan,
            eligibility=verified_eligibility(comparisons, plan),
        )
        self.assertEqual(weak["evidence"]["supportStrength"], "weak")
        self.assertEqual(weak["proposalType"], "configuration-proposal")
        self.assertEqual(weak["evidence"]["medianPairedDelta"], -5)
        self.assertEqual(weak["evidence"]["thresholds"]["weakDirectionRatio"], 2 / 3)

        mostly_ties = []
        for number, tokens in zip(range(20, 30), (5, 10, 10, 10, 10, 10, 10, 10, 10, 10)):
            pair_id = uuid_text(500 + number)
            mostly_ties.append(
                compare.compare_runs(
                    baseline=manual_record(
                        repository_id, uuid_text(3000 + number), arm="baseline",
                        output_tokens=10, pair_id=pair_id,
                    ),
                    treatment=manual_record(
                        repository_id, uuid_text(4000 + number), arm="harness",
                        output_tokens=tokens, pair_id=pair_id,
                    ),
                    plan=plan,
                    comparison_id=uuid_text(number),
                    pair_id=pair_id,
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                )
            )
        tied = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(31),
            created_at="2026-08-31T12:03:00Z",
            comparisons=mostly_ties,
            comparison_plan=plan,
            eligibility=verified_eligibility(mostly_ties, plan),
        )
        self.assertEqual(tied["evidence"]["supportStrength"], "insufficient")
        self.assertEqual(tied["proposalType"], "experiment-suggestion")

    def test_independent_pair_thresholds_reach_moderate_and_strong(self) -> None:
        repository_id = uuid_text(1)
        plan = self.comparison_plan()
        plan["primaryOutcome"] = {
            "metric": "output-tokens",
            "direction": "lower-is-better",
            "minimumEffect": 1,
        }
        plan["secondaryOutcomes"] = []

        def comparisons_for(tokens: tuple[int, ...], offset: int) -> list[dict]:
            result = []
            for index, treatment_tokens in enumerate(tokens):
                pair_id = uuid_text(5000 + offset + index)
                result.append(compare.compare_runs(
                    baseline=manual_record(
                        repository_id, uuid_text(10_000 + offset + index), arm="baseline",
                        output_tokens=10, pair_id=pair_id,
                    ),
                    treatment=manual_record(
                        repository_id, uuid_text(20_000 + offset + index), arm="harness",
                        output_tokens=treatment_tokens, pair_id=pair_id,
                    ),
                    plan=plan,
                    comparison_id=uuid_text(30_000 + offset + index),
                    pair_id=pair_id,
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                ))
            return result

        moderate_comparisons = comparisons_for((5, 5, 5, 5, 15), 0)
        moderate = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(400),
            created_at="2026-08-31T12:03:00Z",
            comparisons=moderate_comparisons,
            comparison_plan=plan,
            eligibility=verified_eligibility(moderate_comparisons, plan),
        )
        self.assertEqual(moderate["evidence"]["supportStrength"], "moderate")

        strong_comparisons = comparisons_for((5, 5, 5, 5, 5, 5, 5, 5, 15, 15), 100)
        strong = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(401),
            created_at="2026-08-31T12:03:00Z",
            comparisons=strong_comparisons,
            comparison_plan=plan,
            eligibility=verified_eligibility(strong_comparisons, plan),
        )
        self.assertEqual(strong["evidence"]["supportStrength"], "strong")

    def test_patch_scope_profile_mismatch_is_rejected_and_baseline_violation_is_recorded(self) -> None:
        repository_id = uuid_text(1)
        plan = self.comparison_plan()
        plan["patchScopeProfileFingerprint"] = HASH
        baseline = manual_record(repository_id, uuid_text(2), arm="baseline", verification="failed")
        treatment = manual_record(repository_id, uuid_text(3), arm="harness", verification="passed")
        baseline["result"]["patchScope"] = measured_patch_scope(HASH, within_scope=False)
        treatment["result"]["patchScope"] = measured_patch_scope(HASH)
        baseline = types.seal_record(baseline)
        treatment = types.seal_record(treatment)
        comparison = compare.compare_runs(
            baseline=baseline,
            treatment=treatment,
            plan=plan,
            comparison_id=uuid_text(10),
            pair_id=uuid_text(500),
            repository_id=repository_id,
            created_at="2026-08-31T12:02:00Z",
        )
        self.assertIn("baseline-patch-scope-violation", comparison["confounders"])
        blocked = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=[comparison],
            comparison_plan=plan,
            eligibility=verified_eligibility(
                [comparison],
                plan,
                excluded={
                    comparison["comparisonId"]: ("baseline-patch-scope-violation",)
                },
            ),
        )
        self.assertEqual(blocked["proposalType"], "experiment-suggestion")
        self.assertEqual(blocked["candidateDelta"]["attributionScope"], "none")

        treatment["result"]["patchScope"] = measured_patch_scope("2" * 64)
        treatment = types.seal_record(treatment)
        with self.assertRaisesRegex(compare.ComparisonError, "patch-scope profile"):
            compare.compare_runs(
                baseline=baseline,
                treatment=treatment,
                plan=plan,
                comparison_id=uuid_text(11),
                pair_id=uuid_text(500),
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )

    def test_v60_schema2_run_remains_readable(self) -> None:
        repository_id = uuid_text(1)
        legacy = manual_record(repository_id, uuid_text(2), harness_version="6.0")
        types.validate_run_record(legacy)
        self.assertNotIn(
            legacy["runtime"]["harnessVersion"],
            schema2.ATTRIBUTION_ELIGIBLE_HARNESS_VERSIONS,
        )
        v62 = manual_record(repository_id, uuid_text(6), harness_version="6.2")
        types.validate_run_record(v62)
        self.assertNotIn(
            v62["runtime"]["harnessVersion"],
            schema2.ATTRIBUTION_ELIGIBLE_HARNESS_VERSIONS,
        )
        v63 = manual_record(repository_id, uuid_text(7), harness_version="6.3")
        types.validate_run_record(v63)
        self.assertNotIn(
            v63["runtime"]["harnessVersion"],
            schema2.ATTRIBUTION_ELIGIBLE_HARNESS_VERSIONS,
        )
        v64 = manual_record(repository_id, uuid_text(8), harness_version="6.4")
        types.validate_run_record(v64)
        self.assertNotIn(
            v64["runtime"]["harnessVersion"],
            schema2.ATTRIBUTION_ELIGIBLE_HARNESS_VERSIONS,
        )
        self.assertEqual(schema2.ATTRIBUTION_ELIGIBLE_HARNESS_VERSIONS, harness_metadata.ATTRIBUTION_ELIGIBLE_EVALUATION_VERSIONS)
        plan = self.comparison_plan()
        v60_comparison = compare.compare_runs(
            baseline=manual_record(repository_id, uuid_text(2), arm="baseline", verification="failed", harness_version="6.0"),
            treatment=manual_record(repository_id, uuid_text(3), arm="harness", verification="passed", harness_version="6.0"),
            plan=plan,
            comparison_id=uuid_text(10),
            pair_id=uuid_text(500),
            repository_id=repository_id,
            created_at="2026-08-31T12:02:00Z",
        )
        v61_comparison = compare.compare_runs(
            baseline=manual_record(repository_id, uuid_text(4), arm="baseline", verification="failed"),
            treatment=manual_record(repository_id, uuid_text(5), arm="harness", verification="passed"),
            plan=plan,
            comparison_id=uuid_text(11),
            pair_id=uuid_text(500),
            repository_id=repository_id,
            created_at="2026-08-31T12:02:00Z",
        )
        self.assertNotEqual(
            v60_comparison["evaluationStratumFingerprint"],
            v61_comparison["evaluationStratumFingerprint"],
        )

    def test_runtime_mismatch_is_partial_and_runtime_strata_are_distinct(self) -> None:
        repository_id = uuid_text(1)
        plan = self.comparison_plan()
        baseline = manual_record(repository_id, uuid_text(2), arm="baseline")
        treatment = manual_record(repository_id, uuid_text(3), arm="harness")
        treatment["runtime"]["codexVersion"] = "different-codex"
        treatment = types.seal_record(treatment)
        mismatch = compare.compare_runs(
            baseline=baseline,
            treatment=treatment,
            plan=plan,
            comparison_id=uuid_text(10),
            pair_id=uuid_text(500),
            repository_id=repository_id,
            created_at="2026-08-31T12:02:00Z",
        )
        self.assertEqual(mismatch["isolationStatus"], "partial")
        self.assertIn("codex-version", mismatch["isolationGaps"])

        def comparison_for_runtime(number: int, platform_name: str, capture_mode: str) -> dict:
            pair_id = uuid_text(700 + number)
            left = manual_record(
                repository_id, uuid_text(1000 + number), arm="baseline",
                pair_id=pair_id, capture_mode=capture_mode,
            )
            right = manual_record(
                repository_id, uuid_text(2000 + number), arm="harness",
                pair_id=pair_id, capture_mode=capture_mode,
            )
            for record in (left, right):
                record["runtime"]["platform"] = platform_name
                record["runtime"]["sandbox"] = "workspace-write" if number else "read-only"
            return compare.compare_runs(
                baseline=types.seal_record(left),
                treatment=types.seal_record(right),
                plan=plan,
                comparison_id=uuid_text(20 + number),
                pair_id=pair_id,
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )

        first = comparison_for_runtime(0, "linux", "manual")
        second = comparison_for_runtime(1, "windows", "agent-reported")
        self.assertEqual(first["isolationStatus"], "complete")
        self.assertEqual(second["isolationStatus"], "complete")
        self.assertNotEqual(
            first["evaluationStratumFingerprint"],
            second["evaluationStratumFingerprint"],
        )

    def test_independent_review_uses_topology_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            (repository / ".harness").mkdir(parents=True)
            evaluation_store = store_module.EvaluationStore(
                parent / "state", ids=types.SequenceUuidProvider([uuid.UUID(int=1)])
            )
            repository_id = evaluation_store.register_repository(repository)
            args = type("Args", (), {"execution_class": "unknown"})()
            cases = (
                (["producer-reviewer"], [], True),
                ([], [{"id": "safety", "name": "independent-safety-review"}], True),
                ([], [{"id": "critic", "name": "completeness-critic"}], False),
            )
            for patterns, policies, expected in cases:
                (repository / ".harness" / "manifest.json").write_text(
                    json.dumps({
                        "topology": {
                            "collaborationPatterns": patterns,
                            "qualityPatternPolicies": policies,
                            "boundaries": [{
                                "separationBenefits": {"independentReview": True}
                            }],
                        }
                    }),
                    encoding="utf-8",
                )
                snapshot = harness_eval._configuration_snapshot(
                    evaluation_store, repository_id, repository, args, "harness"
                )
                self.assertEqual(
                    snapshot["declaredConfiguration"]["independentReview"]["value"],
                    expected,
                )

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
            comparisons=[comparison],
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

    def test_helper_requires_verified_eligibility_and_independent_runs(self) -> None:
        repository_id = uuid_text(1)
        plan = self.comparison_plan()
        comparisons = []
        for number in range(10, 13):
            pair_id = uuid_text(500 + number)
            comparisons.append(compare.compare_runs(
                baseline=manual_record(
                    repository_id, uuid_text(1000 + number), arm="baseline",
                    verification="failed", pair_id=pair_id,
                ),
                treatment=manual_record(
                    repository_id, uuid_text(2000 + number), arm="harness",
                    verification="passed", pair_id=pair_id,
                ),
                plan=plan,
                comparison_id=uuid_text(number),
                pair_id=pair_id,
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            ))
        descriptive = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(30),
            created_at="2026-08-31T12:03:00Z",
            comparisons=comparisons,
            comparison_plan=plan,
        )
        self.assertEqual(descriptive["proposalType"], "experiment-suggestion")
        self.assertEqual(descriptive["evidence"]["pairCount"], 0)

        attributed = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(31),
            created_at="2026-08-31T12:03:00Z",
            comparisons=comparisons,
            comparison_plan=plan,
            eligibility=verified_eligibility(comparisons, plan),
        )
        self.assertEqual(attributed["evidence"]["supportStrength"], "weak")
        with self.assertRaisesRegex(propose.ProposalError, "unique comparison IDs"):
            propose.proposal_from_comparisons(
                repository_id=repository_id,
                proposal_id=uuid_text(32),
                created_at="2026-08-31T12:03:00Z",
                comparisons=[comparisons[0], comparisons[0]],
                comparison_plan=plan,
            )

        shared_baseline = manual_record(
            repository_id, uuid_text(3000), arm="baseline",
            verification="failed", pair_id=uuid_text(900),
        )
        reused = [
            compare.compare_runs(
                baseline=shared_baseline,
                treatment=manual_record(
                    repository_id, uuid_text(3100 + number), arm="harness",
                    verification="passed", pair_id=uuid_text(900),
                ),
                plan=plan,
                comparison_id=uuid_text(40 + number),
                pair_id=uuid_text(900),
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            )
            for number in range(2)
        ]
        with self.assertRaisesRegex(propose.ProposalError, "independent run pairs"):
            propose.proposal_from_comparisons(
                repository_id=repository_id,
                proposal_id=uuid_text(33),
                created_at="2026-08-31T12:03:00Z",
                comparisons=reused,
                comparison_plan=plan,
                eligibility=verified_eligibility(reused, plan),
            )

    def test_complete_task_failures_remain_valid_harmful_evidence(self) -> None:
        repository_id = uuid_text(1)
        plan = self.comparison_plan()
        comparisons = []
        for number in range(3):
            pair_id = uuid_text(950 + number)
            comparisons.append(compare.compare_runs(
                baseline=manual_record(
                    repository_id, uuid_text(6000 + number), arm="baseline",
                    verification="passed", pair_id=pair_id,
                ),
                treatment=manual_record(
                    repository_id, uuid_text(7000 + number), arm="harness",
                    verification="failed", critical_failure=True, pair_id=pair_id,
                ),
                plan=plan,
                comparison_id=uuid_text(150 + number),
                pair_id=pair_id,
                repository_id=repository_id,
                created_at="2026-08-31T12:02:00Z",
            ))
        proposal = propose.proposal_from_comparisons(
            repository_id=repository_id,
            proposal_id=uuid_text(350),
            created_at="2026-08-31T12:03:00Z",
            comparisons=comparisons,
            comparison_plan=plan,
            eligibility=verified_eligibility(comparisons, plan),
        )
        self.assertEqual(proposal["proposalType"], "negative-signal")
        self.assertEqual(proposal["evidence"]["direction"], "harmful")
        self.assertEqual(proposal["evidence"]["supportStrength"], "weak")

    def test_store_eligibility_excludes_partial_but_keeps_independent_complete_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(repository)
            plan = self.comparison_plan()
            comparisons = []
            for number in range(4):
                pair_id = uuid_text(600 + number)
                baseline = manual_record(
                    repository_id, uuid_text(4000 + number), arm="baseline",
                    verification="failed", pair_id=pair_id,
                )
                treatment = manual_record(
                    repository_id, uuid_text(5000 + number), arm="harness",
                    verification="passed", pair_id=pair_id,
                )
                if number == 3:
                    treatment["runtime"]["platform"] = (
                        "linux" if baseline["runtime"]["platform"] != "linux" else "windows"
                    )
                    treatment = types.seal_record(treatment)
                persist_completed(evaluation_store, baseline)
                persist_completed(evaluation_store, treatment)
                comparisons.append(compare.compare_runs(
                    baseline=baseline,
                    treatment=treatment,
                    plan=plan,
                    comparison_id=uuid_text(100 + number),
                    pair_id=pair_id,
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                ))
            self.assertEqual(comparisons[-1]["isolationStatus"], "partial")
            self.assertIn("platform", comparisons[-1]["isolationGaps"])
            eligibility = harness_eval._proposal_eligibility(
                evaluation_store=evaluation_store,
                repository_id=repository_id,
                comparisons=comparisons,
                comparison_plan=plan,
                task_category="test",
                complexity_level="unknown",
                impact_level="unknown",
            )
            self.assertEqual(len(eligibility.attribution_basis_ids), 3)
            self.assertIn(
                "comparison-isolation-not-complete",
                eligibility.exclusion_reasons[comparisons[-1]["comparisonId"]],
            )
            proposal = propose.proposal_from_comparisons(
                repository_id=repository_id,
                proposal_id=uuid_text(300),
                created_at="2026-08-31T12:03:00Z",
                comparisons=comparisons,
                task_category="test",
                comparison_plan=plan,
                eligibility=eligibility,
            )
            self.assertEqual(proposal["evidence"]["pairCount"], 3)
            self.assertEqual(proposal["evidence"]["supportStrength"], "weak")

    def test_proposal_requires_explicit_selection_for_multiple_eligible_strata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            repository = parent / "repo"
            repository.mkdir()
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(repository)
            plan = self.comparison_plan()
            comparisons: list[dict] = []
            for number in range(2):
                pair_id = uuid_text(700 + number)
                baseline = manual_record(
                    repository_id,
                    uuid_text(6000 + number),
                    arm="baseline",
                    verification="failed",
                    pair_id=pair_id,
                )
                treatment = manual_record(
                    repository_id,
                    uuid_text(7000 + number),
                    arm="harness",
                    verification="passed",
                    pair_id=pair_id,
                )
                if number == 1:
                    for record in (baseline, treatment):
                        record["runtime"]["modelRef"] = "model:" + "9" * 32
                    baseline = types.seal_record(baseline)
                    treatment = types.seal_record(treatment)
                persist_completed(evaluation_store, baseline)
                persist_completed(evaluation_store, treatment)
                comparisons.append(compare.compare_runs(
                    baseline=baseline,
                    treatment=treatment,
                    plan=plan,
                    comparison_id=uuid_text(200 + number),
                    pair_id=pair_id,
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                ))
            strata = sorted({
                item["evaluationStratumFingerprint"] for item in comparisons
            })
            self.assertEqual(len(strata), 2)
            with self.assertRaisesRegex(
                types.EvaluationError,
                "multiple concrete-eligible evaluation strata",
            ):
                harness_eval._proposal_eligibility(
                    evaluation_store=evaluation_store,
                    repository_id=repository_id,
                    comparisons=comparisons,
                    comparison_plan=plan,
                    task_category="test",
                    complexity_level="unknown",
                    impact_level="unknown",
                )
            selected = comparisons[0]["evaluationStratumFingerprint"]
            eligibility = harness_eval._proposal_eligibility(
                evaluation_store=evaluation_store,
                repository_id=repository_id,
                comparisons=comparisons,
                comparison_plan=plan,
                task_category="test",
                complexity_level="unknown",
                impact_level="unknown",
                evaluation_stratum=selected,
            )
            proposal = propose.proposal_from_comparisons(
                repository_id=repository_id,
                proposal_id=uuid_text(900),
                created_at="2026-08-31T12:03:00Z",
                comparisons=comparisons,
                task_category="test",
                comparison_plan=plan,
                eligibility=eligibility,
                evaluation_stratum=selected,
            )
            self.assertEqual(proposal["evidence"]["pairCount"], 1)
            self.assertEqual(
                proposal["evidence"]["comparisonRefs"],
                [comparisons[0]["comparisonId"]],
            )

            missing = "f" * 64
            with self.assertRaisesRegex(
                types.EvaluationError,
                "requested evaluation stratum was not found",
            ):
                harness_eval._proposal_eligibility(
                    evaluation_store=evaluation_store,
                    repository_id=repository_id,
                    comparisons=comparisons,
                    comparison_plan=plan,
                    task_category="test",
                    complexity_level="unknown",
                    impact_level="unknown",
                    evaluation_stratum=missing,
                )
            with self.assertRaisesRegex(
                propose.ProposalError,
                "requested evaluation stratum was not found",
            ):
                propose.proposal_from_comparisons(
                    repository_id=repository_id,
                    proposal_id=uuid_text(901),
                    created_at="2026-08-31T12:03:00Z",
                    comparisons=comparisons,
                    task_category="test",
                    comparison_plan=plan,
                    evaluation_stratum=missing,
                )


class PairedIsolationTests(unittest.TestCase):
    def test_verification_interruption_always_cleans_up(self):
        process = mock.Mock()
        process.wait.side_effect = KeyboardInterrupt
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(harness_eval.subprocess, 'Popen', return_value=process), mock.patch.object(capture, '_terminate_process_tree', return_value=False) as cleanup:
                with self.assertRaises(KeyboardInterrupt):
                    harness_eval._run_verification(root=Path(directory), profile={'argv': ['fixture'], 'timeoutSeconds': 1, 'kind': 'custom'}, profile_digest=HASH, check_ref='check:' + '4' * 32)
            cleanup.assert_called_once_with(process)

    @staticmethod
    def _verification_repository(parent: Path) -> tuple[Path, str]:
        root = parent / "repo"
        root.mkdir()
        subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
        (root / "src.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
        base_ref = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        return root, base_ref

    @staticmethod
    def _local_only_repository(parent: Path) -> tuple[Path, str]:
        root = parent / "source"
        shutil.copytree(REPO_ROOT / "test" / "fixtures" / "minimal-project", root)
        subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Fixture"], check=True
        )
        subprocess.run(
            ["git", "-C", str(root), "add", "README.md", "pyproject.toml"], check=True
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "fixture"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        draft = json.loads(
            (
                REPO_ROOT
                / ".agents"
                / "skills"
                / "harness"
                / "references"
                / "minimal-draft-plan.json"
            ).read_text(encoding="utf-8")
        )
        plan = harness_plan_builder.materialize_plan(draft, root=root)
        harness_apply.apply_application(harness_apply.build_application(root, plan))
        assert validate_harness.Validator(root).run()["valid"]
        # Evaluation fixtures explicitly opt into a clean, untracked overlay.
        # Normal project generation no longer changes any Git metadata.
        manifest = json.loads((root / ".harness/manifest.json").read_text(encoding="utf-8"))
        paths = [item["path"] for item in manifest["managedFiles"]]
        protection = harness_workspace.plan_local_protection(root, "git-repository", paths)
        harness_workspace.apply_local_protection(root, protection, paths)
        return root, commit

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

    def test_paired_evidence_target_rejects_reserved_metadata_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (".git/config", ".GIT/config", ".harness/manifest.json"):
                with self.subTest(relative=relative):
                    with self.assertRaisesRegex(
                        types.EvaluationError, "reserved control namespace"
                    ):
                        harness_eval._evidence_target(root, relative)

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

    def test_local_only_installation_materializes_independent_clone_arms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            source_exclude = source / ".git" / "info" / "exclude"
            source_exclude_before = source_exclude.read_bytes()
            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)
            self.assertTrue(all(item["tracked"] for item in snapshot["evidenceFiles"]))
            self.assertFalse(snapshot["projectConfigPresent"])
            self.assertNotIn(
                "project-config-load-unverified", snapshot["isolationGaps"]
            )
            baseline = parent / "pair" / "baseline"
            treatment = parent / "pair" / "treatment"

            harness_eval._clone_local_evaluation_arm(source, baseline, commit)
            harness_eval._clone_local_evaluation_arm(source, treatment, commit)
            removed = harness_eval._materialize_paired_arms(
                baseline, treatment, snapshot
            )

            self.assertTrue(removed)
            self.assertFalse((baseline / ".harness" / "manifest.json").exists())
            self.assertFalse(
                (baseline / ".agents" / "skills" / "project-harness" / "SKILL.md").exists()
            )
            self.assertTrue(validate_harness.Validator(treatment).run()["valid"])
            self.assertEqual(
                harness_eval._manifest_metadata(treatment)[0],
                snapshot["treatmentManifestSha256"],
            )
            self.assertEqual(len(harness_workspace.registered_worktrees(source)), 1)
            self.assertEqual(source_exclude.read_bytes(), source_exclude_before)
            self.assertEqual(harness_eval._git(baseline, "remote").stdout.strip(), "")
            self.assertEqual(harness_eval._git(treatment, "remote").stdout.strip(), "")

            baseline_base = harness_eval._prepare_task_base(baseline, commit)
            treatment_base = harness_eval._prepare_task_base(treatment, commit)
            for root, task_base in (
                (baseline, baseline_base),
                (treatment, treatment_base),
            ):
                self.assertEqual(
                    harness_eval._git(root, "rev-parse", f"{task_base}^").stdout.strip(),
                    commit,
                )
                self.assertEqual(harness_eval._git(root, "status", "--porcelain").stdout, "")

    def test_paired_snapshot_preflight_detects_managed_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)
            skill = source / ".agents" / "skills" / "project-harness" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "external edit\n", encoding="utf-8")

            with self.assertRaisesRegex(types.EvaluationError, "managed file changed"):
                harness_eval._verify_local_harness_snapshot(source, snapshot)

    def test_paired_materialization_refuses_target_collision_before_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)
            baseline = parent / "pair" / "baseline"
            treatment = parent / "pair" / "treatment"
            harness_eval._clone_local_evaluation_arm(source, baseline, commit)
            harness_eval._clone_local_evaluation_arm(source, treatment, commit)
            collision = treatment / snapshot["managedFiles"][0]["path"]
            collision.parent.mkdir(parents=True, exist_ok=True)
            collision.write_text("user-owned\n", encoding="utf-8")

            with self.assertRaisesRegex(types.EvaluationError, "conflicting Harness target"):
                harness_eval._materialize_paired_arms(baseline, treatment, snapshot)

            self.assertEqual(collision.read_text(encoding="utf-8"), "user-owned\n")
            self.assertFalse((baseline / ".harness" / "manifest.json").exists())

    def test_paired_dry_run_preflights_and_reports_local_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, _commit = self._local_only_repository(parent)
            codex_home = parent / "codex-home"
            codex_home.mkdir()
            args = harness_eval.build_parser().parse_args(
                [
                    "paired-run",
                    "--root",
                    str(source),
                    "--task-file",
                    str(FIXTURES / "task.txt"),
                    "--comparison-plan",
                    str(FIXTURES / "comparison-plan.json"),
                    "--verification",
                    str(FIXTURES / "verification-profile.json"),
                    "--codex-home",
                    str(codex_home),
                    "--repetitions",
                    "2",
                    "--order",
                    "counterbalanced",
                    "--seed",
                    "72",
                    "--dry-run",
                ]
            )
            output = io.StringIO()
            with mock.patch("sys.stdout", output), mock.patch.object(
                harness_eval,
                "_clone_local_evaluation_arm",
                side_effect=AssertionError("default dry-run must not clone"),
            ):
                self.assertEqual(harness_eval.command_paired_run(args), 0)
            report = json.loads(output.getvalue())

            self.assertTrue(report["valid"])
            self.assertFalse(report["stateWritten"])
            self.assertEqual(
                report["materialization"]["mode"],
                harness_eval.PAIRED_MATERIALIZATION_MODE,
            )
            self.assertEqual(report["materialization"]["sourceWorktreeCount"], 1)
            self.assertGreater(report["materialization"]["managedFileCount"], 0)
            self.assertFalse(report["materialization"]["clonePerformed"])
            self.assertFalse(report["materialization"]["materializationValidated"])
            self.assertFalse(report["materialization"]["projectConfigPresent"])
            self.assertFalse(report["materialization"]["projectConfigMaterialized"])
            self.assertEqual(
                report["materialization"]["effectiveProjectConfigLoad"],
                "not-applicable",
            )
            self.assertEqual(report["materialization"]["projectAgentConfigCount"], 0)
            self.assertEqual(
                report["materialization"]["effectiveProjectAgentLoad"],
                "not-applicable",
            )
            self.assertIsNone(
                report["materialization"]["projectAgentDependenciesVerified"]
            )
            self.assertEqual(
                report["materialization"]["projectRules"],
                "intentionally-disabled",
            )
            self.assertEqual(
                report["materialization"]["projectHooks"],
                "not-enabled-by-harness",
            )
            self.assertFalse(report["materialization"]["expectedGitRemoteRetained"])
            self.assertIsNone(report["materialization"]["observedGitRemoteRetained"])

            args.validate_materialization = True
            output = io.StringIO()
            with mock.patch("sys.stdout", output):
                self.assertEqual(harness_eval.command_paired_run(args), 0)
            validated = json.loads(output.getvalue())
            self.assertTrue(validated["materialization"]["clonePerformed"])
            self.assertTrue(validated["materialization"]["materializationValidated"])
            self.assertFalse(
                validated["materialization"]["observedGitRemoteRetained"]
            )

            (source / ".harness" / "manifest.json").unlink()
            with self.assertRaisesRegex(types.EvaluationError, "valid project-local"):
                harness_eval.command_paired_run(args)

    def test_snapshot_classifies_manifest_referenced_ignored_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            evidence = source / "private" / "context.txt"
            evidence.parent.mkdir()
            evidence.write_bytes(b"ignored local evidence\n")
            exclude = source / ".git" / "info" / "exclude"
            exclude.write_bytes(b"private/context.txt\n" + exclude.read_bytes())
            manifest_path = source / ".harness" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["project"]["evidence"].append(
                {
                    "path": "private/context.txt",
                    "sha256": types.digest_bytes(evidence.read_bytes()),
                    "claim": "Supplies private local context for the test.",
                }
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            validation = validate_harness.Validator(source).run()
            self.assertTrue(validation["valid"], validation["errors"])

            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)

            captured = {
                item["path"]: item for item in snapshot["evidenceFiles"]
            }
            self.assertFalse(captured["private/context.txt"]["tracked"])
            self.assertEqual(
                captured["private/context.txt"]["data"], b"ignored local evidence\n"
            )
            baseline = parent / "pair" / "baseline"
            treatment = parent / "pair" / "treatment"
            harness_eval._clone_local_evaluation_arm(source, baseline, commit)
            harness_eval._clone_local_evaluation_arm(source, treatment, commit)
            harness_eval._materialize_paired_arms(baseline, treatment, snapshot)
            self.assertEqual(evidence.read_bytes(), b"ignored local evidence\n")
            self.assertEqual(
                (baseline / "private" / "context.txt").read_bytes(),
                b"ignored local evidence\n",
            )
            self.assertEqual(
                (treatment / "private" / "context.txt").read_bytes(),
                b"ignored local evidence\n",
            )

    def test_paired_arms_preserve_and_measure_ignored_project_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            exclude = source / ".git" / "info" / "exclude"
            exclude.write_bytes(
                (
                    ".codex/config.toml\n"
                    ".codex/agents/user-reviewer.toml\n"
                    ".agents/skills/user-check/\n"
                    "PROJECT_GUIDE.md\n"
                ).encode("utf-8")
                + exclude.read_bytes()
            )
            config = source / ".codex" / "config.toml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(
                'project_doc_fallback_filenames = ["PROJECT_GUIDE.md"]\n',
                encoding="utf-8",
            )
            user_agent = source / ".codex" / "agents" / "user-reviewer.toml"
            user_agent.parent.mkdir(parents=True, exist_ok=True)
            user_agent.write_text('name = "user-reviewer"\n', encoding="utf-8")
            user_skill = source / ".agents" / "skills" / "user-check" / "SKILL.md"
            user_skill.parent.mkdir(parents=True, exist_ok=True)
            user_skill.write_text("---\nname: user-check\n---\n", encoding="utf-8")
            fallback = source / "PROJECT_GUIDE.md"
            fallback.write_text("# Project fallback\n", encoding="utf-8")
            self.assertEqual(harness_eval._git(source, "status", "--porcelain").stdout, "")

            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)

            captured = {item["path"]: item for item in snapshot["projectContextFiles"]}
            self.assertEqual(
                set(captured),
                {
                    ".codex/config.toml",
                    ".codex/agents/user-reviewer.toml",
                    ".agents/skills/user-check/SKILL.md",
                    "PROJECT_GUIDE.md",
                },
            )
            self.assertTrue(snapshot["projectConfigPresent"])
            self.assertFalse(snapshot["projectConfigLoadVerified"])
            self.assertEqual(snapshot["projectAgentConfigCount"], 1)
            self.assertFalse(snapshot["projectAgentLoadVerified"])
            self.assertFalse(snapshot["projectAgentDependenciesVerified"])
            self.assertIn(
                "project-config-load-unverified", snapshot["isolationGaps"]
            )
            self.assertIn(
                "project-agent-load-unverified", snapshot["isolationGaps"]
            )

            baseline = parent / "pair" / "baseline"
            treatment = parent / "pair" / "treatment"
            harness_eval._clone_local_evaluation_arm(source, baseline, commit)
            harness_eval._clone_local_evaluation_arm(source, treatment, commit)
            result = harness_eval._materialize_paired_arms(
                baseline, treatment, snapshot
            )
            self.assertEqual(result["baselineInstruction"], "PROJECT_GUIDE.md")
            self.assertEqual(result["treatmentInstruction"], "AGENTS.md")
            self.assertIn("project-config-load-unverified", result["isolationGaps"])
            self.assertIn("project-agent-load-unverified", result["isolationGaps"])
            force_files = [
                *snapshot["evidenceFiles"],
                *snapshot["projectContextFiles"],
            ]
            baseline_base = harness_eval._prepare_task_base(
                baseline, commit, force_files
            )
            treatment_base = harness_eval._prepare_task_base(
                treatment, commit, force_files
            )
            for root, base_ref in (
                (baseline, baseline_base),
                (treatment, treatment_base),
            ):
                harness_eval._assert_task_base_snapshot_files(
                    root, base_ref, force_files
                )
                for relative, item in captured.items():
                    self.assertEqual((root / relative).read_bytes(), item["data"])

            evaluation_store = store_module.EvaluationStore(parent / "state")
            before = harness_eval._result_fingerprint(
                evaluation_store, baseline, base_ref=baseline_base
            )
            (baseline / ".codex" / "agents" / "user-reviewer.toml").write_text(
                'name = "changed"\n', encoding="utf-8"
            )
            after = harness_eval._result_fingerprint(
                evaluation_store, baseline, base_ref=baseline_base
            )
            self.assertNotEqual(before, after)

    def test_unmanaged_custom_agent_requires_load_and_dependency_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            exclude = source / ".git" / "info" / "exclude"
            exclude.write_bytes(
                b".codex/agents/user-specialist.toml\n" + exclude.read_bytes()
            )
            agent = source / ".codex" / "agents" / "user-specialist.toml"
            agent.parent.mkdir(parents=True, exist_ok=True)
            agent.write_text(
                'name = "user-specialist"\ndescription = "User-owned specialist"\n',
                encoding="utf-8",
            )
            self.assertEqual(harness_eval._git(source, "status", "--porcelain").stdout, "")

            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)

            self.assertFalse(snapshot["projectConfigPresent"])
            self.assertEqual(snapshot["projectAgentConfigCount"], 1)
            self.assertFalse(snapshot["projectAgentLoadVerified"])
            self.assertFalse(snapshot["projectAgentDependenciesVerified"])
            self.assertEqual(
                snapshot["isolationGaps"], ["project-agent-load-unverified"]
            )
            self.assertIn(
                ".codex/agents/user-specialist.toml",
                {item["path"] for item in snapshot["projectContextFiles"]},
            )

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
            self.assertEqual(
                removed["isolationGaps"],
                ["baseline-instruction-provenance-unavailable"],
            )

    def test_baseline_removal_deletes_generated_only_instruction_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            manifest = root / ".harness" / "manifest.json"
            manifest.parent.mkdir(parents=True)
            block = (
                f"{harness_eval.harness_state.BEGIN_MARKER}\nmanaged\n"
                f"{harness_eval.harness_state.END_MARKER}"
            )
            agents.write_text(f"{block}\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {"managedFiles": [{"path": "AGENTS.md", "kind": "managed-block"}]}
                ),
                encoding="utf-8",
            )

            removed = harness_eval._remove_managed_baseline(root)

            harness_eval._assert_baseline_isolated(root, removed)
            self.assertFalse(agents.exists())
            self.assertEqual(removed["isolationGaps"], [])

    def test_untracked_evidence_is_materialized_in_both_clone_arms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)
            evidence = {
                "path": "private/context.txt",
                "data": b"local evidence\n",
                "mode": 0o640,
                "contentSha256": types.digest_bytes(b"local evidence\n"),
                "tracked": False,
            }
            snapshot["evidenceFiles"].append(evidence)
            baseline = parent / "pair" / "baseline"
            treatment = parent / "pair" / "treatment"
            harness_eval._clone_local_evaluation_arm(source, baseline, commit)
            harness_eval._clone_local_evaluation_arm(source, treatment, commit)
            for root in (baseline, treatment):
                target = root / evidence["path"]
                target.parent.mkdir(parents=True)
                target.write_bytes(b"stale local material\n")

            result = harness_eval._materialize_paired_arms(
                baseline, treatment, snapshot
            )
            for root in (baseline, treatment):
                self.assertEqual((root / evidence["path"]).read_bytes(), evidence["data"])
            self.assertEqual(result["isolationGaps"], [])

            harness_eval._prepare_task_base(baseline, commit)
            harness_eval._prepare_task_base(treatment, commit)
            for root in (baseline, treatment):
                self.assertEqual((root / evidence["path"]).read_bytes(), evidence["data"])
                self.assertEqual(harness_eval._git(root, "status", "--porcelain").stdout, "")

    def test_evidence_preflight_checks_both_arms_before_first_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)
            evidence = {
                "path": "private/context.txt",
                "data": b"local evidence\n",
                "mode": 0o640,
                "contentSha256": types.digest_bytes(b"local evidence\n"),
                "tracked": False,
            }
            snapshot["evidenceFiles"].append(evidence)
            baseline = parent / "pair" / "baseline"
            treatment = parent / "pair" / "treatment"
            harness_eval._clone_local_evaluation_arm(source, baseline, commit)
            harness_eval._clone_local_evaluation_arm(source, treatment, commit)
            (treatment / "private" / "context.txt").mkdir(parents=True)

            with self.assertRaisesRegex(types.EvaluationError, "not a regular file"):
                harness_eval._materialize_paired_arms(
                    baseline, treatment, snapshot
                )

            self.assertFalse((baseline / evidence["path"]).exists())

    def test_evidence_preflight_rejects_symlink_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source, commit = self._local_only_repository(parent)
            snapshot = harness_eval._capture_local_harness_snapshot(source, commit)
            snapshot["evidenceFiles"].append(
                {
                    "path": "private/context.txt",
                    "data": b"local evidence\n",
                    "mode": 0o640,
                    "contentSha256": types.digest_bytes(b"local evidence\n"),
                    "tracked": False,
                }
            )
            baseline = parent / "pair" / "baseline"
            treatment = parent / "pair" / "treatment"
            harness_eval._clone_local_evaluation_arm(source, baseline, commit)
            harness_eval._clone_local_evaluation_arm(source, treatment, commit)
            external = parent / "external"
            external.mkdir()
            try:
                (treatment / "private").symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("creating symlinks may require Windows developer mode")

            with self.assertRaisesRegex(
                types.EvaluationError, "symlink or reparse point"
            ):
                harness_eval._materialize_paired_arms(
                    baseline, treatment, snapshot
                )

            self.assertFalse((baseline / "private" / "context.txt").exists())

    def test_arm_task_bases_exclude_harness_preparation_from_task_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            baseline = parent / "baseline"
            treatment = parent / "treatment"
            source.mkdir()
            subprocess.run(["git", "init", str(source)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Fixture"], check=True)
            (source / "src").mkdir()
            (source / "src" / "parser.py").write_text("value = 1\n", encoding="utf-8")
            managed = source / ".codex" / "agents" / "reviewer.toml"
            managed.parent.mkdir(parents=True)
            managed.write_text("name = 'reviewer'\n", encoding="utf-8")
            block = (
                f"{harness_eval.harness_state.BEGIN_MARKER}\nmanaged\n"
                f"{harness_eval.harness_state.END_MARKER}"
            )
            (source / "AGENTS.md").write_text(f"user\n{block}\n", encoding="utf-8")
            manifest = source / ".harness" / "manifest.json"
            manifest.parent.mkdir()
            manifest.write_text(json.dumps({
                "managedFiles": [
                    {"path": "AGENTS.md", "kind": "managed-block"},
                    {"path": ".codex/agents/reviewer.toml", "kind": "file"},
                ]
            }), encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            original_commit = subprocess.run(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8",
            ).stdout.strip()
            subprocess.run(["git", "clone", "--quiet", str(source), str(baseline)], check=True)
            subprocess.run(["git", "clone", "--quiet", str(source), str(treatment)], check=True)

            removed = harness_eval._remove_managed_baseline(baseline)
            harness_eval._assert_baseline_isolated(baseline, removed)
            baseline_base = harness_eval._prepare_task_base(baseline, original_commit)
            treatment_base = harness_eval._prepare_task_base(treatment, original_commit)
            for root, task_base in ((baseline, baseline_base), (treatment, treatment_base)):
                parent_commit = subprocess.run(
                    ["git", "-C", str(root), "rev-parse", f"{task_base}^"],
                    check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                ).stdout.strip()
                self.assertEqual(parent_commit, original_commit)
                self.assertFalse(subprocess.run(
                    ["git", "-C", str(root), "status", "--porcelain"],
                    check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                ).stdout.strip())
            self.assertNotEqual(
                subprocess.run(
                    ["git", "-C", str(baseline), "rev-parse", f"{baseline_base}^{{tree}}"],
                    check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                ).stdout,
                subprocess.run(
                    ["git", "-C", str(treatment), "rev-parse", f"{treatment_base}^{{tree}}"],
                    check=True, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                ).stdout,
            )

            (baseline / "src" / "parser.py").write_text("value = 2\n", encoding="utf-8")
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(baseline)
            patch_scope = harness_patch_scope.evaluate(
                root=baseline,
                profile={
                    "schemaVersion": 1,
                    "id": "parser-only",
                    "allowedScopes": ["src/**"],
                    "allowUntracked": False,
                    "maximumChangedPaths": 1,
                    "maximumAddedLines": 10,
                    "maximumDeletedLines": 10,
                },
                repository_id=repository_id,
                store=evaluation_store,
                base_ref=baseline_base,
            )
            self.assertEqual(patch_scope["changedTrackedCount"], 1)
            self.assertTrue(patch_scope["withinDeclaredScope"])
            record = harness_eval._new_record(
                evaluation_store=evaluation_store,
                root=baseline,
                repository_id=repository_id,
                prompt=b"task",
                capture_mode="runtime-instrumented",
                args=type("Args", (), {"execution_class": "unknown"})(),
                arm="baseline",
                comparison_id=uuid_text(800),
                pair_id=uuid_text(801),
                arm_order="first",
                source_snapshot_id_override=f"git:{original_commit}",
            )
            self.assertEqual(
                record["repository"]["sourceSnapshotId"],
                f"git:{original_commit}",
            )
            self.assertIsNotNone(
                harness_eval._result_fingerprint(
                    evaluation_store, baseline, base_ref=baseline_base
                )
            )

    def test_non_mutating_verification_preserves_complete_comparability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, base_ref = self._verification_repository(parent)
            (root / "src.py").write_text("value = 2\n", encoding="utf-8")
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(root)
            task_fingerprint = harness_eval._result_fingerprint(
                evaluation_store, root, base_ref=base_ref
            )
            pre_signature = harness_eval._repository_state_signature(
                evaluation_store, root, base_ref=base_ref
            )
            result, cleanup_verified = harness_eval._run_verification(
                root=root,
                profile={
                    "id": "no-write",
                    "kind": "custom",
                    "argv": [sys.executable, "-c", "pass"],
                    "timeoutSeconds": 10,
                },
                profile_digest=HASH,
                check_ref="check:" + "4" * 32,
            )
            post_fingerprint = harness_eval._result_fingerprint(
                evaluation_store, root, base_ref=base_ref
            )
            post_signature = harness_eval._repository_state_signature(
                evaluation_store, root, base_ref=base_ref
            )
            record = manual_record(repository_id, uuid_text(2), arm="baseline")
            harness_eval._record_verification_repository_state(
                record,
                pre_verification_signature=pre_signature,
                post_verification_signature=post_signature,
                quiescent=True,
            )
            self.assertEqual(result["result"], "passed")
            self.assertEqual(cleanup_verified, os.name != 'nt')
            self.assertEqual(task_fingerprint, post_fingerprint)
            self.assertEqual(pre_signature, post_signature)
            self.assertEqual(record["comparison"]["isolationStatus"], "complete")
            self.assertNotIn(
                "verification-repository-state-mutated",
                record["comparison"]["isolationGaps"],
            )

    def test_verification_tracked_and_untracked_mutations_are_partial(self) -> None:
        cases = {
            "tracked": "from pathlib import Path; Path('src.py').write_text('verification = 1\\n', encoding='utf-8')",
            "untracked": "from pathlib import Path; Path('generated.txt').write_text('verification\\n', encoding='utf-8')",
        }
        for label, command in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, base_ref = self._verification_repository(parent)
                (root / "src.py").write_text("value = 2\n", encoding="utf-8")
                evaluation_store = store_module.EvaluationStore(parent / "state")
                repository_id = evaluation_store.register_repository(root)
                task_fingerprint = harness_eval._result_fingerprint(
                    evaluation_store, root, base_ref=base_ref
                )
                record = manual_record(repository_id, uuid_text(2), arm="baseline")
                harness_eval._set_result_fingerprint(record, task_fingerprint)
                pre_signature = harness_eval._repository_state_signature(
                    evaluation_store, root, base_ref=base_ref
                )
                result, cleanup_verified = harness_eval._run_verification(
                    root=root,
                    profile={
                        "id": f"mutate-{label}",
                        "kind": "custom",
                        "argv": [sys.executable, "-c", command],
                        "timeoutSeconds": 10,
                    },
                    profile_digest=HASH,
                    check_ref="check:" + "4" * 32,
                )
                post_fingerprint = harness_eval._result_fingerprint(
                    evaluation_store, root, base_ref=base_ref
                )
                post_signature = harness_eval._repository_state_signature(
                    evaluation_store, root, base_ref=base_ref
                )
                harness_eval._record_verification_repository_state(
                    record,
                    pre_verification_signature=pre_signature,
                    post_verification_signature=post_signature,
                    quiescent=True,
                )
                self.assertEqual(result["result"], "passed")
                self.assertEqual(cleanup_verified, os.name != 'nt')
                self.assertNotEqual(task_fingerprint, post_fingerprint)
                self.assertEqual(
                    record["result"]["resultFingerprint"]["value"],
                    task_fingerprint,
                )
                self.assertEqual(record["comparison"]["isolationStatus"], "partial")
                self.assertIn(
                    "verification-repository-state-mutated",
                    record["comparison"]["isolationGaps"],
                )
                comparison = compare.compare_runs(
                    baseline=types.seal_record(record),
                    treatment=manual_record(
                        repository_id, uuid_text(3), arm="harness"
                    ),
                    plan=ComparisonTests().comparison_plan(),
                    comparison_id=uuid_text(10),
                    pair_id=uuid_text(500),
                    repository_id=repository_id,
                    created_at="2026-08-31T12:02:00Z",
                )
                self.assertEqual(comparison["isolationStatus"], "partial")
                self.assertIn(
                    "baseline-verification-repository-state-mutated",
                    comparison["isolationGaps"],
                )

    def test_verification_index_and_head_mutations_are_partial(self) -> None:
        cases = {
            "index": ["git", "add", "-A"],
            "head": ["git", "commit", "-am", "verification commit"],
        }
        for label, argv in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, base_ref = self._verification_repository(parent)
                (root / "src.py").write_text("value = 2\n", encoding="utf-8")
                evaluation_store = store_module.EvaluationStore(parent / "state")
                repository_id = evaluation_store.register_repository(root)
                task_fingerprint = harness_eval._result_fingerprint(
                    evaluation_store, root, base_ref=base_ref
                )
                pre_signature = harness_eval._repository_state_signature(
                    evaluation_store, root, base_ref=base_ref
                )
                result, cleanup_verified = harness_eval._run_verification(
                    root=root,
                    profile={
                        "id": f"mutate-{label}",
                        "kind": "custom",
                        "argv": argv,
                        "timeoutSeconds": 10,
                    },
                    profile_digest=HASH,
                    check_ref="check:" + "4" * 32,
                )
                post_fingerprint = harness_eval._result_fingerprint(
                    evaluation_store, root, base_ref=base_ref
                )
                post_signature = harness_eval._repository_state_signature(
                    evaluation_store, root, base_ref=base_ref
                )
                record = manual_record(repository_id, uuid_text(2), arm="baseline")
                harness_eval._set_result_fingerprint(record, task_fingerprint)
                harness_eval._record_verification_repository_state(
                    record,
                    pre_verification_signature=pre_signature,
                    post_verification_signature=post_signature,
                    quiescent=True,
                )
                self.assertEqual(result["result"], "passed")
                self.assertEqual(cleanup_verified, os.name != 'nt')
                self.assertEqual(task_fingerprint, post_fingerprint)
                self.assertNotEqual(pre_signature, post_signature)
                self.assertEqual(record["comparison"]["isolationStatus"], "partial")
                self.assertIn(
                    "verification-repository-state-mutated",
                    record["comparison"]["isolationGaps"],
                )

    def test_non_quiescent_verification_is_partial(self) -> None:
        record = manual_record(uuid_text(1), uuid_text(2), arm="baseline")
        harness_eval._record_verification_repository_state(
            record,
            pre_verification_signature=HASH,
            post_verification_signature=HASH,
            quiescent=False,
        )
        self.assertEqual(record["comparison"]["isolationStatus"], "partial")
        self.assertIn(
            "verification-repository-state-mutated",
            record["comparison"]["isolationGaps"],
        )

    def test_verification_timeout_terminates_the_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, cleanup_verified = harness_eval._run_verification(
                root=Path(directory),
                profile={
                    "id": "timeout",
                    "kind": "custom",
                    "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
                    "timeoutSeconds": 0.1,
                },
                profile_digest=HASH,
                check_ref="check:" + "4" * 32,
            )
            self.assertEqual(result["result"], "failed")
            self.assertEqual(result["exitCode"]["state"], "unavailable")
            self.assertEqual(cleanup_verified, os.name != 'nt')

    @unittest.skipIf(os.name == "nt", "Windows process-tree assurance is receipt-gated")
    def test_verification_timeout_terminates_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = (
                "import time; from pathlib import Path; "
                "time.sleep(0.5); Path('escaped.txt').write_text('escaped', encoding='utf-8')"
            )
            parent = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                "time.sleep(60)"
            )
            _, cleanup_verified = harness_eval._run_verification(
                root=root,
                profile={
                    "id": "descendant-timeout",
                    "kind": "custom",
                    "argv": [sys.executable, "-c", parent],
                    "timeoutSeconds": 0.2,
                },
                profile_digest=HASH,
                check_ref="check:" + "4" * 32,
            )
            time.sleep(0.7)
            self.assertEqual(cleanup_verified, os.name != 'nt')
            self.assertFalse((root / "escaped.txt").exists())


class ResultFingerprintTests(unittest.TestCase):
    def test_fingerprint_rejects_mismatched_complete_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evaluation_store = store_module.EvaluationStore(Path(directory) / "state")
            with mock.patch.object(
                harness_eval,
                "_collect_result_fingerprint_payload",
                side_effect=[b"first", b"second"],
            ):
                self.assertIsNone(
                    harness_eval._result_fingerprint(
                        evaluation_store, Path(directory) / "repo"
                    )
                )

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

    def test_repository_state_signature_detects_index_and_head_only_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            state = Path(directory) / "state"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            base_ref = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            ).stdout.strip()
            evaluation_store = store_module.EvaluationStore(state)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            content_before = harness_eval._result_fingerprint(
                evaluation_store, root, base_ref=base_ref
            )
            unstaged = harness_eval._repository_state_signature(
                evaluation_store, root, base_ref=base_ref
            )
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            staged = harness_eval._repository_state_signature(
                evaluation_store, root, base_ref=base_ref
            )
            content_staged = harness_eval._result_fingerprint(
                evaluation_store, root, base_ref=base_ref
            )
            subprocess.run(["git", "-C", str(root), "commit", "-m", "changed"], check=True, stdout=subprocess.DEVNULL)
            committed = harness_eval._repository_state_signature(
                evaluation_store, root, base_ref=base_ref
            )
            content_committed = harness_eval._result_fingerprint(
                evaluation_store, root, base_ref=base_ref
            )
            self.assertEqual(content_before, content_staged)
            self.assertEqual(content_staged, content_committed)
            self.assertEqual(len({unstaged, staged, committed}), 3)

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
        legacy["runtime"].pop("evaluationContract", None)
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
            repository_id=uuid_text(1), proposal_id=uuid_text(30), created_at="2026-08-31T12:03:00Z", comparisons=comparisons,
            comparison_plan=plan,
        )
        self.assertEqual(proposal["proposalType"], "experiment-suggestion")
        self.assertEqual(proposal["candidateDelta"]["attributionScope"], "none")

    def test_bundle_proposal_preserves_the_observed_factor_set(self) -> None:
        tests = ComparisonTests()
        plan = tests.comparison_plan()
        plan["intervention"] = {"expectedChangedFactors": ["agent-set", "skill-set"], "attributionTarget": "bundle"}
        comparisons = []
        for number in range(10, 15):
            pair_id = uuid_text(500 + number)
            baseline = manual_record(
                uuid_text(1), uuid_text(1000 + number), arm="baseline",
                verification="failed", pair_id=pair_id,
            )
            treatment = manual_record(
                uuid_text(1), uuid_text(2000 + number), arm="harness",
                verification="passed", pair_id=pair_id,
            )
            treatment["configuration"]["declaredConfiguration"]["skills"] = schema2.reference_set(
                ["skill:" + "6" * 32], state="measured", source="run-configuration-snapshot", fidelity="exact", completeness="complete"
            )
            treatment = types.seal_record(treatment)
            comparisons.append(compare.compare_runs(
                baseline=baseline, treatment=treatment, plan=plan,
                comparison_id=uuid_text(number), pair_id=pair_id, repository_id=uuid_text(1),
                created_at="2026-08-31T12:02:00Z",
            ))
        proposal = propose.proposal_from_comparisons(
            repository_id=uuid_text(1), proposal_id=uuid_text(30), created_at="2026-08-31T12:03:00Z", comparisons=comparisons,
            comparison_plan=plan, eligibility=verified_eligibility(comparisons, plan),
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
            successor = evaluation_store.repository_root(repository_id) / "annotations" / uuid_text(2) / f"{uuid_text(22)}.json"
            original = successor.read_bytes()
            for corrupt in (b'{', b'[]', b'{}'):
                with self.subTest(corrupt=corrupt):
                    successor.write_bytes(corrupt)
                    with self.assertRaisesRegex(store_module.StoreError, "invalid"):
                        evaluation_store.annotations_for_run(repository_id, uuid_text(2))
                    with self.assertRaisesRegex(store_module.StoreError, "invalid"):
                        evaluation_store.add_annotation(repository_id, annotation(uuid_text(23), uuid_text(20)))
                    self.assertEqual(successor.read_bytes(), corrupt)
                    self.assertTrue(evaluation_store.repair_repository(repository_id)["invalid"])
                    self.assertEqual(evaluation_store.export_repository(repository_id)["excludedCount"], 1)
            successor.write_bytes(original)

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
            successor = evaluation_store.repository_root(repository_id) / "observations" / f"{uuid_text(12)}.json"
            original = successor.read_bytes()
            wrong_hash = json.loads(original)
            wrong_hash["integrity"]["recordSha256"] = "0" * 64
            for corrupt in (b'{', b'[]', b'{}', json.dumps(wrong_hash).encode()):
                with self.subTest(corrupt=corrupt):
                    successor.write_bytes(corrupt)
                    with self.assertRaisesRegex(store_module.StoreError, "invalid"):
                        evaluation_store.observations_for_run(repository_id, uuid_text(2))
                    with self.assertRaisesRegex(store_module.StoreError, "invalid"):
                        evaluation_store.add_observation(repository_id, observation_record(repository_id, uuid_text(2), uuid_text(15), kind="replacement", supersedes=uuid_text(11)))
                    report = evaluation_store.repair_repository(repository_id)
                    self.assertEqual(len(report["invalid"]), 1)
                    self.assertEqual(report["quarantined"], 0)
                    self.assertEqual(successor.read_bytes(), corrupt)
                    self.assertEqual(evaluation_store.export_repository(repository_id)["excludedCount"], 1)
            successor.write_bytes(original)
            self.assertEqual(evaluation_store.repair_repository(repository_id)["invalid"], [])
            successor.write_bytes(b'{')
            self.assertEqual(evaluation_store.repair_repository(repository_id, quarantine=True)["quarantined"], 1)
            self.assertFalse(successor.exists())
            self.assertEqual(len(evaluation_store.observations_for_run(repository_id, uuid_text(2))), 2)

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
    def test_untracked_file_makes_line_budget_measurement_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repo"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / "reports").mkdir()
            (root / "reports" / "base.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, stdout=subprocess.DEVNULL)
            (root / "reports" / "large.txt").write_text("line\n" * 10_000, encoding="utf-8")
            evaluation_store = store_module.EvaluationStore(parent / "state")
            repository_id = evaluation_store.register_repository(root)
            result = harness_patch_scope.evaluate(
                root=root,
                profile={
                    "schemaVersion": 1,
                    "id": "reports",
                    "allowedScopes": ["reports/**"],
                    "allowUntracked": True,
                    "maximumChangedPaths": 2,
                    "maximumAddedLines": 100,
                    "maximumDeletedLines": None,
                },
                repository_id=repository_id,
                store=evaluation_store,
            )
            self.assertTrue(result["withinDeclaredScope"])
            self.assertEqual(result["untrackedCount"], 1)
            self.assertEqual(result["completeness"], "partial")

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
