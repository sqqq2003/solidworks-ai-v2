import unittest
from ql5050px.interference_audit import component_names,compare_overlap_groups


class InterferenceAuditTests(unittest.TestCase):
    def test_native_dict_and_legacy_string_components_compare_with_explicit_units(self):
        a=[{'components':['assembly/A.step-1','assembly/B.step-1'],'volume_mm3':2}]
        b=[{'components':[{'name':'A_4.step-9'},{'name':'B_4.step-2'}],'volume_m3':2e-9}]
        result=compare_overlap_groups(a,b,families=['A','B','assembly'])
        self.assertEqual(result['status'],'pass');self.assertEqual(result['compared'],1)

    def test_parent_assembly_name_does_not_override_leaf_family(self):
        row={'components':['VeryLongAssembly/A.step-1'],'volume_mm3':1}
        other={'components':['A_3.step-1'],'volume_mm3':1}
        self.assertEqual(compare_overlap_groups([row],[other],families=['A','VeryLongAssembly'])['status'],'pass')

    def test_real_roundtrip_drift_is_not_waived(self):
        a={'components':['A.step-1','B.step-1'],'volume_mm3':7351.142627756724}
        b=dict(a,volume_mm3=7351.191635397192)
        self.assertEqual(compare_overlap_groups([a],[b],families=['A','B'])['status'],'fail')

    def test_missing_pair_and_internal_overlap_counts_are_detected(self):
        row={'components':['A.step-1','A.step-1'],'volume_mm3':1}
        self.assertEqual(compare_overlap_groups([row,row],[row],families=['A'])['status'],'fail')

    def test_invalid_evidence_cannot_be_interpreted_as_no_collision(self):
        for components in ([],[{}],[{'name':''}],[None]):
            with self.subTest(components=components),self.assertRaises(ValueError):component_names({'components':components})

    def test_nonfinite_ambiguous_volume_and_unmapped_family_are_refused(self):
        cases=[{'components':['A.step-1'],'volume_mm3':float('nan')},
               {'components':['A.step-1'],'volume_mm3':1,'volume_m3':1},
               {'components':['unknown.step-1'],'volume_mm3':1}]
        for row in cases:
            with self.subTest(row=row),self.assertRaises(ValueError):compare_overlap_groups([row],[row],families=['A'])
