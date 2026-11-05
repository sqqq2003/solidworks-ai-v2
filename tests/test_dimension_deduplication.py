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
