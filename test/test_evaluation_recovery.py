from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_harness_evaluation as fixtures
from test_harness_evaluation import (
    compare, evaluation_view, harness_eval, manual_record, observation_record,
    persist_completed, schema2, store_module, types, uuid_text,
)


class EvaluationRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = store_module.EvaluationStore(Path(directory.name) / "state")
        self.repository_id = uuid_text(1)

    def interrupted_completion(self):
        record = manual_record(self.repository_id, uuid_text(2))
        unlink = Path.unlink
        def interrupt(path, *args, **kwargs):
            if path.parent.name == "pending":
                raise OSError("fixture: interrupted after completed save")
            return unlink(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", interrupt), self.assertRaises(OSError):
            persist_completed(self.store, record)
        return record, self.store._run_paths(self.repository_id, record["runId"])

    def test_completed_receipt_wins_and_repair_preserves_both_originals(self):
        record, (pending, completed) = self.interrupted_completion()
        pending_bytes = pending.read_bytes()
        completed_identity = (completed.read_bytes(), completed.stat().st_mtime_ns)
        self.assertEqual(self.store.find_run(record["runId"]), (self.repository_id, record))
        listed = self.store.list_runs(self.repository_id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["recordState"], "completed")
        report = self.store.repair_repository(self.repository_id)
        self.assertEqual(report["invalid"], [])
        self.assertEqual(report["completedPending"], [f"runs/pending/{record['runId']}.json"])
        self.assertEqual(pending.read_bytes(), pending_bytes)
        report = self.store.repair_repository(self.repository_id, quarantine=True)
        self.assertEqual(report["quarantined"], 1)
        self.assertFalse(pending.exists())
        retained = list((self.store.repository_root(self.repository_id) / "quarantine").glob("*-pending-*.json"))
        self.assertEqual([path.read_bytes() for path in retained], [pending_bytes])
        self.assertEqual((completed.read_bytes(), completed.stat().st_mtime_ns), completed_identity)
        self.assertEqual(self.store.find_run(record["runId"])[1], record)
        with self.assertRaisesRegex(store_module.StoreError, "immutable"):
            self.store.complete_run(record)

    def test_conflicting_pending_identity_is_reported_not_silently_discarded(self):
        record, (pending, completed) = self.interrupted_completion()
        predecessor = types.load_json(pending)
        predecessor["task"]["taskInstanceId"] = uuid_text(99)
        pending.write_text(types.canonical_text(types.seal_record(predecessor)), encoding="utf-8")
        with self.assertRaisesRegex(store_module.StoreError, "identities disagree"):
            self.store.find_run(record["runId"])
        report = self.store.repair_repository(self.repository_id)
        self.assertEqual(len(report["invalid"]), 1)
        self.assertEqual(report["completedPending"], [])
        self.assertTrue(pending.exists())
        self.assertEqual(types.load_json(completed), record)

    def test_corrupt_completed_file_does_not_quarantine_a_valid_pending_run(self):
        record, (pending, completed) = self.interrupted_completion()
        pending_bytes = pending.read_bytes()
        completed.write_text("{", encoding="utf-8")
        preview = self.store.repair_repository(self.repository_id)
        self.assertEqual([item["path"] for item in preview["invalid"]], [f"runs/completed/{record['runId']}.json"])
        self.assertEqual(self.store.repair_repository(self.repository_id, quarantine=True)["quarantined"], 1)
        self.assertEqual(pending.read_bytes(), pending_bytes)
        self.assertEqual(self.store.find_run(record["runId"])[1]["recordState"], "pending")

    def test_proposal_reads_repository_observations_once_and_next_command_sees_changes(self):
        plan = fixtures.ComparisonTests().comparison_plan()
        comparisons = []
        for index in range(3):
            baseline = manual_record(self.repository_id, uuid_text(10 + index * 2), arm="baseline",
                                     output_tokens=100, pair_id=uuid_text(100 + index))
            treatment = manual_record(self.repository_id, uuid_text(11 + index * 2), arm="harness",
                                      pair_id=uuid_text(100 + index))
            for run in (baseline, treatment):
                persist_completed(self.store, run)
            comparisons.append(compare.compare_runs(
                baseline=baseline, treatment=treatment, plan=plan,
                comparison_id=uuid_text(200 + index), pair_id=uuid_text(100 + index),
                repository_id=self.repository_id, created_at="2026-08-31T12:02:00Z",
            ))
        with mock.patch.object(self.store, "_read_json_records", wraps=self.store._read_json_records) as read:
            harness_eval._proposal_eligibility(
                evaluation_store=self.store, repository_id=self.repository_id, comparisons=comparisons,
                comparison_plan=plan, task_category="test", complexity_level="unknown", impact_level="unknown",
            )
        self.assertEqual(sum(call.args[0].name == "observations" for call in read.call_args_list), 1)
        run_id = comparisons[0]["baselineRunId"]
        before = self.store.evaluation_inputs(self.repository_id, [run_id])
        self.store.add_observation(self.repository_id, observation_record(self.repository_id, run_id, uuid_text(300)))
        after = self.store.evaluation_inputs(self.repository_id, [run_id])
        self.assertEqual(before[run_id][1], [])
        self.assertEqual(len(after[run_id][1]), 1)
        damaged = self.store.repository_root(self.repository_id) / "observations" / f"{uuid_text(301)}.json"
        damaged.write_text("{", encoding="utf-8")
        self.assertIsNone(self.store.evaluation_inputs(self.repository_id, [run_id])[run_id])


class EvaluationReferenceTests(unittest.TestCase):
    def setUp(self):
        self.run = manual_record(uuid_text(1), uuid_text(2))
        self.refs = ["agent:" + digit * 32 for digit in "abc"]
        self.run["configuration"]["expectedExecution"]["agents"] = schema2.reference_set(
            self.refs[:2], state="measured", source="comparison-plan", fidelity="exact", completeness="complete",
        )
        self.run = types.seal_record(self.run)

    def observed(self, number, refs, completeness):
        record = observation_record(uuid_text(1), uuid_text(2), uuid_text(number))
        record["payload"]["observedExecution"]["agents"] = schema2.reference_set(
            refs, state="measured", source="user-report", fidelity="reported", completeness=completeness,
        )
        return types.seal_record(record)

    def test_protocol_comparison_uses_set_membership_and_observation_coverage(self):
        for refs, completeness, mismatch in (
            (list(reversed(self.refs[:2])), "complete", False),
            (self.refs[:1], "partial", False),
            (self.refs[:1], "complete", True),
            (self.refs[2:], "partial", True),
        ):
            with self.subTest(refs=refs, completeness=completeness):
                observation = self.observed(10, refs, completeness)
                original = copy.deepcopy((self.run, observation))
                view = evaluation_view.derived_evaluation_view(self.run, [observation], [])
                self.assertEqual(bool(view["protocolDeviations"]), mismatch)
                effective = evaluation_view.materialize_run_view(self.run, view)
                self.assertEqual(bool(compare._execution_protocol_deviations(effective, "baseline")), mismatch)
                self.assertEqual((self.run, observation), original)

    def test_compatible_partial_observations_merge_without_claiming_completeness(self):
        first = self.observed(10, self.refs[:1], "partial")
        second = self.observed(11, self.refs[1:2], "partial")
        view = evaluation_view.derived_evaluation_view(self.run, [first, second], [])
        selected = view["selectedValues"]["observedExecution.agents"]
        self.assertEqual(selected["refs"], self.refs[:2])
        self.assertEqual(selected["completeness"], "partial")
        self.assertEqual(view["activeConflicts"], [])
        self.assertEqual(len(view["provenanceSummary"]["observedExecution.agents"]["supportingRefs"]), 2)
        complete = self.observed(12, list(reversed(self.refs[:2])), "complete")
        view = evaluation_view.derived_evaluation_view(self.run, [first, complete], [])
        self.assertEqual(view["selectedValues"]["observedExecution.agents"]["completeness"], "complete")
        contradictory = self.observed(13, self.refs[2:], "partial")
        view = evaluation_view.derived_evaluation_view(self.run, [complete, contradictory], [])
        self.assertTrue(view["activeConflicts"])
        self.assertIsNone(view["selectedValues"]["observedExecution.agents"])

    def test_reordered_declared_sets_do_not_invent_an_intervention(self):
        baseline = manual_record(uuid_text(1), uuid_text(2), arm="baseline")
        treatment = copy.deepcopy(baseline)
        for record, refs in ((baseline, self.refs[:2]), (treatment, list(reversed(self.refs[:2])))):
            record["configuration"]["declaredConfiguration"]["agents"]["refs"] = refs
        delta, deviations = compare._configuration_delta(baseline, treatment, {
            "intervention": {"expectedChangedFactors": [], "attributionTarget": "descriptive-only"},
        })
        self.assertEqual(delta["changedFactors"], [])
        self.assertEqual(deviations, [])


if __name__ == "__main__":
    unittest.main()
