"""P0 synthetic-DXF algorithm and simulated transaction tests; no live SW."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src')]
import ezdxf
from cad_analyzer import analyze_dxf
from sheet_metal_pipeline import (build_plan, run_plan, MockSheetMetalPort,
                                 validate_native, diagnose_k_change)
from solidworks_generator import _com_read, export_flat_pattern_dxf


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'synthetic.dxf'
        doc = ezdxf.new('R2010')
        doc.units = ezdxf.units.MM
        space = doc.modelspace()
        space.add_lwpolyline([(0,0),(100,0),(100,80),(0,80)], close=True)
        space.add_circle((20,20), 4)
        doc.layers.new('BEND', dxfattribs={'color':1})
        space.add_line((50,0),(50,80), dxfattribs={'layer':'BEND','color':1})
        doc.saveas(self.source)
        self.analysis = analyze_dxf(self.source)
        self.outer = max(range(len(self.analysis.profiles)), key=lambda i: len(self.analysis.profiles[i].points) if self.analysis.profiles[i].kind != 'CIRCLE' else 0)

    def plan(self, **kwargs):
        params = dict(profile_index=self.outer, thickness_mm=2.5, radius_mm=1,
                      angle_degrees=90, k_factor=.4, flip_direction=False, bends_confirmed=True)
        params.update(kwargs)
        return build_plan(self.analysis, **params)

    def test_native_feature_plan_reuses_holes_bends_and_relief_rules(self):
        plan = self.plan(relief_bend_indices=(0,))
        self.assertEqual(plan['status'], 'ready_for_windows')
        self.assertEqual(len(plan['hole_indices']), 1)
        self.assertEqual(plan['bend_indices'], [0])
        self.assertEqual(plan['relief_rule']['width_mm'], 2.5)
        self.assertEqual(plan['relief_rule']['depth_past_centerline_mm'], 4)
        self.assertIn('native_base_flange', plan['feature_plan'])
        self.assertFalse(plan['sw_live_verified'])

    def test_missing_values_and_units_are_pending(self):
        plan = self.plan(k_factor=None, flip_direction=None)
        self.assertIn('bend_line_classification', self.plan(bends_confirmed=False)['pending'])
        self.assertIn('k_factor', plan['pending'])
        self.assertIn('bend_direction', plan['pending'])
        analysis = replace(self.analysis, units_name='未指定（按毫米显示）')
        self.assertIn('source_units', build_plan(analysis)['pending'])
        self.assertEqual(run_plan(self.analysis, plan, self.root/'out', MockSheetMetalPort())['status'], 'pending')

    def test_invalid_parameters_and_reliefs(self):
        for updates in ({'thickness_mm':0}, {'radius_mm':-1}, {'angle_degrees':180},
                        {'k_factor':2}, {'k_factor':True}, {'radius_mm':float('nan')},
                        {'relief_bend_indices':(8,)}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.plan(**updates)

    def test_internal_hole_not_silently_promoted(self):
        hole = self.plan()['hole_indices'][0]
        with self.assertRaises(ValueError):
            self.plan(profile_index=hole)

    def test_dryrun_has_json_only_and_verified_resume(self):
        plan = self.plan()
        first = run_plan(self.analysis, plan, self.root/'out', MockSheetMetalPort())
        self.assertEqual(first['status'], 'simulated_pass')
        self.assertFalse(first['sw_live_verified'])
        self.assertFalse(first['reopen']['editable'])
        out = Path(first['output_dir'])
        self.assertTrue(all(p.suffix == '.json' for p in out.iterdir()))
        second = run_plan(self.analysis, plan, self.root/'out', MockSheetMetalPort())
        self.assertTrue(second['resumed'])
        (out/'part.trace.json').write_text('tampered')
        third = run_plan(self.analysis, plan, self.root/'out', MockSheetMetalPort())
        self.assertEqual(third['status'], 'failed')
        self.assertIn('artifact changed', third['error'])

    def test_source_geometry_and_plan_edits_invalidate(self):
        plan = self.plan()
        changed = dict(plan)
        changed['parameters'] = {**plan['parameters'], 'k_factor':.5}
        with self.assertRaises(ValueError):
            run_plan(self.analysis, changed, self.root/'out', MockSheetMetalPort())
        with self.assertRaises(ValueError):
            run_plan(replace(self.analysis, bend_lines=()), plan, self.root/'out', MockSheetMetalPort())
        self.source.write_text('edited')
        with self.assertRaises(ValueError):
            run_plan(self.analysis, plan, self.root/'out', MockSheetMetalPort())

    def test_failure_each_stage_cleans_only_staged_products(self):
        for fail in ('generate','reopen_inspect','export_flat'):
            port = MockSheetMetalPort()
            setattr(port, fail, lambda *args: (_ for _ in ()).throw(RuntimeError('centerline bend rejected')))
            out = self.root/fail
            out.mkdir()
            original = out/'user.txt'
            original.write_text('keep')
            report = run_plan(self.analysis, self.plan(), out, port)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['recovery'], 'staging_removed')
            self.assertEqual(len(list(out.glob('failure-*.json'))), 1)
            # Issue #19: a crash package with the last checkpoints is kept
            # next to the failure file; staging itself is still removed.
            self.assertEqual(len(list(out.glob('crash-*.json'))), 1)
            crash = json.loads(list(out.glob('crash-*.json'))[0].read_text())
            self.assertEqual(crash['plan_id'], self.plan()['plan_id'])
            self.assertEqual(len(list(out.iterdir())), 3)
            self.assertEqual(original.read_text(), 'keep')

    def test_recovery_failure_is_explicit(self):
        class Broken(MockSheetMetalPort):
            def export_flat(self, *args):
                raise RuntimeError('export failed')
            def abort(self, *args):
                raise RuntimeError('lease lost')
        report = run_plan(self.analysis, self.plan(), self.root/'out', Broken())
        self.assertIn('recovery_required', report['recovery'])
        self.assertTrue(Path(report['diagnostic_stage']).exists())

    def test_native_gate_rejects_incomplete_bend_and_wrong_k(self):
        plan = self.plan()
        evidence = dict(reopened=True, rebuilt=True, feature_types=['SheetMetal','FlatPattern','SMBaseFlange'],
                        editable=True, bend_feature_count=1, thickness_mm=2.5, radius_mm=1, k_factor=.4)
        validate_native(plan, evidence)
        for bad in ({'k_factor':.5}, {'editable':False}, {'rebuilt':False},
                    {'bend_feature_count':0}, {'thickness_mm':None}):
            with self.assertRaises(RuntimeError):
                validate_native(plan, {**evidence, **bad})

    def test_k_changed_flat_unchanged_requires_dimensional_basis(self):
        params = dict(thickness_mm=2.5, radius_mm=1, angle_degrees=90, old_k=.3, new_k=.4,
                      old_flat_mm=100, new_flat_mm=100)
        fixed_blank = diagnose_k_change(**params, geometry_basis='fixed_blank')
        self.assertEqual(fixed_blank['status'], 'consistent_with_formula')
        fixed_legs = diagnose_k_change(**params, geometry_basis='fixed_outside_legs')
        self.assertEqual(fixed_legs['status'], 'mismatch')
        self.assertAlmostEqual(fixed_legs['expected_single_bend_delta_mm'], .3926990817)
        self.assertFalse(fixed_legs['sw_live_verified'])

    def test_pywin32_parameterless_property_and_method(self):
        class Property:
            EditRebuild3 = True
        class Method:
            def EditRebuild3(self):
                return False
        self.assertTrue(_com_read(Property(), 'EditRebuild3'))
        self.assertFalse(_com_read(Method(), 'EditRebuild3'))

    def test_export_refuses_overwrite_before_com(self):
        part = self.root/'part.SLDPRT'
        part.write_text('test fixture only')
        target = self.root/'original.dxf'
        target.write_text('keep')
        from unittest.mock import patch
        with patch('solidworks_generator.on_task_sta', return_value=True):
            with self.assertRaises(FileExistsError):
                export_flat_pattern_dxf(part, target)
        self.assertEqual(target.read_text(), 'keep')


class WindowsBridgeContractTests(unittest.TestCase):
    def test_import_is_lazy_and_linux_execution_refused(self):
        from sheet_metal_windows import WindowsSheetMetalPort
        from unittest.mock import patch
        with patch('sheet_metal_windows.sys.platform', 'linux'):
            with self.assertRaisesRegex(RuntimeError, 'Windows'):
                WindowsSheetMetalPort().guard()

    def test_native_reopen_reads_definition_and_closes_owned_document(self):
        from sheet_metal_windows import WindowsSheetMetalPort
        from unittest.mock import MagicMock, patch
        from types import SimpleNamespace
        from bend_allowance import SW_BEND_ALLOWANCE_K_FACTOR
        lease = MagicMock()
        lease.owned_docs = {}
        lease.foreign_titles = set()
        lease.note_owned_document.side_effect = lambda title, **kwargs: lease.owned_docs.update({title: object()})
        data = SimpleNamespace(Thickness=.0025, BendRadius=.001,
            AccessSelections=lambda *args: True, ReleaseSelectionAccess=lambda: None,
            GetCustomBendAllowance=lambda: SimpleNamespace(Type=SW_BEND_ALLOWANCE_K_FACTOR, KFactor=.4))
        def feature(kind):
            return SimpleNamespace(GetTypeName2=lambda:kind, GetDefinition=lambda:data)
        features = [feature(k) for k in ('SMBaseFlange','SheetMetal','SM3dBend','FlatPattern')]
        model = SimpleNamespace(GetTitle=lambda:'part.SLDPRT', EditRebuild3=True)
        app = SimpleNamespace(OpenDoc6=lambda *args:model)
        port = WindowsSheetMetalPort()
        com = SimpleNamespace(CoInitialize=lambda:None, CoUninitialize=lambda:None)
        win32 = SimpleNamespace(client=SimpleNamespace())
        with patch.object(port, 'guard', return_value=lease), patch.dict(sys.modules, {'pythoncom':com, 'win32com':win32, 'win32com.client':win32.client}), patch('sw_session.require_model_write'), patch('sw_session.close_owned_document') as close, patch('solidworks_generator._connect_task_solidworks', return_value=(app,False)), patch('solidworks_generator.ensure_solidworks_typelib'), patch('solidworks_generator._as_interface', side_effect=lambda module, instance, interface:instance), patch('solidworks_generator._features', return_value=features), patch('sheet_metal_windows.measure_folded_and_flat', return_value={'status':'mock_only'}):
            report = port.reopen_inspect(Path('part.SLDPRT'))
        self.assertTrue(report['reopened'])
        self.assertTrue(report['editable'])
        self.assertTrue(report['rebuilt'])
        self.assertEqual(report['thickness_mm'], 2.5)
        self.assertEqual(report['radius_mm'], 1)
        self.assertEqual(report['k_factor'], .4)
        self.assertEqual(report['bend_feature_count'], 1)
        close.assert_called_once_with(lease, app, 'part.SLDPRT')
