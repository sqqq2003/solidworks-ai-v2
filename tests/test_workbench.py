import contextlib
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import a01
except ImportError as exc:
    raise unittest.SkipTest(
        "a01.py and data/machine_spec.json are not in the GORK-CLOUD-002 "
        "cloud-safe subset; workbench tests skipped so discovery can continue. "
        f"Not a SolidWorks live test. ({exc})"
    ) from exc


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.spec = a01.read_json(a01.ROOT / 'data' / 'machine_spec.json')

    def test_target_retained_and_unknowns_never_guessed(self):
        result = a01.make_plan(self.spec)
        self.assertEqual(result['target_envelope_mm'], dict(length=1800, width=900, height=1500))
        self.assertEqual(result['status'], 'review_required')
        self.assertIsNone(result['values_mm']['frame_length'])
        self.assertFalse(result['cad_executed'])
        self.assertFalse(result['cad_release_approved'])

    def test_negative_nonfinite_and_bool_dimensions_rejected(self):
        for value in (0, -1, float('nan'), float('inf'), True, '1800'):
            with self.subTest(value=value):
                self.spec['target_envelope_mm']['length'] = value
                with self.assertRaises(ValueError):
                    a01.make_plan(self.spec)

    def test_confirmed_dimensions_resolve_without_evaluating_code(self):
        for node in self.spec['parameter_graph'].values():
            if node['kind'] == 'measured':
                node.update(value_mm=10, confirmed=True, source='synthetic test fixture')
        result = a01.make_plan(self.spec)
        self.assertEqual(result['values_mm']['frame_length'], 1780)
        self.assertEqual(result['values_mm']['frame_width'], 880)
        self.assertEqual(result['values_mm']['column_height'], 1480)
        self.assertEqual(result['status'], 'review_required')

    def test_measured_value_requires_provenance(self):
        self.spec['parameter_graph']['front_allowance']['value_mm'] = 25
        result = a01.make_plan(self.spec)
        self.assertIsNone(result['values_mm']['front_allowance'])

    def test_cycle_and_unknown_dependency_rejected(self):
        with self.assertRaises(ValueError):
            a01.topological_order({'a': {'depends_on': ['b']}, 'b': {'depends_on': ['a']}})
        with self.assertRaises(ValueError):
            a01.topological_order({'a': {'depends_on': ['missing']}})

    def test_invalid_units_rejected(self):
        self.spec['units'] = 'inch'
        with self.assertRaises(ValueError):
            a01.make_plan(self.spec)

    def test_confirmed_range_enforced(self):
        self.spec['parameter_graph']['length']['confirmed_range_mm'] = [100, 1700]
        with self.assertRaises(ValueError):
            a01.make_plan(self.spec)

    def test_impossible_dimension_chain_rejected(self):
        for node in self.spec['parameter_graph'].values():
            if node['kind'] == 'measured':
                node.update(value_mm=2000, confirmed=True, source='synthetic test fixture')
        with self.assertRaises(ValueError):
            a01.make_plan(self.spec)


class CoordinationTests(unittest.TestCase):
    def test_degraded_predecessor_does_not_release_successor(self):
        board = {'tasks': [dict(task_id='first', depends_on=[], status='degraded'),
                           dict(task_id='next', depends_on=['first'], status='queued')]}
        result = a01.queue_snapshot(board)
        self.assertFalse(result['tasks'][1]['ready'])
        self.assertEqual(result['tasks'][1]['blocked_by'], ['first'])
        self.assertFalse(result['external_agents_started'])

    def test_duplicates_rejected(self):
        task = dict(task_id='same', status='queued', depends_on=[])
        with self.assertRaises(ValueError):
            a01.queue_snapshot({'tasks': [task, task.copy()]})

    def test_baseline_copy_hashes_match(self):
        self.assertEqual(a01.verify_baseline()['status'], 'passed')

    def test_plan_exit_code_is_review_required(self):
        out = a01.ROOT / 'reports' / 'test-cli-review.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = a01.main(['plan', '--out', str(out)])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['status'], 'review_required')


if __name__ == '__main__':
    unittest.main()
