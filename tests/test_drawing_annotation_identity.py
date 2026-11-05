import unittest
from types import SimpleNamespace as NS
from ql5050px.drawing_verification import verify_annotation_evidence


def annotation(name='note',text='test',position=(.03,.38,0)):
    return NS(GetName=lambda:name,GetType=lambda:6,GetPosition=lambda:position,
              GetSpecificAnnotation=lambda:NS(GetText=lambda:text))


def drawing(*groups):
    next_view=None
    for i,group in reversed(list(enumerate(groups))):
        next_view=NS(GetName2='view'+str(i),GetAnnotations=group,GetNextView=next_view)
    return NS(GetFirstView=next_view)


class AnnotationIdentityTests(unittest.TestCase):
    expected=[dict(name='note',kind='note',type=6,position_mm=[30,380,0],text='test')]
    def test_same_native_object_repeated_across_views_is_not_duplicate(self):
        note=annotation()
        self.assertTrue(verify_annotation_evidence(drawing([note],[note]),self.expected)[0]['reopened'])
    def test_unrelated_duplicate_template_names_do_not_block_expected_note(self):
        self.assertTrue(verify_annotation_evidence(drawing([annotation('template')],[annotation('template'),annotation()]),self.expected))
    def test_different_objects_with_identical_expected_evidence_remain_ambiguous(self):
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):
            verify_annotation_evidence(drawing([annotation()],[annotation()]),self.expected)
    def test_same_name_with_different_position_is_disambiguated_by_full_evidence(self):
        self.assertTrue(verify_annotation_evidence(drawing([annotation(position=(0,0,0))],[annotation()]),self.expected))
    def test_changed_text_and_position_remain_failures(self):
        for note in (annotation(text='changed'),annotation(position=(0,0,0))):
            with self.assertRaisesRegex(RuntimeError,'differs'):verify_annotation_evidence(drawing([note]),self.expected)
    def test_missing_note_remains_failure(self):
        with self.assertRaisesRegex(RuntimeError,'missing'):verify_annotation_evidence(drawing([annotation('other')]),self.expected)
