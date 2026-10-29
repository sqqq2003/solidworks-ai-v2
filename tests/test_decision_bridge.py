"""Synthetic offline integration tests, never native acceptance."""
import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ql5050px.intelligent_scan import identity
from ql5050px.integrated import run_integrated


def fixture():
    path='SIM/frame.SLDPRT'
    key=identity(path,'SIM')
    request={'snapshot':{'machine':'QL-5050PX','documents':[{
        'path':path,'configuration':'SIM','exists':True,'component_kind':'editable',
        'dimensions':[{'name':'Length@Sketch1','value':1,'unit':'m','source':'fixture'}]}]},
        'pending_parameters':['length'],
        'approvals':[{'parameter':'length','document_id':key,'dimension':'Length@Sketch1','reviewed':True,'source':'fixture engineer'}],
        'rules':{key:{'action':'resize','targets':{'length':1.8}}},
        'manufacturing':{'drive':{'source_assembly':'SIM/machine.SLDASM','assembly_configuration':'SIM'}}}
    return request,key


class DecisionBridgeTests(unittest.TestCase):
    def test_resize_generates_native_drive_contract_and_preserves_input(self):
        request,key=fixture()
        before=copy.deepcopy(request)
        result=run_integrated(request)
        self.assertEqual(request,before)
        drive=result['machine_plan']['drive_plan']
        self.assertEqual(drive['status'],'ready_for_native')
        edit=drive['component_modifications'][0]['edits'][0]
        self.assertEqual((edit['before'],edit['after'],edit['unit']),(1000,1800,'mm'))
        self.assertEqual(edit['target'],'Length@Sketch1')
        self.assertFalse(result['windows_tasks']['native_write_allowed'])
        self.assertFalse(result['cad_executed'])

    def test_unapproved_and_partial_decisions_do_not_generate_edits(self):
        for partial in (False,True):
            with self.subTest(partial=partial):
                request,key=fixture()
                if partial:
                    request['pending_parameters'].append('width')
                    request['rules'][key]['targets']['width']=900
                else:
                    request['approvals']=[]
                result=run_integrated(request)
                self.assertFalse(result['machine_plan']['drive_plan']['component_modifications'])
                self.assertTrue(result['windows_tasks']['decision_bridge']['pending_mapping'])

    def test_explicit_approval_resolves_multiple_candidates(self):
        request,key=fixture()
        request['snapshot']['documents'][0]['dimensions'].append({'name':'Length@Sketch2','value':2,'unit':'m'})
        result=run_integrated(request)
        self.assertEqual(len(result['machine_plan']['drive_plan']['component_modifications']),1)

    def test_protected_parts_reject_dimension_approval(self):
        for kind in ('purchased','fixed','standard'):
            with self.subTest(kind=kind):
                request,key=fixture()
                request['snapshot']['documents'][0]['component_kind']=kind
                with self.assertRaises(ValueError): run_integrated(request)

    def test_invalid_values_and_duplicate_approvals_rejected(self):
        for value in (True,float('nan'),float('inf'),-1):
            request,key=fixture()
            request['rules'][key]['targets']['length']=value
            with self.subTest(value=value),self.assertRaises(ValueError): run_integrated(request)
        request,key=fixture()
        request['approvals']*=2
        with self.assertRaises(ValueError): run_integrated(request)

    def test_existing_drive_binding_collision_rejected(self):
        request,key=fixture()
        request['manufacturing']['drive']['components']=[{'id':'old','document':'sim\\FRAME.sldprt','configuration':'SIM',
            'bindings':[{'parameter':'other','target':'Length@Sketch1'}]}]
        with self.assertRaises(ValueError): run_integrated(request)

    def test_existing_protected_component_blocks_snapshot_resize(self):
        request,key=fixture()
        request['manufacturing']['drive']['components']=[{'id':'motor','component_kind':'purchased',
            'document':'SIM/frame.SLDPRT','configuration':'SIM'}]
        result=run_integrated(request)
        self.assertFalse(result['machine_plan']['drive_plan']['component_modifications'])
        self.assertTrue(result['windows_tasks']['decision_bridge']['pending_mapping'])

    def test_new_size_propagates_to_existing_dependency_graph(self):
        request,key=fixture()
        request['manufacturing']['drive']['nodes']={
            'half_length':{'unit':'mm','depends_on':['decision_0_0'],'rule':{'op':'scale','factor':0.5}}}
        result=run_integrated(request)
        self.assertEqual(result['machine_plan']['drive_plan']['values']['half_length'],900)

    def test_translate_requires_reviewed_occurrence_and_preserves_rotation(self):
        request,key=fixture()
        request['approvals']=[]
        request['pending_parameters']=[]
        request['rules'][key]={'action':'translate','translation_mm':[20,30,40]}
        transform=[1,0,0,0,1,0,0,0,1,1,2,3,1,0,0,0]
        request['manufacturing']['assembly_tree']={'machine':'QL-5050PX','units':'mm','root':'machine',
            'mate_inventory_status':'confirmed','mates':[], 'catalog':{
            'machine':{'part_number':'SIM-ASM','type':'assembly','component_kind':'editable','source_path':'SIM/machine.SLDASM','configuration':'SIM',
                'children':[{'id':'frame1','ref':'frame','native_name':'frame-1','transform_mm':transform}]},
            'frame':{'part_number':'SIM-FRAME','type':'part','component_kind':'editable','source_path':'SIM/frame.SLDPRT','configuration':'SIM'}}}
        result=run_integrated(request)
        self.assertTrue(result['windows_tasks']['decision_bridge']['pending_mapping'])
        request['execution_bindings']={key:{'assembly':'machine','occurrence':'frame1','reviewed':True,'source':'fixture'}}
        result=run_integrated(request)
        actual=result['machine_plan']['assembly_plan']['tree']['catalog']['machine']['children'][0]['transform_mm']
        self.assertEqual(actual[:9],transform[:9])
        self.assertEqual(actual[9:12],[20,30,40])
        self.assertEqual(transform[9:12],[1,2,3])

    def test_unsupported_actions_remain_pending(self):
        request,key=fixture()
        request['rules'][key]={'action':'regenerate','approved_specification':'fixture'}
        result=run_integrated(request)
        self.assertTrue(result['windows_tasks']['decision_bridge']['pending_mapping'])


if __name__=='__main__': unittest.main()
