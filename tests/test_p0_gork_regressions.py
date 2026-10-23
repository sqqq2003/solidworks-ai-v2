"""Gork p209 K=0.31 and p248 partial/deepen regressions (mock COM only)."""
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from bend_allowance import BendAllowanceSpec
from solidworks_generator import (GenerationResult, SolidWorksGenerationError,
    _build_custom_bend_allowance, _try_insert_base_flange, _create_bend_feature,
    _verify_sheet_metal_bend_allowance, generate_sheet_metal_with_relief_retries,
    BendRejectedError, rect_relief_extra_mm)
from sheet_metal_pipeline import validate_native
import sw_tool_cli


class GorkRegressions(unittest.TestCase):
    def test_custom_allowance_typed_before_property_writes(self):
        raw, typed = MagicMock(), SimpleNamespace()
        fm = SimpleNamespace(CreateCustomBendAllowance=lambda:raw)
        module = object()
        with patch('solidworks_generator._as_interface', return_value=typed) as cast:
            result = _build_custom_bend_allowance(fm, BendAllowanceSpec('k_factor', k_factor=.25), module)
        cast.assert_called_once_with(module, raw, 'ICustomBendAllowance')
        self.assertIs(result, typed)
        self.assertEqual(result.KFactor, .25)
        self.assertNotIn('KFactor', raw.__dict__)

    def test_allowance_units_bd_ba_and_missing_factory(self):
        for mode, kwargs, field in (('bend_deduction', {'bend_deduction_mm':3.2}, 'BendDeduction'),
                                    ('bend_allowance', {'bend_allowance_mm':4.1}, 'BendAllowance')):
            custom = SimpleNamespace()
            result = _build_custom_bend_allowance(SimpleNamespace(CreateCustomBendAllowance=lambda:custom), BendAllowanceSpec(mode, **kwargs))
            self.assertAlmostEqual(getattr(result, field), list(kwargs.values())[0]/1000)
        with self.assertRaises(SolidWorksGenerationError):
            _build_custom_bend_allowance(SimpleNamespace(), BendAllowanceSpec('k_factor', .5))

    def test_insert_time_base_flange_both_api_versions_receive_custom(self):
        for modern in (True, False):
            fm = MagicMock()
            fm.InsertSheetMetalBaseFlange2.return_value = object() if modern else None
            custom = object()
            spec = BendAllowanceSpec('k_factor', k_factor=.25)
            with patch('solidworks_generator._build_custom_bend_allowance', return_value=custom) as build:
                result = _try_insert_base_flange(fm, .0025, .001, True, spec, 'typed-module')
            self.assertIsNotNone(result)
            build.assert_called_once_with(fm, spec, 'typed-module')
            call = fm.InsertSheetMetalBaseFlange2 if modern else fm.InsertSheetMetalBaseFlange
            self.assertIs(call.call_args.args[9], custom)

    def test_insert_time_sketched_bend_receives_custom(self):
        from cad_analyzer import Primitive
        outer = Primitive(((0,0),(100,0),(100,80),(0,80),(0,0)), True, False, '0','LWPOLYLINE')
        bend = Primitive(((50,0),(50,80)), False, True, 'BEND','LINE')
        analysis = SimpleNamespace(profiles=(outer,), bend_lines=(bend,))
        face = SimpleNamespace(GetBox=lambda:(0,0,0,.1,.08,0),
            GetSurface=lambda:SimpleNamespace(IsPlane=lambda:True),
            GetClosestPointOn=lambda x,y,z:(x,y,z,0,0))
        sketch = SimpleNamespace(Name='bend-sketch')
        custom = object()
        with patch('solidworks_generator._planar_faces_by_area', return_value=[face]), patch('solidworks_generator._fixed_face_pick_candidates', return_value=[(10,10)]), patch('solidworks_generator._create_bend_sketch_on_face', return_value=(sketch,None)), patch('solidworks_generator._build_custom_bend_allowance', return_value=custom), patch('solidworks_generator._try_insert_sheet_metal_bend', return_value=True) as insert, patch('solidworks_generator._auto_bend_deadline', None):
            _create_bend_feature(MagicMock(),MagicMock(),MagicMock(),MagicMock(),MagicMock(),MagicMock(),
                analysis,(0,),(0,0),2.5,1,90,False,bend_allowance=BendAllowanceSpec('k_factor', .25),outer_profile=outer)
        self.assertIs(insert.call_args.args[-1], custom)

    def test_modify_true_but_k_still_031_is_failure(self):
        for k, fails in ((.31,True),(.25,False)):
            custom = SimpleNamespace(Type=BendAllowanceSpec('k_factor').sw_type, KFactor=k)
            data = SimpleNamespace(AccessSelections=lambda *a:True,
                GetCustomBendAllowance=lambda:custom, ReleaseSelectionAccess=MagicMock())
            feature = SimpleNamespace(GetTypeName2=lambda:'SheetMetal',GetDefinition=lambda:data)
            with patch('solidworks_generator._features', return_value=[feature]), patch('solidworks_generator._as_interface', side_effect=lambda m,obj,t:obj):
                if fails:
                    with self.assertRaisesRegex(SolidWorksGenerationError,'readback=0.31'):
                        _verify_sheet_metal_bend_allowance(object(), object(), BendAllowanceSpec('k_factor',.25))
                else:
                    self.assertEqual(_verify_sheet_metal_bend_allowance(object(),object(),BendAllowanceSpec('k_factor',.25)), .25)
            data.ReleaseSelectionAccess.assert_called_once()

    def test_partial_p248_reaches_deepen_steps_before_flat(self):
        steps = []
        flat = GenerationResult(Path('flat.SLDPRT'),0,0,0,(0,)*6,(0,)*6,auto_bent=False)
        def generate(*args, **kw):
            if not kw['auto_bend']:
                return flat
            step = kw['relief_step']
            steps.append((step, rect_relief_extra_mm(step)))
            error = BendRejectedError((108,109), relief_step=step)
            error.completed_bend_count = 2
            raise error
        with patch('solidworks_generator.generate_sheet_metal', side_effect=generate):
            result = generate_sheet_metal_with_relief_retries(MagicMock(),0,(106,107,108,109),2.5,1,90,'out.SLDPRT')
        self.assertEqual(steps, [(0,0),(1,1),(2,1.5)])
        self.assertTrue(result.auto_bend_abandoned)
        self.assertEqual(result.auto_bend_failed_count,4)
        self.assertEqual([r['relief_step'] for r in result.bend_attempts], [0,1,2])
        self.assertTrue(all(r['status'] == 'rejected' for r in result.bend_attempts))
        self.assertTrue(all(r['completed_bend_count'] == 2 for r in result.bend_attempts))

    def test_many_bend_lines_can_be_one_native_feature(self):
        plan = {'bend_indices':[13,14,15,16,27,28], 'parameters':{'thickness_mm':2.5,'radius_mm':1,'k_factor':.25}}
        evidence = dict(reopened=True,rebuilt=True,editable=True,
            feature_types=['SMBaseFlange','SheetMetal','SM3dBend','FlatPattern'],
            bend_feature_count=1,completed_bend_count=6, thickness_mm=2.5,radius_mm=1,k_factor=.25)
        validate_native(plan,evidence)
        with self.assertRaises(RuntimeError):
            validate_native(plan,{**evidence,'completed_bend_count':2})

    def test_existing_cli_k_flag_reaches_generator_and_success_gate(self):
        args = sw_tool_cli.build_parser().parse_args(['--mode','sheet','--input','test.dxf','--out','out.SLDPRT','--profile','1','--thickness','2.5','--radius','1','--k-factor','.25'])
        analysis = SimpleNamespace(profiles=(object(),))
        result = GenerationResult(Path('out.SLDPRT'),0,1,0,(0,)*6,(0,)*6,auto_bent=True,
                                  bend_allowance_verified=True,k_factor_readback=.25)
        with patch('sw_tool_cli.analyze_cad_file',return_value=analysis), patch('sw_tool_cli.outermost_containing_profile_index',return_value=0), patch('batch_export.part_bend_indices',return_value=(0,)), patch('sw_tool_cli.emit') as emit, patch('sw_tool_cli.generate_sheet_metal_with_relief_retries',return_value=result) as generate:
            self.assertEqual(sw_tool_cli.run_sheet(args),0)
            self.assertEqual(generate.call_args.kwargs['bend_allowance'].k_factor,.25)
            self.assertEqual(emit.call_args.kwargs['k_factor_readback'],.25)
            generate.return_value = replace(result, k_factor_readback=.31)
            with self.assertRaisesRegex(RuntimeError,'not verified'):
                sw_tool_cli.run_sheet(args)


class KVariantEvidenceTests(unittest.TestCase):
    def test_k_sticks_equal_flat_needs_dimension_basis(self):
        from k_factor_evidence import audit_variants
        evidence = {'variants':[
            {'k_target':.5,'k_read':.5,'dxf_extents':{'ok':True,'max_extent_mm':431.004}},
            {'k_target':.25,'k_read':.25,'dxf_extents':{'ok':True,'max_extent_mm':431.004}}]}
        self.assertEqual(audit_variants(evidence)['status'], 'pending_dimension_basis')
        fixed = audit_variants(evidence, geometry_basis='fixed_blank')
        self.assertEqual(fixed['status'], 'consistent_fixed_blank_pending_folded_measurements')
        self.assertFalse(fixed['sw_live_verified'])
        legs = audit_variants(evidence, geometry_basis='fixed_outside_legs')
        self.assertEqual(legs['flat_comparison']['status'], 'mismatch')
        evidence['variants'][1]['k_read'] = .31
        self.assertEqual(audit_variants(evidence)['native_k_persistence'], 'mismatch_or_missing')

    def test_native_state_measurement_restores_initial_suppression(self):
        from sheet_metal_windows import measure_folded_and_flat
        state = {'suppressed':True}
        feature = SimpleNamespace(Name='FlatPattern',GetTypeName2=lambda:'FlatPattern',
                                  IsSuppressed=lambda:state['suppressed'])
        model = SimpleNamespace(ClearSelection2=lambda *a:None,
            Extension=SimpleNamespace(SelectByID2=lambda *a:True),
            EditSuppress2=lambda:state.update(suppressed=True),
            EditUnsuppress2=lambda:state.update(suppressed=False), EditRebuild3=True)
        with patch('sw_session.require_model_write'), patch('solidworks_generator._features',return_value=[feature]), patch('solidworks_generator._as_interface',side_effect=lambda m,obj,t:obj), patch('solidworks_generator._body_bounds',side_effect=[(0,0,0,.1,.08,.03),(0,0,0,.12,.08,.0025)]):
            result = measure_folded_and_flat(model,object())
        self.assertTrue(state['suppressed'])
        self.assertEqual(result['folded_bounds'][3],100)
        self.assertEqual(result['flat_bounds'][3],120)

