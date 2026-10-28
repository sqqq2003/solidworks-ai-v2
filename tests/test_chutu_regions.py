import unittest
import ezdxf
from chutu_regions import classify, inspect_regions


class ChutuRegionsTest(unittest.TestCase):
    def test_priority_and_region_candidates(self):
        doc=ezdxf.new(); m=doc.modelspace()
        doc.layers.new('VIEW_DIM')
        self.assertEqual(classify(m.add_line((38000,3000),(38010,3000),dxfattribs={'layer':'VIEW_DIM'})),'view')
        self.assertEqual(classify(m.add_text('test',dxfattribs={'insert':(39000,3000)})),'bom')
        self.assertEqual(classify(m.add_text('test',dxfattribs={'insert':(44000,4000)})),'fang')
        self.assertEqual(classify(m.add_lwpolyline([(35000,1000),(39000,1000),(39000,4001),(35000,4001)],close=True)),'frame')
        result=inspect_regions(doc)
        self.assertEqual(sum(result['counts'].values()),4)
        self.assertFalse(result['production_approved'])
