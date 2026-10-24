import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.a01_next.assembly_preflight import preflight_assembly
from src.a01_next.stable_references import validate_references
from src.ql5050px.assembly import inspect_assembly


class AssemblyPreflightTests(unittest.TestCase):
    def payload(self):
        return dict(schema_version=1,units='mm',components=[
            dict(id='base',fixed=True,bbox_mm=[0,0,0,1,1,1]),
            dict(id='slider',bbox_mm=[3,0,0,4,1,1])],
            mates=[dict(a='base',b='slider',type='concentric')],times_s=[0,1],
            linear_motion=[dict(component='slider',velocity_mm_s=[1,0,0])])

    def test_offline_clear_does_not_claim_native(self):
        r=preflight_assembly(self.payload())
        self.assertEqual(r['status'],'offline_consistent')
        self.assertFalse(r['mates_solved'])
        self.assertFalse(r['cad_executed'])

    def test_moving_collision_and_missing_geometry(self):
        p=self.payload();p['linear_motion'][0]['velocity_mm_s']=[-3,0,0]
        self.assertIn('sampled_interference_candidates',[x['kind'] for x in preflight_assembly(p)['issues']])
        p['components'][1].pop('bbox_mm')
        self.assertIn('missing_geometry',[x['kind'] for x in preflight_assembly(p)['issues']])

    def test_clearance_is_applied_at_rest(self):
        p=self.payload();p['clearance_mm']=3
        self.assertTrue(preflight_assembly(p)['assembly']['interference']['candidates'])

    def test_invalid_motion_and_units(self):
        for key,value in [('units','m'),('times_s',[1,0]),('times_s',[0,0]),('times_s',[True]),('times_s',[0]*1001)]:
            p=self.payload();p[key]=value
            with self.subTest(key=key,value=str(value)[:20]),self.assertRaises(ValueError):preflight_assembly(p)
        p=self.payload();p['linear_motion'][0]['component']='base'
        with self.assertRaises(ValueError):preflight_assembly(p)

    def test_suppressed_mate_does_not_remove_other_active_edge(self):
        p=self.payload();p['mates'].append(dict(a='base',b='slider',type='distance',suppressed=True))
        r=inspect_assembly(p['components'],p['mates'])
        self.assertNotIn('unanchored',[x['kind'] for x in r['issues']])

    def test_unsupported_mate_cannot_anchor_component(self):
        p=self.payload();p['mates'][0]['type']='unknown'
        r=inspect_assembly(p['components'],p['mates'])
        self.assertIn('unanchored',[x['kind'] for x in r['issues']])


class StableReferenceTests(unittest.TestCase):
    def record(self):
        return dict(id='slider.axis',document_sha256='a'*64,configuration='Default',
            component_path='A01/slider-1',entity_type='axis',persistent_reference_base64='AQID')

    def test_schema_validation_never_claims_native_resolution(self):
        r=validate_references(dict(schema_version=1,references=[self.record()]))
        self.assertEqual(r['validated_records'],1)
        self.assertFalse(r['native_resolved'])

    def test_ordinal_missing_identity_and_bad_token_rejected(self):
        for key,value in [('persistent_reference_base64',''),('persistent_reference_base64','!!'),
                          ('document_sha256','unknown'),('configuration',''),('entity_type','Face2')]:
            row=self.record();row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_references(dict(schema_version=1,references=[row]))

    def test_duplicate_physical_reference_rejected(self):
        a=self.record();b=copy.deepcopy(a);b['id']='other'
        with self.assertRaises(ValueError):validate_references(dict(schema_version=1,references=[a,b]))
