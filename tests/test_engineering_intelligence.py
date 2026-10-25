import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from engineering_intelligence import run_module, build_batch

ROOT=Path(__file__).resolve().parents[1]

def request(name):
    return json.loads((ROOT/'examples'/('issue50-'+name+'.json')).read_text(encoding='utf-8'))


class EngineeringTests(unittest.TestCase):
    def test_all_twelve_callable(self):
        report=build_batch(json.loads((ROOT/'examples/issue50-batch.json').read_text()))
        self.assertEqual(len(report['modules']),12)
        self.assertNotIn('failed',[v['status'] for v in report['modules'].values()])
        self.assertFalse(report['cad_executed'])

    def test_roller_overall(self):
        r=run_module('dimensions',request('dimensions'))
        self.assertEqual(r['after_mm']['barrel'],690)
        self.assertEqual(r['after_mm']['overall'],800)
        for key in ('left','right','diameter','shoulder','bearing'):
            self.assertEqual(r['after_mm'][key],r['before_mm'][key])
        self.assertEqual([v['parameter'] for v in r['changes']],['barrel','overall'])

    def test_protected_target(self):
        r=request('dimensions');r['targets']['diameter']={'value':30,'unit':'mm','source':'test'}
        self.assertEqual(run_module('dimensions',r)['status'],'failed')

    def test_cyclic_dimensions(self):
        r=request('dimensions');r['dimensions'][0]['terms']=[{'dimension':'overall','direction':1}]
        with self.assertRaises(ValueError): run_module('dimensions',r)

    def test_missing_dimension(self):
        r=request('dimensions');del r['dimensions'][0]['value']
        self.assertEqual(run_module('dimensions',r)['status'],'review_required')

    def test_undersize_barrel(self):
        r=request('dimensions');r['targets']['overall']['value']=100
        self.assertEqual(run_module('dimensions',r)['status'],'failed')

    def test_overconstrained_baseline(self):
        r=request('dimensions');r['dimensions'][-1]['value']=999
        self.assertEqual(run_module('dimensions',r)['status'],'failed')

    def test_conflicting_targets(self):
        r=request('dimensions');r['targets']['barrel']={'value':999,'unit':'mm','source':'test'}
        self.assertEqual(run_module('dimensions',r)['status'],'failed')

    def test_missing_reference(self):
        r=request('dimensions');r['dimensions'][-1]['terms'][0]['dimension']='absent'
        self.assertEqual(run_module('dimensions',r)['status'],'failed')

    def test_dimension_datum(self):
        r=request('dimensions');r['dimensions'][0]['datum']='different'
        self.assertEqual(run_module('dimensions',r)['status'],'failed')

    def test_dimension_units(self):
        r=request('dimensions');r['dimensions'][0]['unit']='m'
        with self.assertRaises(ValueError):run_module('dimensions',r)

    def test_signed_fit_tolerance(self):
        r=run_module('tolerances',request('tolerances'))
        self.assertEqual(r['status'],'passed')
        self.assertAlmostEqual(r['worst_case']['minimum_mm'],.02)
        self.assertAlmostEqual(r['worst_case']['maximum_mm'],.05)

    def test_missing_tolerance_never_zero(self):
        r=request('tolerances');del r['dimensions'][0]['tolerance']
        out=run_module('tolerances',r)
        self.assertIsNone(out['worst_case']);self.assertEqual(out['status'],'review_required')

    def test_tolerance_failure(self):
        r=request('tolerances');r['required_interval_mm']=[0,.01]
        self.assertEqual(run_module('tolerances',r)['status'],'failed')

    def test_tolerance_invalid_range(self):
        r=request('tolerances');r['dimensions'][0]['tolerance']['lower']=1
        with self.assertRaises(ValueError):run_module('tolerances',r)

    def test_assembly_offline_never_native_pass(self):
        r=run_module('assembly',request('assembly'))
        self.assertEqual(r['status'],'review_required')
        self.assertFalse(r['native_evidence_independently_verified'])

    def test_invalid_mate(self):
        r=request('assembly');r['mates'][0]['a']='absent'
        self.assertEqual(run_module('assembly',r)['status'],'failed')

    def test_overtravel(self):
        r=request('assembly');r['joints'][0]['position']=200
        self.assertEqual(run_module('assembly',r)['status'],'failed')

    def test_redundancy(self):
        r=request('assembly');m=copy.deepcopy(r['mates'][0]);m['id']='again';r['mates'].append(m)
        self.assertTrue(any('redundant' in v for v in run_module('assembly',r)['issues']))

    def test_stale_native_readback(self):
        r=request('assembly');r['native_readback']={'assembly_sha256':'old'}
        self.assertEqual(run_module('assembly',r)['status'],'failed')

    def test_dependency_propagation(self):
        r=run_module('changes',request('changes'))
        self.assertEqual(set(r['affected']),{'roller','machine','drawing','bom'})
        self.assertFalse(r['rollback']['overwrite_original'])

    def test_deleted_reference(self):
        r=request('changes');r['after']=r['after'][1:]
        self.assertEqual(run_module('changes',r)['status'],'failed')

    def test_change_cycle(self):
        r=request('changes');r['after'][0]['depends_on']=['drawing']
        self.assertEqual(run_module('changes',r)['status'],'failed')

    def test_purchased_change_requires_review(self):
        r=request('changes');r['after'][0]['kind']='purchased'
        self.assertEqual(run_module('changes',r)['status'],'review_required')

    def test_rule_fail_and_no_write(self):
        r=request('review');r['values']['barrel']['value']=100
        out=run_module('review',r)
        self.assertEqual(out['status'],'failed');self.assertFalse(out['automatic_write'])

    def test_rule_scope_confidence(self):
        r=request('review');r['rules'][0]['confidence']=.5
        self.assertEqual(run_module('review',r)['status'],'review_required')

    def test_transmission_analytic_values(self):
        r=run_module('transmission',request('transmission'))
        v=r['calculations'];self.assertAlmostEqual(v['power_W'],37.5)
        self.assertAlmostEqual(v['roller_design_torque_Nm'],6)
        self.assertAlmostEqual(v['speed_mm_s'],200)

    def test_efficiency_and_source(self):
        r=request('transmission');r['inputs']['efficiency']['value']=2
        with self.assertRaises(ValueError):run_module('transmission',r)
        r=request('transmission');del r['inputs']['speed']['source']
        with self.assertRaises(ValueError):run_module('transmission',r)

    def test_transmission_missing(self):
        r=request('transmission');del r['inputs']['ratio']
        self.assertEqual(run_module('transmission',r)['status'],'review_required')

    def test_frame_cut_list(self):
        r=run_module('weldments',request('weldments'))
        self.assertEqual(r['cut_list'][0]['cut_length_mm'],1002)
        self.assertEqual(r['stock_plan'][0]['stock_count'],1)
        self.assertAlmostEqual(r['material_mass_kg']['steel'],300*3008*1e-9*7850)

    def test_member_exceeds_stock(self):
        r=request('weldments');r['profiles'][0]['stock_length']['value']=500
        self.assertEqual(run_module('weldments',r)['status'],'failed')

    def test_weld_connection_invalid(self):
        r=request('weldments');r['connections'][0]['members'].append('absent')
        self.assertEqual(run_module('weldments',r)['status'],'failed')

    def test_cost_waste(self):
        r=run_module('costs',request('costs'));self.assertAlmostEqual(r['total'],50/.9)

    def test_missing_and_expired_price(self):
        for mode in ('missing','expired'):
            r=request('costs')
            if mode=='missing':del r['items'][0]['quote']
            else:r['items'][0]['quote']['valid_until']='2026-10-24'
            out=run_module('costs',r);self.assertIsNone(out['total']);self.assertEqual(out['status'],'review_required')

    def test_currency_and_loss(self):
        r=request('costs');r['items'][0]['quote']['currency']='USD'
        with self.assertRaises(ValueError):run_module('costs',r)
        r=request('costs');r['items'][0]['loss']['value']=1
        with self.assertRaises(ValueError):run_module('costs',r)

    def test_similarity_never_replaces(self):
        r=run_module('similarity',request('similarity'))
        self.assertEqual(len(r['candidates']),1);self.assertFalse(r['automatic_replace'])

    def test_similarity_preserves_small_difference(self):
        r=request('similarity');r['parts'][1]['dimensions']['length']=100.001
        out=run_module('similarity',r)
        self.assertEqual(len(out['candidates']),1);self.assertTrue(out['candidates'][0]['differences'])

    def test_different_interface(self):
        r=request('similarity');r['parts'][1]['interfaces']=['other']
        self.assertEqual(run_module('similarity',r)['candidates'],[])

    def test_change_report_evidence_pending(self):
        r=run_module('change_report',request('change_report'))
        self.assertEqual(r['status'],'review_required');self.assertEqual(len(r['report_sha256']),64)

    def test_proposals_missing_no_best(self):
        r=request('proposals');del r['alternatives'][0]['metrics']['cost']
        out=run_module('proposals',r)
        self.assertIsNone(out['best_scheme']);self.assertEqual(out['comparison'],[])

    def test_instruction_reuses_parser(self):
        out=run_module('instruction',request('instruction'))
        self.assertEqual(out['parsed']['target_overall_mm'],800)
        self.assertFalse(out['native_write_allowed'])

    def test_batch_continues_and_refuses_overwrite(self):
        r={'modules':{'dimensions':{'dimensions':[{'id':'bad'}]},'costs':request('costs')}}
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'run';out=build_batch(r,dest)
            self.assertEqual(out['status'],'failed');self.assertIn('costs',out['modules'])
            self.assertTrue((dest/'HANDOFF.json').is_file())
            with self.assertRaises(FileExistsError):build_batch(r,dest)

    def test_input_unchanged(self):
        r=request('dimensions');before=copy.deepcopy(r);run_module('dimensions',r)
        self.assertEqual(r,before)

    def test_nonfinite_and_bool(self):
        for bad in (True,float('nan'),float('inf')):
            r=request('dimensions');r['dimensions'][0]['value']=bad
            with self.assertRaises(ValueError):run_module('dimensions',r)

    def test_existing_calculator_compatibility(self):
        from ql5050px.mechanical_selection import calculate
        r=calculate('ratio',{'driver':{'value':10,'unit':'count','source':'test'},'driven':{'value':20,'unit':'count','source':'test'}})
        self.assertEqual(r['results']['output_input_ratio'],.5)

    def test_existing_rules_compatibility(self):
        from design_platform.rules import evaluate_rules
        r=request('review');out=evaluate_rules(r['values'],r['rules'])
        self.assertEqual(out['status'],'declared_rules_satisfied')

    def test_existing_bom_compatibility(self):
        from ql5050px.drawing_bom import build_bom
        self.assertEqual(build_bom([{'part_number':'p','material':'steel','quantity':2}])[0]['quantity'],2)


class NativeReviewBridgeTests(unittest.TestCase):
    def payload(self):
        chain=request('dimensions'); bindings=[]; intentions={'parameters':{}}
        for row in chain['dimensions']:
            if row.get('terms'):continue
            name=row['id'];protected=row['role']!='adjustable'
            bindings.append({'parameter':name,'document':'isolated/roller.sldprt','configuration':'Default',
                 'feature':'sketch','dimension':name+'@sketch','unit':'mm','source':'synthetic reviewed mapping',
                 'allowed_range':[1,1000],'component_kind':'fixed' if protected else 'editable','status':'confirmed'})
            intentions['parameters'][name]={'role':row['role'],'source':row['source'],'unit':'mm',
                   'allowed_range':[1,1000],'review_status':'confirmed'}
        return {'chain':chain,'mappings':{'schema_version':1,'parameters':bindings},'intentions':intentions}

    def test_existing_review_gate(self):
        from engineering_intelligence.native_review import prepare_native_review
        out=prepare_native_review(self.payload())
        self.assertTrue(out['review']['review_ready'])
        self.assertEqual(out['derived_readback_required'],{'overall':800})
        self.assertEqual([r['parameter'] for r in out['plan']['changes']],['barrel'])
        self.assertFalse(out['native_write_allowed'])

    def test_protected_mapping_cannot_be_omitted(self):
        from engineering_intelligence.native_review import prepare_native_review
        r=self.payload();r['mappings']['parameters'].pop()
        with self.assertRaises(ValueError): prepare_native_review(r)

    def test_role_cannot_be_reclassified(self):
        from engineering_intelligence.native_review import prepare_native_review
        r=self.payload();r['intentions']['parameters']['diameter']['role']='adjustable'
        with self.assertRaises(ValueError):prepare_native_review(r)

    def test_native_execution_failure_remains_failed(self):
        from engineering_intelligence.native_review import execute_native_review
        from unittest.mock import patch
        with patch('design_platform.native.execute_reviewed_transaction',return_value={'status':'failed','execution_status':'failed'}):
            out=execute_native_review(self.payload(),{},object(),'unused')
        self.assertEqual(out['status'],'failed')
        self.assertFalse(out['manufacturing_approved'])
