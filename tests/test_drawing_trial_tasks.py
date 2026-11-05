import unittest
from src.ql5050px.drawing_trial import trial_task


class TrialTaskTests(unittest.TestCase):
    def test_part_has_three_views_pdf_and_no_fabricated_bom(self):
        task=trial_task({'sheet':'A2','denominator':10},'frame','Default','bom',model_kind=1)
        self.assertEqual(task['drawing_model']['bom'],[])
        self.assertEqual([v['id'] for v in task['drawing_model']['views']],['front','top','right'])
        self.assertEqual(task['exports'],['SLDDRW','PDF']);self.assertTrue(task['auto_layout'])
        self.assertEqual(task['projection'],'first_angle');self.assertEqual(task['scale'],[1,10])
    def test_assembly_keeps_linked_top_level_bom(self):
        task=trial_task({'sheet':'A3','denominator':20},'frame','Default','bom',model_kind=2)
        self.assertEqual(task['drawing_model']['bom'],[{'scope':'available_top_level_only'}])
        self.assertEqual(task['width_mm'],420);self.assertEqual(task['scale'],[1,20])
    def test_drawing_cannot_be_used_as_source_model(self):
        with self.assertRaises(ValueError):trial_task({'sheet':'A2','denominator':10},'frame','Default','bom',model_kind=3)
