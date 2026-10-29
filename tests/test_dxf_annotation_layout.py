import sys
from pathlib import Path
import unittest
import ezdxf
from ezdxf import bbox
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from dxf_annotation_layout import fit_single_line_mtext


class AnnotationLayoutTests(unittest.TestCase):
    def test_content_and_style_preserved_and_actual_extents_inside_cell(self):
        doc = ezdxf.new()
        text = doc.modelspace().add_mtext('Machine 1000 x 800', dxfattribs={'char_height':10, 'width':2})
        original = text.text
        fit_single_line_mtext(text, (0,0,80,12), padding=1, minimum_height=2)
        ext = bbox.extents([text])
        self.assertGreaterEqual(ext.extmin.x, 1-1e-8)
        self.assertLessEqual(ext.extmax.x, 79+1e-8)
        self.assertGreaterEqual(ext.extmin.y, 1-1e-8)
        self.assertLessEqual(ext.extmax.y, 11+1e-8)
        self.assertEqual(text.text, original)
        self.assertEqual(text.dxf.style, 'Standard')

    def test_failure_does_not_partially_change_the_entity(self):
        doc = ezdxf.new()
        text = doc.modelspace().add_mtext('A very long label', dxfattribs={'char_height':10})
        before = text.dxf.all_existing_dxf_attribs().copy()
        with self.assertRaises(ValueError):
            fit_single_line_mtext(text, (0,0,2,2), padding=0, minimum_height=5)
        self.assertEqual(text.dxf.all_existing_dxf_attribs(), before)

    def test_multiline_and_dimensions_are_not_silently_rewritten(self):
        doc = ezdxf.new()
        text = doc.modelspace().add_mtext('first\\Psecond')
        with self.assertRaises(ValueError):
            fit_single_line_mtext(text, (0,0,100,100), padding=1, minimum_height=1)
        with self.assertRaises(ValueError):
            fit_single_line_mtext(doc.modelspace().add_line((0,0),(1,1)), (0,0,100,100), padding=1, minimum_height=1)
