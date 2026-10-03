from __future__ import annotations

import copy
import unittest

from test_harness_evaluation import (
    HASH, compare, harness_metadata, manual_record, propose, types,
    uuid_text, verified_eligibility,
)


class EvaluationCompatibilityTests(unittest.TestCase):
    def test_previous_measurement_contract_remains_readable_without_retroactive_attribution(self) -> None:
        for version, contract in (("0.32.4-beta", None), ("0.33.0-beta", "schema2-parser1-attribution2"),
                                  ("99.0.0-beta", "schema2-parser1-attribution2")):
            with self.subTest(version=version, contract=contract):
                record = manual_record(uuid_text(1), uuid_text(2), harness_version=version)
                if contract is not None:
                    record["runtime"]["evaluationContract"] = contract
                    record = types.seal_record(record)
                original = copy.deepcopy(record)
                types.validate_run_record(record)
                self.assertFalse(harness_metadata.evaluation_contract_eligible(record))
                self.assertEqual(record, original)

    def test_explicit_contract_decouples_release_and_rejects_unknown_semantics(self) -> None:
        record = manual_record(uuid_text(1), uuid_text(2))
        record["runtime"]["harnessVersion"] = "99.0.0-beta"
        record = types.seal_record(record)
        types.validate_run_record(record)
        self.assertTrue(harness_metadata.evaluation_contract_eligible(record))
        record["runtime"]["harnessVersion"] = harness_metadata.HARNESS_VERSION
        record["runtime"]["evaluationContract"] = "unknown-contract"
        record = types.seal_record(record)
        types.validate_run_record(record)
        self.assertFalse(harness_metadata.evaluation_contract_eligible(record))
        record["runtime"]["harnessVersion"] = "99.0.0-beta"
        with self.assertRaises(types.EvaluationError):
            types.validate_run_record(types.seal_record(record))
        record["runtime"]["harnessVersion"] = harness_metadata.HARNESS_VERSION
        record["runtime"]["evaluationContract"] = harness_metadata.EVALUATION_MEASUREMENT_CONTRACT
        record["capture"]["parserVersion"] = "unknown-parser"
        self.assertFalse(harness_metadata.evaluation_contract_eligible(record))
        legacy = manual_record(uuid_text(1), uuid_text(3), harness_version="6.4")
        self.assertFalse(harness_metadata.evaluation_contract_eligible(legacy))

    def test_faster_or_tied_but_repeatedly_incorrect_is_a_negative_signal(self) -> None:
        plan = {
            "schemaVersion": 2,
            "primaryOutcome": {"metric": "output-tokens", "direction": "lower-is-better", "minimumEffect": 1},
            "correctnessGate": "no-regression",
            "secondaryOutcomes": [],
            "verificationProfileFingerprint": HASH,
            "intervention": {"expectedChangedFactors": ["agent-set"], "attributionTarget": "single-factor"},
            "taskStratum": {"category": "test", "complexityLevel": "unknown", "impactLevel": "unknown",
                            "uncertaintyLevel": "unknown", "scopeClass": "single-file"},
            "patchScopeProfileFingerprint": None,
        }
        for tokens, legacy in ((10, False), (100, False), (10, True), (100, True)):
            with self.subTest(tokens=tokens, legacy=legacy):
                comparisons = []
                for index in range(10):
                    pair_id = uuid_text(500 + index)
                    baseline = manual_record(uuid_text(1), uuid_text(1000 + index), arm="baseline",
                                             output_tokens=100, pair_id=pair_id)
                    treatment = manual_record(uuid_text(1), uuid_text(2000 + index), arm="harness",
                                              output_tokens=tokens, pair_id=pair_id, verification="failed")
                    comparisons.append(compare.compare_runs(
                        baseline=baseline, treatment=treatment, plan=plan,
                        comparison_id=uuid_text(3000 + index), pair_id=pair_id,
                        repository_id=uuid_text(1), created_at="2026-08-31T12:02:00Z",
                    ))
                if legacy:
                    for item in comparisons:
                        item["correctnessGate"].pop("status")
                        if tokens == 100:
                            item["primaryOutcome"]["direction"] = "tie"
                    comparisons = [types.seal_record(item) for item in comparisons]
                result = propose.proposal_from_comparisons(
                    repository_id=uuid_text(1), proposal_id=uuid_text(4000),
                    created_at="2026-08-31T12:03:00Z", comparisons=comparisons,
                    comparison_plan=plan, eligibility=verified_eligibility(comparisons, plan),
                )
                self.assertEqual(result["proposalType"], "negative-signal")
                self.assertEqual(result["evidence"]["supportStrength"], "strong")
                self.assertEqual(result["evidence"]["criticalRegressionCount"], 10)

    def test_isolated_regression_does_not_invent_strong_support(self) -> None:
        strength = propose._support_strength_v2(
            direction="harmful", pair_count=10, non_tie_count=10, direction_count=10,
            median_signed_improvement=90, minimum_effect=1, isolation_ratio=1.0,
            critical_regression=True, isolation_failed=False, confounders=set(),
            correctness_regression_count=1,
        )
        self.assertEqual(strength, "insufficient")

    def test_distinct_adverse_signals_do_not_pool_support(self) -> None:
        plan = {
            "schemaVersion": 2,
            "primaryOutcome": {"metric": "output-tokens", "direction": "lower-is-better", "minimumEffect": 1},
            "correctnessGate": "no-regression", "secondaryOutcomes": [],
            "verificationProfileFingerprint": HASH,
            "intervention": {"expectedChangedFactors": ["agent-set"], "attributionTarget": "single-factor"},
            "taskStratum": {"category": "test", "complexityLevel": "unknown", "impactLevel": "unknown",
                            "uncertaintyLevel": "unknown", "scopeClass": "single-file"},
            "patchScopeProfileFingerprint": None,
        }
        comparisons = []
        for index in range(10):
            pair_id = uuid_text(500 + index)
            baseline = manual_record(uuid_text(1), uuid_text(1000 + index), arm="baseline",
                                     output_tokens=100, pair_id=pair_id)
            treatment = manual_record(uuid_text(1), uuid_text(2000 + index), arm="harness", pair_id=pair_id,
                                      output_tokens=10 if index < 3 else 200 if index < 8 else 90,
                                      verification="failed" if index < 3 else "passed")
            comparisons.append(compare.compare_runs(
                baseline=baseline, treatment=treatment, plan=plan,
                comparison_id=uuid_text(3000 + index), pair_id=pair_id,
                repository_id=uuid_text(1), created_at="2026-08-31T12:02:00Z",
            ))
        result = propose.proposal_from_comparisons(
            repository_id=uuid_text(1), proposal_id=uuid_text(4000),
            created_at="2026-08-31T12:03:00Z", comparisons=comparisons,
            comparison_plan=plan, eligibility=verified_eligibility(comparisons, plan),
        )
        self.assertEqual(result["evidence"]["supportStrength"], "insufficient")
        self.assertEqual(result["candidateDelta"]["attributionScope"], "none")


if __name__ == "__main__":
    unittest.main()
