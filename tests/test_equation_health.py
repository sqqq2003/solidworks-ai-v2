import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from src.sw_api.equation_health import analyze_equations
from src.sw_api.equation_repair import assert_isolated, solve_owned_work_copy
from src.sw_api.win32com_backend import _assign_existing_equations

ROOT = Path(__file__).resolve().parents[1]


class Manager:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)
        self.deleted = []
        self.AutomaticSolveOrder = False
    def GetCount(self):
        return len(self.rows)
    def Equation(self, index):
        return self.rows[index]['equation']
    def Value(self, index):
        return self.rows[index]['value']
    def Delete(self, index):
        self.deleted.append(index)
        del self.rows[index]
        return True
    def Add2(self, index, equation, solve):
        self.rows.insert(index, {'index': index, 'equation': equation, 'value': 0})
        return index
    def EvaluateAll(self):
        expected = analyze_equations(self.rows)['expected_mm']
        for row in self.rows:
            name = row['equation'].split('"')[1]
            row['value'] = expected[name]
        return -1


class Model:
    def __init__(self, rows):
        self.manager = Manager(rows)
        self.geometry = {}
        self.follow = True
    def GetEquationMgr(self):
        return self.manager
    def GetPathName(self):
        return r'C:\isolated\model.SLDASM'
    def GetDependencies2(self, *args):
        return ['part', r'C:\isolated\part.SLDPRT']
    def ForceRebuild3(self, top_only):
        if self.follow:
            self.geometry = analyze_equations(self.manager.rows)['expected_mm']
        return True
    def Parameter(self, name):
        if name not in self.geometry:
            return None
        class Dimension:
            SystemValue = self.geometry[name] / 1000
        return Dimension()


class EquationHealthTests(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads((ROOT/'tests/fixtures/equation_contract_synthetic.json').read_text())['equations']

    def test_contract_dump_identifies_forward_refs_and_unverified_geometry(self):
        report = analyze_equations(self.rows)
        self.assertEqual(report['expected_mm']['DeckHeight'], 700)
        self.assertEqual(report['expected_mm']['RollerLong'], 700)
        self.assertTrue(any(x['depends_on'] == 'Length' for x in report['forward_references']))
        self.assertEqual(report['status'], 'review_required')
        self.assertTrue(all(x['status'] == 'unverified' for x in report['linked_dimensions']))

    def test_live_failure_reproduced_without_claiming_geometry(self):
        manager = Manager(self.rows)
        model = Model(self.rows)
        _assign_existing_equations(model, {'Length': 1800, 'Width': 900, 'Height': 1500})
        for row in model.manager.rows:
            name = row['equation'].split('"')[1]
            row['value'] = {'Length':1800,'Width':900,'Height':1500,'DeckHeight':-50,'RollerLong':100}.get(name, row['value'])
        report = analyze_equations(model.manager.rows)
        self.assertEqual(report['expected_mm']['DeckHeight'], 1450)
        self.assertEqual(report['expected_mm']['RollerLong'], 1000)
        self.assertIn('DeckHeight', {x['target'] for x in report['equation_mismatches']})

    def test_owned_explicit_solve_checks_actual_dimensions(self):
        for follow in (True, False):
            model = Model(self.rows)
            model.follow = follow
            with patch('src.sw_api.equation_repair.sys.platform', 'win32'), patch('src.sw_api.win32com_backend._import_sw_session') as session:
                result = solve_owned_work_copy(model, r'C:\isolated', updates={'Length':1800,'Width':900,'Height':1500})
            self.assertEqual(result['status'], 'linked_dimensions_verified_unsaved' if follow else 'geometry_verification_failed')
            self.assertFalse(result['saved'])
            self.assertEqual(result['after']['analysis']['expected_mm']['DeckHeight'], 1450)
            self.assertTrue(session.return_value.require_model_write.called)

    def test_native_solver_error_blocks_even_matching_values(self):
        model = Model(self.rows)
        original = model.manager.EvaluateAll
        def error():
            original()
            return 4
        model.manager.EvaluateAll = error
        with patch('src.sw_api.equation_repair.sys.platform', 'win32'), patch('src.sw_api.win32com_backend._import_sw_session'):
            report = solve_owned_work_copy(model, r'C:\isolated')
        self.assertEqual(report['status'], 'geometry_verification_failed')
        self.assertFalse(report['saved'])

    def test_unknown_dependency_inventory_refused(self):
        for deps in (None, [], ['odd']):
            model = Model(self.rows)
            model.GetDependencies2 = lambda *args: deps
            with self.assertRaises(RuntimeError):
                assert_isolated(model, r'C:\isolated')

    def test_shared_parts_block_before_writes(self):
        model = Model(self.rows)
        model.GetDependencies2 = lambda *args: ['part', r'D:\original\part.SLDPRT']
        with self.assertRaisesRegex(ValueError, 'Pack and Go'):
            assert_isolated(model, r'C:\isolated')
        self.assertFalse(model.manager.deleted)

    def test_delete_failure_and_bad_add_are_not_success(self):
        model = Model(self.rows)
        model.manager.Delete = lambda index: False
        with self.assertRaisesRegex(RuntimeError, 'Delete failed'):
            _assign_existing_equations(model, {'Length': 1800})
        model = Model(self.rows)
        model.manager.Add2 = lambda *args: -1
        with self.assertRaises(RuntimeError):
            _assign_existing_equations(model, {'Length': 1800})

    def test_all_values_validated_before_delete_and_formula_preserved(self):
        model = Model(self.rows)
        for updates in ({'Length':1800, 'Width':float('nan')}, {'DeckHeight':1450}, {'Length':True}):
            with self.assertRaises(ValueError):
                _assign_existing_equations(model, updates)
            self.assertFalse(model.manager.deleted)

    def test_cycle_unknown_and_code_are_pending(self):
        for rhs in ('"Missing"', '"X"', '__import__("os")'):
            report = analyze_equations([{'index':0,'equation':'"X"='+rhs,'value':0}])
            self.assertIn('X', report['pending_formulas'])

    def test_matching_globals_with_stale_dimension_not_verified(self):
        manager = Manager(self.rows)
        manager.EvaluateAll()
        report = analyze_equations(manager.rows, {self.rows[6]['equation'].split('"')[1]:1001})
        self.assertEqual(report['status'], 'review_required')
        self.assertEqual(report['linked_dimensions'][0]['status'], 'mismatch')
