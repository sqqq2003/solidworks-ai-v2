"""Focused fixture-only Issue24 checks, never native CAD evidence."""
import json,tempfile,unittest
from copy import deepcopy
from pathlib import Path
from roller_variant import plan_variant,execute_variant
from roller_variant.delivery import export_package


def fixture():
    values={'overall_length':1000,'barrel_length':945,'left_projection':20,'right_projection':35,'shaft_diameter':12,'bearing_diameter':15,'shaft_length':1000}
    return {'units':'mm','target_overall_mm':800,'source_kind':'synthetic_fixture_not_OEM','source_document':'fixture.SLDPRT','configuration':'Default','axis':'x',
        'protected_parameters':['shaft_diameter','bearing_diameter'],
        'interface_inventory_status':'confirmed','interface_inventory_source':'synthetic reviewed fixture',
        'dependency_inventory_status':'confirmed','dependency_inventory_source':'synthetic fixture equation',
        'dependencies':[{'parameter':'shaft_length','depends_on':['overall_length'],'offset_mm':0}],
        'measurements':{k:{'value':v,'confirmed':True,'source':'synthetic fixture'} for k,v in values.items()},
        'mappings':{'schema_version':1,'parameters':[{'parameter':k,'document':'fixture.SLDPRT','configuration':'Default','feature':'Sketch1','dimension':'D'+str(i)+'@Sketch1','unit':'mm','source':'synthetic fixture','allowed_range':[1,2000],'status':'confirmed'} for i,k in enumerate(values,1)]}}

class FakeDriver:
    simulated=True
    def __init__(self,request,fail=False):self.values={k:v['value'] for k,v in request['measurements'].items()};self.fail=fail;self.writes=[]
    def isolate(self,*args):pass
    def read_all(self):return dict(self.values)
    def feature_inventory(self):return ['Sketch1','Boss1']
    def mechanical_inventory(self):return {'scope':'fake'}
    def write(self,change):self.writes.append(change['parameter']);self.values[change['parameter']]=change['after_mm']
    def rebuild_save(self):
        if self.fail:raise RuntimeError('fixture rebuild failed')
        self.values['overall_length']=self.values['barrel_length']+self.values['left_projection']+self.values['right_projection']
    def reopen(self):pass
    def axial_extent(self,axis):return self.values['overall_length']
    def close(self):pass

class RollerContracts(unittest.TestCase):
    def test_asymmetric_ends_subtracted_from_total(self):
        p=plan_variant(fixture());self.assertEqual(p['status'],'ready_for_native')
        self.assertEqual(p['resolved_mm']['barrel_length'],745)
        self.assertEqual(p['resolved_mm']['shaft_length'],800)
        self.assertNotIn('shaft_diameter',[c['parameter'] for c in p['changes']])
    def test_missing_mapping_not_inferred(self):
        p=plan_variant({'units':'mm','target_overall_mm':800})
        self.assertEqual(p['status'],'pending_mapping');self.assertEqual(p['changes'],[])
    def test_wrong_original_length_and_short_target_rejected(self):
        r=fixture();r['measurements']['overall_length']['value']=945
        with self.assertRaisesRegex(ValueError,'both shaft projections'):plan_variant(r)
        r=fixture();r['target_overall_mm']=50
        with self.assertRaisesRegex(ValueError,'both preserved shaft'):plan_variant(r)
    def test_protected_dimension_dependency_refused(self):
        r=fixture();r['dependencies']=[{'parameter':'shaft_diameter','depends_on':['overall_length']}]
        with self.assertRaisesRegex(ValueError,'protected interface'):plan_variant(r)
    def test_fake_transaction_preserves_interfaces_and_marks_simulated(self):
        r=fixture();d=FakeDriver(r)
        with tempfile.TemporaryDirectory() as tmp:
            result=execute_variant(r,d,Path(tmp)/'run')
            self.assertEqual(result['status'],'simulated_only');self.assertFalse(result['cad_executed'])
            self.assertEqual(result['after_mm']['overall_length'],800)
            self.assertEqual(result['after_mm']['bearing_diameter'],15)
    def test_failure_preserves_checkpoint_and_stops_readback(self):
        r=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'failed';result=execute_variant(r,FakeDriver(r,True),root)
            self.assertEqual(result['status'],'failed');self.assertIn('recovery',result)
            self.assertEqual(json.loads((root/'checkpoint.json').read_text())['status'],'failed')
    def test_one_handoff_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=export_package(fixture(),Path(tmp)/'handoff')
            self.assertTrue(Path(result['package']).is_file());self.assertFalse(result['cad_executed'])

if __name__=='__main__':unittest.main()
