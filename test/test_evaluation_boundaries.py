"""Malformed records remain diagnosable and long histories are order independent."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_harness_evaluation import (
    compare, evaluation_view, manual_record, observation_record,
    schema2, store_module, types, uuid_text,
)
import test_harness_evaluation as fixtures


class EvaluationBoundaryTests(unittest.TestCase):
    def malformed_runs(self, repository_id):
        values = []
        for field in ('runtime', 'configuration', 'result'):
            for bad in (None, [], 7, 'not-an-object'):
                value = manual_record(repository_id, uuid_text(10 + len(values)))
                value[field] = bad
                values.append(value)
            value = manual_record(repository_id, uuid_text(10 + len(values)))
            del value[field]
            values.append(value)
        value = manual_record(repository_id, uuid_text(10 + len(values)))
        del value['runtime']['harnessVersion']
        values.append(value)
        return values

    def test_schema_two_run_shape_errors_use_the_evaluation_error_contract(self):
        for value in self.malformed_runs(uuid_text(1)):
            with self.subTest(run=value['runId']):
                original = copy.deepcopy(value)
                with self.assertRaises(types.EvaluationError):
                    schema2.validate_run_record(value, verify_hash=False)
                self.assertEqual(value, original)

    def test_corrupt_run_shapes_do_not_abort_listing_or_read_only_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / 'project'
            project.mkdir()
            store = store_module.EvaluationStore(base / 'state')
            repository_id = store.register_repository(project)
            root = store._ensure_repository_dirs(repository_id)
            records = [manual_record(repository_id, uuid_text(2)), *self.malformed_runs(repository_id)]
            paths = []
            for record in records:
                path = root / 'runs/completed' / (record['runId'] + '.json')
                path.write_text(json.dumps(types.seal_record(record)))
                paths.append(path)
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
            listed = store.list_runs(repository_id)
            self.assertEqual(len(listed), len(records))
            self.assertEqual(sum(item['recordState'] == 'corrupt' for item in listed), len(records) - 1)
            repair = store.repair_repository(repository_id)
            self.assertEqual(len(repair['invalid']), len(records) - 1)
            self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}, before)

    def test_schema_two_comparison_requires_every_additional_field(self):
        repository_id = uuid_text(1)
        comparison = compare.compare_runs(
            baseline=manual_record(repository_id, uuid_text(2), arm='baseline'),
            treatment=manual_record(repository_id, uuid_text(3), arm='harness'),
            plan=fixtures.ComparisonTests().comparison_plan(), comparison_id=uuid_text(4), pair_id=uuid_text(500),
            repository_id=repository_id, created_at='2026-08-31T12:02:00Z',
        )
        for field in ('taskStratum', 'configurationDelta', 'protocolDeviations',
                      'resultFingerprintComplete', 'evaluationStratumFingerprint', 'derivedViewFingerprints'):
            with self.subTest(field=field):
                value = copy.deepcopy(comparison)
                del value[field]
                with self.assertRaisesRegex(types.EvaluationError, 'missing fields'):
                    schema2.validate_comparison_record(value, verify_hash=False)

    def histories(self, size=1200):
        observations, annotations = [], []
        for index in range(size):
            identity = uuid_text(100 + index)
            previous = uuid_text(99 + index) if index else None
            observations.append(observation_record(uuid_text(1), uuid_text(2), identity,
                kind='replacement' if index else 'supplement', supersedes=previous))
            annotations.append(types.seal_record({
                'schemaVersion': 2, 'annotationId': identity, 'repositoryId': uuid_text(1),
                'runId': uuid_text(2), 'createdAt': '2026-08-31T12:05:00Z',
                'supersedesAnnotationId': previous, 'source': 'user', 'acceptance': 'accepted',
                'correctionCount': types.unavailable('count'), 'reopened': False,
                'freeTextStored': False, 'integrity': {'recordSha256': None},
            }))
        return observations, annotations

    def graph(self, values, kind):
        function = evaluation_view.observation_graph if kind == 'observation' else evaluation_view.annotation_state
        return function(values, repository_id=uuid_text(1), run_id=uuid_text(2))

    def test_long_supersession_chains_accept_both_input_orders(self):
        for kind, values in zip(('observation', 'annotation'), self.histories()):
            forward = self.graph(values, kind)
            backward = self.graph(list(reversed(values)), kind)
            self.assertEqual(forward, backward)
            self.assertEqual(forward['conflicts'], [])
            self.assertEqual(len(forward['inactive']), len(values) - 1)
            active = forward['active'][0] if kind == 'observation' else forward['active']
            self.assertEqual(active[kind + 'Id'], values[-1][kind + 'Id'])

    def test_long_cycles_remain_conflicts_in_both_input_orders(self):
        for kind, values in zip(('observation', 'annotation'), self.histories()):
            if kind == 'observation':
                values[0]['lifecycle'] = {'kind': 'replacement', 'supersedesObservationId': values[-1]['observationId']}
            else:
                values[0]['supersedesAnnotationId'] = values[-1]['annotationId']
            values[0] = types.seal_record(values[0])
            for order in (values, list(reversed(values))):
                result = self.graph(order, kind)
                expected = 'supersession-cycle' if kind == 'observation' else 'annotation-cycle'
                self.assertIn(expected, [item['code'] for item in result['conflicts']])
                self.assertFalse(result['active'])


if __name__ == '__main__':
    unittest.main()
