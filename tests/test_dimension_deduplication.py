import unittest
from types import SimpleNamespace as NS
from test_model_dimension_import import display
from ql5050px.model_dimensions import (display_dimension_value,duplicate_dimension_plan,
    deduplicate_model_dimensions,verify_hidden_dimensions,collect_model_dimensions)


class DimensionDeduplicationTests(unittest.TestCase):
    def records(self):
        return [dict(view=view,name='note'+view,model_dimension=display_dimension_value(display()))
                for view in ('front','right')]
    def test_explicit_preferred_view_keeps_one_and_hides_only_duplicate(self):
        plan=duplicate_dimension_plan(self.records(),{'D1@Extrude':'right'})
        self.assertEqual(plan['keep'],[1]);self.assertEqual(plan['hide'],[0])
    def test_different_model_full_names_are_never_merged(self):
        records=self.records();records[1]['model_dimension']['full_name']='D1@Extrude@other.Part'
        plan=duplicate_dimension_plan(records)
        self.assertEqual(plan['hide'],[]);self.assertEqual(len(plan['keep']),2)
    def test_conflicting_values_or_overrides_are_not_hidden(self):
        for key,value in (('value_si',.504),('overridden',True)):
            records=self.records();records[1]['model_dimension'][key]=value
            plan=duplicate_dimension_plan(records)
            self.assertEqual(plan['hide'],[]);self.assertTrue(plan['blocked_parameters'])
    def test_unknown_preferred_view_is_rejected(self):
        with self.assertRaises(ValueError):duplicate_dimension_plan(self.records(),{'D1@Extrude':'isometric'})
    def test_visibility_only_native_write_and_reopen_verification(self):
        front=display();right=display()
        views={'front':NS(GetFirstDisplayDimension5=front),'right':NS(GetFirstDisplayDimension5=right)}
        drawing=NS(GraphicsRedraw2=lambda:None,EditRebuild3=lambda:True)
        proof=deduplicate_model_dimensions(NS(guard=lambda:None),drawing,views,{'D1@Extrude':'right'})
        self.assertEqual(proof['status'],'applied');self.assertFalse(proof['model_dimensions_deleted'])
        self.assertEqual(front.GetAnnotation().Visible,3);self.assertEqual(right.GetAnnotation().Visible,1)
        self.assertEqual(len(collect_model_dimensions(views)),1)
        self.assertTrue(verify_hidden_dimensions(views,proof)['reopened_verified'])
        front.GetAnnotation().Visible=1
        self.assertFalse(verify_hidden_dimensions(views,proof)['reopened_verified'])
    def test_already_hidden_dimensions_are_not_counted_as_visible_evidence(self):
        dim=display();dim.GetAnnotation().Visible=3
        self.assertEqual(collect_model_dimensions({'front':NS(GetFirstDisplayDimension5=dim)}),[])
    def test_hidden_annotation_chain_is_used_when_display_iterator_omits_it(self):
        dim=display();ann=dim.GetAnnotation();ann.Visible=3;ann.GetNext3=None
        record={'view':'front','name':'dimension1','model_dimension':display_dimension_value(dim)}
        proof={'status':'applied','hidden_dimensions':[record]}
        views={'front':NS(GetFirstDisplayDimension5=None,GetFirstAnnotation3=ann)}
        self.assertTrue(verify_hidden_dimensions(views,proof)['reopened_verified'])
        ann.Visible=1
        self.assertFalse(verify_hidden_dimensions(views,proof)['reopened_verified'])
    def test_different_hidden_dimensions_can_share_the_short_name_d1(self):
        first=display(value=.04,name='D1@Sketch@tube.Part');second=display()
        a=first.GetAnnotation();b=second.GetAnnotation()
        for annotation in (a,b):annotation.Visible=3;annotation.GetName=lambda:'D1'
        a.GetNext3=b;b.GetNext3=None
        proof={'status':'applied','hidden_dimensions':[
            {'view':'top','name':'D1','annotation_type':4,'model_dimension':display_dimension_value(dim)}
            for dim in (first,second)]}
        views={'top':NS(GetFirstDisplayDimension5=None,GetFirstAnnotation3=a)}
        self.assertTrue(verify_hidden_dimensions(views,proof)['reopened_verified'])
        b.GetNext3=a
        with self.assertRaisesRegex(RuntimeError,'cyclic'):verify_hidden_dimensions(views,proof)
