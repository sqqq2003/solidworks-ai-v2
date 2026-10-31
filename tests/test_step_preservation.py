import hashlib
from pathlib import Path
import tempfile
import unittest
from ql5050px.step_preservation import StepDocument, references


DATA = b"ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));\nENDSEC;\nDATA;\n#1=CARTESIAN_POINT('semi; quote'' #999',(1.,2.,3.));\n#2=NEXT_ASSEMBLY_USAGE_OCCURRENCE('trial','', '',#3,#3,$);\n#3=PRODUCT_DEFINITION('','',#4,#4);\n#4=PRODUCT('x','x','',());\nENDSEC;\nEND-ISO-10303-21;\n"


class StepPreservationTests(unittest.TestCase):
    def test_quoted_semicolon_and_fake_reference_are_opaque(self):
        doc=StepDocument(DATA)
        self.assertEqual(len(doc.records),4)
        self.assertEqual(references(doc.records[1]),set())

    def test_removal_preserves_geometry_bytes_and_header(self):
        doc=StepDocument(DATA)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'trial.step'
            evidence=doc.remove_occurrence_metadata([2],expected_sha256=doc.sha256,output=path)
            self.assertEqual(StepDocument(path.read_bytes()).records[1],doc.records[1])
            self.assertFalse(evidence['geometry_reserialized'])
            self.assertTrue(path.read_bytes().startswith(DATA[:DATA.index(b'DATA;')]))

    def test_geometry_deletion_is_refused_before_creating_output(self):
        doc=StepDocument(DATA)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'trial.step'
            with self.assertRaises(ValueError):doc.remove_occurrence_metadata([1],expected_sha256=doc.sha256,output=path)
            self.assertFalse(path.exists())

    def test_dangling_reference_refused(self):
        data=DATA.replace(b'#3=PRODUCT_DEFINITION',b'#5=PRODUCT_DEFINITION')
        with self.assertRaises(ValueError):StepDocument(data)

    def test_removal_with_incoming_reference_is_refused_before_write(self):
        data=DATA.replace(b'#3=PRODUCT_DEFINITION',b'#9=PRODUCT_DEFINITION_SHAPE(\'\',\'\',#2);\n#3=PRODUCT_DEFINITION')
        doc=StepDocument(data)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'trial.step'
            with self.assertRaises(ValueError):doc.remove_occurrence_metadata([2],expected_sha256=doc.sha256,output=path)
            self.assertFalse(path.exists())

    def test_changed_baseline_and_existing_output_refused(self):
        doc=StepDocument(DATA)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'trial.step'
            with self.assertRaises(ValueError):doc.remove_occurrence_metadata([2],expected_sha256='a'*64,output=path)
            path.write_bytes(b'original')
            with self.assertRaises(FileExistsError):doc.remove_occurrence_metadata([2],expected_sha256=doc.sha256,output=path)
            self.assertEqual(path.read_bytes(),b'original')

    def test_duplicate_ids_and_unterminated_strings_refused(self):
        for data in (DATA.replace(b'#2=NEXT',b'#1=NEXT'),DATA.replace(b"semi; quote'' #999'",b"unterminated")):
            with self.subTest(data=data),self.assertRaises(ValueError):StepDocument(data)

    def test_detached_placement_can_be_removed_but_shared_coordinate_cannot(self):
        data=DATA.replace(b'ENDSEC;\nEND-ISO',b"#5=AXIS2_PLACEMENT_3D('',#1,#6,#6);\n#6=DIRECTION('',(0.,0.,1.));\nENDSEC;\nEND-ISO")
        doc=StepDocument(data)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'trial.step'
            evidence=doc.remove_occurrence_metadata([5,6],expected_sha256=doc.sha256,output=path)
            self.assertEqual(evidence['removed_detached_placement_entities'],[5,6])
            shared=StepDocument(data.replace(b"#4=PRODUCT('x'",b"#7=POLYLINE('',(#1));\n#4=PRODUCT('x'"))
            with self.assertRaises(ValueError):shared.remove_occurrence_metadata([1,5,6],expected_sha256=shared.sha256,output=Path(temp)/'unsafe.step')

    def test_removed_occurrence_axis_is_detached_from_assembly_item_list(self):
        data=DATA.replace(b'ENDSEC;\nEND-ISO',b"#5=AXIS2_PLACEMENT_3D('',#1,#6,#6);\n#6=DIRECTION('',(0.,0.,1.));\n#7=SHAPE_REPRESENTATION('',(#5,#1),#4);\nENDSEC;\nEND-ISO")
        doc=StepDocument(data)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'trial.step'
            with self.assertRaises(ValueError):doc.remove_occurrence_metadata([5,6],expected_sha256=doc.sha256,output=path)
            evidence=doc.remove_occurrence_metadata([5,6],detach_axes=[5],expected_sha256=doc.sha256,output=path)
            self.assertEqual(evidence['edited_assembly_item_lists'],[7])
            self.assertEqual(references(StepDocument(path.read_bytes()).records[7]),{1,4})
