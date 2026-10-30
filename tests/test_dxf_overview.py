"""Read-only DXF overview tests; synthetic files only, no CAD process."""
import tempfile
import unittest
from pathlib import Path

import ezdxf
from dxf_overview import inspect_dxf, preview_geometry


class DxfOverviewTests(unittest.TestCase):
    def test_inventory_and_numeric_override_are_review_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '带空格 图纸.dxf'
            doc = ezdxf.new('R2010'); doc.units = 4
            space = doc.modelspace()
            space.add_line((0, 0), (290, 0), dxfattribs={'layer': '方管'})
            space.add_text('方管下料', dxfattribs={'layer': '说明'})
            dimension = space.add_linear_dim(base=(0, 10), p1=(0, 0), p2=(290, 0)).dimension
            dimension.dxf.text = '270'; dimension.dxf.actual_measurement = 290
            doc.saveas(path)
            before = path.read_bytes()
            report = inspect_dxf(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(report['entity_count'], 3)
            self.assertEqual(report['unit_label'], 'mm')
            self.assertEqual(report['dimension_mismatch_count'], 1)
            self.assertEqual(report['dimension_mismatches'][0]['display_override'], '270')
            self.assertEqual(report['dimension_mismatches'][0]['stored_measurement'], 290)
            self.assertFalse(report['geometry_verified'])
            self.assertFalse(report['production_approved'])

    def test_dimension_specification_not_treated_as_numeric_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'unknown-units.dxf'
            doc = ezdxf.new('R2010'); doc.units = 0
            dimension = doc.modelspace().add_linear_dim(base=(0, 10), p1=(0, 0), p2=(10, 0)).dimension
            dimension.dxf.text = '2-%%C10打穿'; dimension.dxf.actual_measurement = 10
            doc.saveas(path)
            report = inspect_dxf(path)
            self.assertEqual(report['unit_label'], 'unconfirmed')
            self.assertEqual(report['dimension_mismatch_count'], 0)

    def test_dwg_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'drawing.dwg'; path.write_bytes(b'not a DXF')
            with self.assertRaisesRegex(ValueError, 'DXF'):
                inspect_dxf(path)

    def test_paper_layout_is_visible_as_unchecked_inventory(self):
        from dxf_overview import format_overview
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'layout.dxf';doc=ezdxf.new('R2010')
            doc.modelspace().add_line((0,0),(1,0))
            layout=doc.layouts.new('总图');layout.add_circle((5,5),2);doc.saveas(path)
            report=inspect_dxf(path)
            paper=next(item for item in report['paper_layouts'] if item['name']=='总图')
            self.assertEqual(paper['entity_types']['CIRCLE'],1)
            self.assertEqual(paper['status'],'inventory_only')
            self.assertIn('当前概览和图形预览不检查布局',format_overview(report))
            self.assertFalse(report['production_approved'])

    def test_preview_is_bounded_read_only_and_refuses_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview.dxf'
            doc=ezdxf.new('R2010');space=doc.modelspace()
            space.add_line((0,0),(10,0),dxfattribs={'layer':'轮廓'})
            space.add_circle((5,5),2,dxfattribs={'layer':'孔'})
            space.add_text('ignored in visual preview');doc.saveas(path)
            before=path.read_bytes();overview=inspect_dxf(path)
            preview=preview_geometry(path,overview['sha256'])
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual({row['layer'] for row in preview['paths']},{'轮廓','孔'})
            self.assertEqual(preview['omitted']['TEXT'],1)
            self.assertFalse(preview['truncated'])
            path.write_bytes(before+b'\n')
            with self.assertRaisesRegex(ValueError,'文件已改变'):
                preview_geometry(path,overview['sha256'])


if __name__ == '__main__':
    unittest.main()
