import tempfile,unittest
from pathlib import Path
import ezdxf
from sheet_dimension_compare import compare_flat

class SheetCompareTests(unittest.TestCase):
    def test_mirror_is_disclosed_and_wrong_hole_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[Path(tmp)/'source.dxf',Path(tmp)/'actual.dxf']
            def write(path,x,diameter=8):
                doc=ezdxf.new();doc.units=4;m=doc.modelspace();m.add_lwpolyline([(0,0),(100,0),(100,80),(0,80)],close=True);m.add_circle((x,20),diameter/2);doc.saveas(path)
            write(paths[0],20);write(paths[1],80)
            r=compare_flat(*paths,numerical_tolerance_mm=.000001)
            self.assertEqual(r['matching_coordinate_transforms'],['face_flip_x']);self.assertFalse(r['manufacturing_approved'])
            write(paths[1],80,9)
            self.assertEqual(compare_flat(*paths,numerical_tolerance_mm=.000001)['status'],'dimension_mismatch')

if __name__=='__main__':unittest.main()
