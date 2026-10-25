import unittest,sys
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ql5050px.modeling_validation import validate_part_plan,envelope

class Validation(unittest.TestCase):
    def plan(self):return {'features':[{'id':'outline','kind':'sketch','unit':'mm','confirmed':True,'evidence':['fixture'],'parameters':{'plane':'fixture','entities':[{'type':'line','start':[0,0],'end':[10,0]}]}}]}
    def test_empty_and_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):validate_part_plan({'features':[]},{'sketch'})
        p=self.plan();p['features']*=2
        with self.assertRaises(ValueError):validate_part_plan(p,{'sketch'})
    def test_bad_envelopes_cannot_truncate_comparison(self):
        for v in ([1],[1,2],[1,2,3,4],[1,2,float('nan')],[True,2,3]):
            with self.subTest(v=v),self.assertRaises(ValueError):envelope(v)
    def test_cut_needs_consumed_sketch_dependency(self):
        p=self.plan();p['features'].append({'id':'cut','kind':'cut','unit':'mm','confirmed':True,'evidence':['fixture'],'parameters':{'sketch':'outline','depth_mm':1}})
        with self.assertRaises(ValueError):validate_part_plan(p,{'sketch','cut'})
    def test_non_circular_arc_rejected(self):
        p=self.plan();p['features'][0]['parameters']['entities']=[{'type':'arc','center':[0,0],'start':[10,0],'end':[0,12],'direction':1}]
        with self.assertRaises(ValueError):validate_part_plan(p,{'sketch'})
    def test_dimension_count_unit_rejected_before_native_write(self):
        p=self.plan();p['features'][0]['parameters']['constraints']=[{'kind':'dimension','confirmed':True,'source':'fixture','references':[{'name':'x','type':'SKETCHSEGMENT'}],'value':3,'unit':'count','position_mm':[0,0,0]}]
        with self.assertRaises(ValueError):validate_part_plan(p,{'sketch'})
    def test_valid_fixture_and_complete_envelope_accepted(self):
        p=self.plan();p['expected_dims_mm']=[10,20,2];p['expected_body_count']=1
        self.assertIs(validate_part_plan(p,{'sketch'}),p)
if __name__=='__main__':unittest.main()

