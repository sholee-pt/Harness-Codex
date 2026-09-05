from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents" / "skills" / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import harness_apply
import harness_doctor
import harness_eval
import harness_eval_compare as compare
import harness_eval_types as types
import harness_eval_view as evaluation_view
import harness_plan_builder
import harness_teamplay
import harness_usage
import validate_harness
import test_harness_evaluation as evaluation_fixtures
from test_harness_evaluation import manual_record, uuid_text
from test_harness_tools import minimal_plan


def snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*") if path.is_file()
    }


class ActivationDiagnosticsTests(unittest.TestCase):
    def test_both_activation_modes_are_valid_and_diagnostics_do_not_write(self) -> None:
        for instruction in (None, "AGENTS.md", "AGENTS.override.md"):
            with self.subTest(instruction=instruction), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if instruction:
                    (root / instruction).write_bytes(b"User-owned instructions\r\n")
                application = harness_apply.build_application(root, minimal_plan(root))
                harness_apply.apply_application(application)
                before = snapshot(root)
                with mock.patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "harness"}), mock.patch.object(
                    harness_doctor.shutil, "which", return_value=None
                ):
                    report = harness_doctor.diagnose(root)
                self.assertTrue(report["valid"], report["errors"])
                activation = report["activation"]
                self.assertEqual(activation["mode"], "explicit-skill" if instruction else "managed-pointer")
                self.assertEqual(activation["runtimeLoaded"], "not-tested")
                self.assertEqual(activation["invocation"], "$project-harness")
                self.assertFalse(report["codexInvoked"])
                self.assertFalse(report["environment"]["codexCliOnPath"])
                self.assertEqual(before, snapshot(root))
                if instruction:
                    self.assertEqual((root / instruction).read_bytes(), b"User-owned instructions\r\n")

    def test_modified_router_blocks_activation_without_repairing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            router = root / ".agents/skills/project-harness/SKILL.md"
            router.write_text("user edit", encoding="utf-8")
            before = snapshot(root)
            report = harness_doctor.diagnose(root)
            self.assertFalse(report["valid"])
            self.assertEqual(report["activation"]["status"], "blocked")
            self.assertIsNone(report["activation"]["invocation"])
            self.assertEqual(before, snapshot(root))

    def test_missing_installation_never_becomes_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = harness_doctor.diagnose(root)
            self.assertFalse(report["valid"])
            self.assertEqual(report["activation"]["status"], "blocked")
            self.assertEqual(list(root.iterdir()), [])

    def test_wrong_environment_is_reported_without_changing_installation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness_apply.apply_application(harness_apply.build_application(root, minimal_plan(root)))
            with mock.patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "base", "CONDA_PREFIX": "/base"}):
                report = harness_doctor.diagnose(root)
            self.assertFalse(report["valid"])
            self.assertFalse(report["environment"]["harnessCondaEnvironment"])
            self.assertFalse(report["codexInvoked"])


class UsageCoverageTests(unittest.TestCase):
    def record(self) -> dict:
        return manual_record(uuid_text(1), uuid_text(2))

    def selected_record(self, *, completeness: str = "complete") -> dict:
        record = self.record()
        for name, value in zip(harness_usage.TOKEN_METRICS, (100, 80, 0, 0)):
            record["measurements"][name] = types.measurement(
                value, unit="tokens", state="measured", source="codex-jsonl",
                fidelity="exact", completeness=completeness,
            )
        return types.seal_record(record)

    def test_zero_is_measured_and_overlapping_counters_are_never_summed(self) -> None:
        record = self.selected_record()
        view = evaluation_view.derived_evaluation_view(record, [], [])
        original = copy.deepcopy((record, view))
        report = harness_usage.usage_summary(record, view)
        self.assertEqual(report["metrics"]["outputTokens"]["measurement"]["value"], 0)
        self.assertEqual(report["metrics"]["outputTokens"]["selection"], "selected")
        self.assertEqual(report["totalTokens"]["state"], "unavailable")
        self.assertIsNone(report["totalTokens"]["value"])
        self.assertFalse(report["aggregationPerformed"])
        self.assertEqual(report["childUsageCoverage"], "unverified")
        self.assertEqual(report["accountUsageCoverage"], "not-measured")
        self.assertEqual(original, (record, view))

    def test_missing_and_reported_metrics_stay_distinct(self) -> None:
        record = self.record()
        report = harness_usage.usage_summary(record, evaluation_view.derived_evaluation_view(record, [], []))
        self.assertEqual(report["metrics"]["inputTokens"]["selection"], "unavailable")
        self.assertIsNone(report["metrics"]["inputTokens"]["measurement"]["value"])
        output = report["metrics"]["outputTokens"]
        self.assertEqual(output["selection"], "reported-only")
        self.assertEqual(output["measurement"]["fidelity"], "reported")
        self.assertEqual(output["scope"], "unverified")

    def test_partial_stream_does_not_gain_completeness(self) -> None:
        record = self.selected_record(completeness="partial")
        report = harness_usage.usage_summary(record, evaluation_view.derived_evaluation_view(record, [], []))
        self.assertEqual(report["metrics"]["inputTokens"]["measurement"]["completeness"], "partial")

    def test_conflicts_do_not_fall_back_to_a_favorable_raw_value(self) -> None:
        record = self.selected_record()
        view = evaluation_view.derived_evaluation_view(record, [], [])
        view["activeConflicts"].append({"field": "measurements.inputTokens"})
        view["selectedValues"]["measurements.inputTokens"] = None
        metric = harness_usage.usage_summary(record, view)["metrics"]["inputTokens"]
        self.assertEqual(metric["selection"], "conflicted")
        self.assertIsNone(metric["measurement"])

    def test_invalid_record_and_foreign_view_are_rejected(self) -> None:
        record = self.selected_record()
        view = evaluation_view.derived_evaluation_view(record, [], [])
        foreign = {**view, "runId": uuid_text(3)}
        with self.assertRaises(types.EvaluationError):
            harness_usage.usage_summary(record, foreign)
        record["measurements"]["inputTokens"]["value"] = 900
        with self.assertRaises(types.EvaluationError):
            harness_usage.usage_summary(record, view)

    def test_view_command_adds_summary_without_changing_derived_view_or_store(self) -> None:
        record = self.selected_record()
        original = copy.deepcopy(record)
        evaluation_store = mock.Mock()
        evaluation_store.find_run.return_value = (record["repository"]["repositoryId"], record)
        evaluation_store.observations_for_run.return_value = []
        evaluation_store.annotations_for_run.return_value = []
        args = harness_eval.build_parser().parse_args(["view", "--run", record["runId"]])
        output = io.StringIO()
        with mock.patch.object(harness_eval, "_store", return_value=evaluation_store), mock.patch("sys.stdout", output):
            self.assertEqual(harness_eval.command_view(args), 0)
        result = json.loads(output.getvalue())
        self.assertIn("usageSummary", result)
        result.pop("usageSummary")
        self.assertEqual(result, evaluation_view.derived_evaluation_view(record, [], []))
        self.assertEqual(original, record)
        self.assertEqual(
            [call[0] for call in evaluation_store.mock_calls],
            ["find_run", "observations_for_run", "annotations_for_run"],
        )

    def test_separate_usage_metrics_preserve_zero_and_missing_values(self) -> None:
        record = self.selected_record()
        for metric, expected in (("input-tokens", 100), ("cached-input-tokens", 80), ("output-tokens", 0), ("reasoning-output-tokens", 0)):
            self.assertIn(metric, types.PRIMARY_OUTCOMES)
            self.assertEqual(compare.outcome_value(record, metric), expected)
        self.assertIsNone(compare.outcome_value(self.record(), "input-tokens"))

    def test_previous_release_records_remain_readable(self) -> None:
        record = manual_record(uuid_text(1), uuid_text(2), harness_version="7.5")
        types.validate_run_record(record)
        report = harness_usage.usage_summary(record, evaluation_view.derived_evaluation_view(record, [], []))
        self.assertIsNone(report["totalTokens"]["value"])

    def test_new_metrics_work_through_full_comparison_and_missing_is_jointly_unknown(self) -> None:
        for metric, counter in (
            ("input-tokens", "inputTokens"), ("cached-input-tokens", "cachedInputTokens"),
            ("reasoning-output-tokens", "reasoningOutputTokens"), ("output-tokens", "outputTokens"),
        ):
            for coverage in ("complete", "partial", "missing"):
                with self.subTest(metric=metric, coverage=coverage):
                    baseline = manual_record(uuid_text(1), uuid_text(2), arm="baseline")
                    treatment = manual_record(uuid_text(1), uuid_text(3), arm="harness")
                    for record, value in ((baseline, 100), (treatment, 10)):
                        record["measurements"][counter] = types.measurement(
                            value, unit="tokens", state="measured", source="codex-jsonl",
                            fidelity="exact", completeness="complete",
                        )
                    if coverage == "missing":
                        treatment["measurements"][counter] = types.unavailable("tokens")
                    elif coverage == "partial":
                        treatment["measurements"][counter]["completeness"] = "partial"
                    plan = evaluation_fixtures.ComparisonTests().comparison_plan()
                    plan["primaryOutcome"] = {"metric": metric, "direction": "lower-is-better", "minimumEffect": 1}
                    plan["secondaryOutcomes"] = []
                    result = compare.compare_runs(
                        baseline=types.seal_record(baseline), treatment=types.seal_record(treatment),
                        plan=plan, comparison_id=uuid_text(10), pair_id=uuid_text(500),
                        repository_id=uuid_text(1), created_at="2026-08-31T12:02:00Z",
                    )
                    if coverage == "complete":
                        self.assertEqual(result["primaryOutcome"]["delta"], -90)
                        self.assertEqual(result["primaryOutcome"]["completeness"], 1)
                    else:
                        self.assertEqual(result["primaryOutcome"]["direction"], "unknown")
                        self.assertIsNone(result["primaryOutcome"]["baselineValue"])
                        self.assertIsNone(result["primaryOutcome"]["treatmentValue"])
                        self.assertEqual(result["primaryOutcome"]["completeness"], 0)

    def test_cache_counter_can_use_either_explicit_direction(self) -> None:
        for direction in ("higher-is-better", "lower-is-better"):
            plan = evaluation_fixtures.ComparisonTests().comparison_plan()
            plan["primaryOutcome"] = {"metric": "cached-input-tokens", "direction": direction, "minimumEffect": 1}
            baseline = manual_record(uuid_text(1), uuid_text(2), arm="baseline")
            treatment = manual_record(uuid_text(1), uuid_text(3), arm="harness")
            for record, value in ((baseline, 10), (treatment, 20)):
                record["measurements"]["cachedInputTokens"] = types.measurement(
                    value, unit="tokens", state="measured", source="codex-jsonl",
                    fidelity="exact", completeness="complete",
                )
            result = compare.compare_runs(
                baseline=types.seal_record(baseline), treatment=types.seal_record(treatment),
                plan=plan, comparison_id=uuid_text(10), pair_id=uuid_text(500),
                repository_id=uuid_text(1), created_at="2026-08-31T12:02:00Z",
            )
            self.assertEqual(result["primaryOutcome"]["direction"], "beneficial" if direction == "higher-is-better" else "harmful")


class DirectGuidanceCompatibilityTests(unittest.TestCase):
    def test_builder_adds_guidance_and_preserves_old_contract_compatibility(self) -> None:
        draft = json.loads((SCRIPTS.parent / "references/minimal-draft-plan.json").read_text(encoding="utf-8"))
        plan = harness_plan_builder.materialize_plan(draft)
        content = plan["artifacts"][0]["content"]
        harness_teamplay.require_exactly_once(content, harness_teamplay.PROJECT_BLOCK, "router")
        self.assertEqual(content.count(harness_teamplay.DIRECT_EXECUTION_GUIDANCE), 1)
        # A draft based on the current template must not duplicate the advisory.
        draft["artifacts"][0]["content"] += "\n" + harness_teamplay.DIRECT_EXECUTION_GUIDANCE
        repeated = harness_plan_builder.materialize_plan(draft)
        self.assertEqual(repeated["artifacts"][0]["content"].count(harness_teamplay.DIRECT_EXECUTION_GUIDANCE), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_plan = minimal_plan(root)
            self.assertNotIn(harness_teamplay.DIRECT_EXECUTION_GUIDANCE, old_plan["artifacts"][0]["content"])
            harness_apply.apply_application(harness_apply.build_application(root, old_plan))
            self.assertTrue(validate_harness.Validator(root).run()["valid"])


if __name__ == "__main__":
    unittest.main()
