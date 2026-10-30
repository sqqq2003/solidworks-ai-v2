import tempfile,unittest
from pathlib import Path
import ezdxf
from sheet_batch_review import inspect_sheet_batch,format_batch_review


class SheetBatchReviewTests(unittest.TestCase):
    def test_preview_flags_text_frame_and_does_not_confirm_parameters(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sheet.dxf';doc=ezdxf.new('R2010');doc.units=4;m=doc.modelspace()
            m.add_lwpolyline([(0,0),(100,0),(100,40),(0,40)],close=True)
            m.add_lwpolyline([(0,100),(100,100),(100,140),(0,140)],close=True)
            m.add_text('红色线为折弯线',dxfattribs={'insert':(10,110),'height':4})
            doc.saveas(path);before=path.read_bytes();report=inspect_sheet_batch(path)
            self.assertEqual(path.read_bytes(),before);self.assertFalse(report['cad_written'])
            self.assertFalse(report['production_approved']);self.assertTrue(report['warnings'])
            self.assertTrue(any(row['text_inside'] for row in report['candidates']))
            self.assertTrue(all(not row['thickness_confirmed'] for row in report['candidates']))
            self.assertIn('未确认',format_batch_review(report))
