import tempfile
import unittest
from pathlib import Path
import ezdxf
from five_sheet_plan import plan_five_sheets


class FiveSheetPlanTest(unittest.TestCase):
    def test_file_is_read_only_and_no_layer_implies_approval(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source.dxf'
            doc = ezdxf.new(); doc.units = 4
            doc.modelspace().add_line((0, 0), (100, 0))
            doc.saveas(path)
            before = path.read_bytes()
            result = plan_five_sheets(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(result['sheets']), 5)
            self.assertEqual(result['source']['entity_count'], 1)
            self.assertTrue(all(row['missing_confirmed_components'] for row in result['sheets']))
            self.assertFalse(result['production_approved'])

    def test_explicit_component_does_not_claim_generated(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source.dxf'; ezdxf.new().saveas(path)
            result = plan_five_sheets(path, component_evidence={'views': True})
            self.assertNotIn('views', result['sheets'][0]['missing_confirmed_components'])
            self.assertFalse(result['geometry_generated'])
