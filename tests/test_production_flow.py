"""Offline orchestration contracts only: fixture files are not native CAD."""
from copy import deepcopy
import json,tempfile,unittest
from pathlib import Path
from ql5050px.production import execute_production,fingerprint,validate_review,write_production_package


def fixture_plan():
    plan={'status':'ready_for_native','pending_mapping':[], 'links':{'components':{'motor':'part'},'mates':{}},'motion_samples':[],
      'machine_plan':{'assembly_plan':{'status':'ready_for_native','tree':{'root':'machine'}},
        'drive_plan':{'status':'ready_for_native','component_modifications':[{'component':'motor','document':'original.SLDPRT'}],'affected_mates':[]},
        'drawing_plan':{'status':'ready_for_native','bom':[]}}}
    plan['review_sha256']=fingerprint(plan);return plan

class FakeDriver:
    def __init__(self,fail=False):self.fail=fail;self.events=[]
    def build_assembly(self,plan,dest):
        self.events.append('assembly');dest.mkdir()
        self.documents={n:{'path':str(dest/(n+suffix)),'configuration':'Default'} for n,suffix in [('machine','.SLDASM'),('part','.SLDPRT')]}
        for item in self.documents.values():Path(item['path']).write_bytes(b'offline fake')
        return {'documents':self.documents}
    def apply_drive(self,plan,dest):
        self.events.append('drive')
        assert plan['source_assembly']==self.documents['machine']['path']
        assert plan['component_modifications'][0]['document']==self.documents['part']['path']
        if self.fail:raise RuntimeError('fixture drive failure')
        dest.mkdir();copies={}
        for item in self.documents.values():
            target=dest/Path(item['path']).name;target.write_bytes(b'offline variant');copies[item['path']]=str(target)
        return {'isolated_documents':copies,'document':{'path':copies[self.documents['machine']['path']],'configuration':'Default'}}
    def inspect_native(self,path,samples):
        self.events.append('checks');assert Path(path).parent.name == 'drive'
        return {'simulated_only':False,'acceptance':'unverified','fixture_only':True}
    def export_manufacturing(self,plan,receipt,dest):
        self.events.append('drawings')
        assert all(Path(d['path']).parent.name == 'drive' for d in receipt['documents'].values())
        dest.mkdir();(dest/'fixture.SLDDRW').write_bytes(b'not a real drawing')
        return {'fixture_only':True}

class ProductionContracts(unittest.TestCase):
    def test_linked_flow_uses_variant_for_checks_and_drawings(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan=fixture_plan();driver=FakeDriver()
            report=execute_production(plan,driver,Path(tmp)/'run',review_sha256=plan['review_sha256'])
            self.assertEqual(driver.events,['assembly','drive','checks','drawings'])
            self.assertEqual(report['status'],'outputs_created_review_required')
            self.assertFalse(report['manufacturing_approved'])
            self.assertTrue(report['artifact_sha256'])
    def test_failure_stops_downstream_and_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';plan=fixture_plan();driver=FakeDriver(True)
            with self.assertRaisesRegex(RuntimeError,'fixture drive failure'):
                execute_production(plan,driver,root,review_sha256=plan['review_sha256'])
            self.assertEqual(driver.events,['assembly','drive'])
            self.assertEqual(json.loads((root/'checkpoint.json').read_text())['status'],'failed')
    def test_changed_review_refused_before_driver(self):
        plan=fixture_plan();sha=plan['review_sha256'];plan['motion_samples']=[{'changed':True}]
        with self.assertRaisesRegex(ValueError,'review hash'):validate_review(plan,sha)
    def test_pending_plan_refused_even_if_hash_matches(self):
        plan=fixture_plan();plan.pop('review_sha256');plan['status']='pending_mapping';plan['review_sha256']=fingerprint(plan)
        with self.assertRaisesRegex(ValueError,'incomplete OEM'):validate_review(plan,plan['review_sha256'])
    def test_unmapped_target_exports_real_bom_package_without_cad(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=write_production_package({'machine':'QL-5050PX','units':'mm'},Path(tmp)/'package')
            self.assertEqual(result['status'],'pending_mapping');self.assertFalse(result['cad_executed'])
            self.assertTrue(Path(result['package']).is_file())

if __name__=='__main__':unittest.main()
