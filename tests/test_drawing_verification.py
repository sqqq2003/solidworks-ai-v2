from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import MagicMock
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject
from ql5050px.drawing_verification import validate_pdf,verify_view_layout,lock_view_layout,export_pdf


class DrawingVerificationTests(unittest.TestCase):
    def fixture(self):
        sheet=MagicMock();sheet.GetProperties2.return_value=[12,0,1,10,True,.594,.420]
        drawing=MagicMock();drawing.GetCurrentSheet.return_value=sheet
        view=NS(ScaleDecimal=.1,Position=(.15,.15),GetOutline=lambda:[.1,.1,.2,.2])
        task={'scale':[1,10],'width_mm':594,'height_mm':420,'drawing_model':{'views':[{'id':'front','position_mm':[150,150]}]}}
        return drawing,sheet,view,task

    def test_autoscaled_sheet_rejected_even_if_view_looks_right(self):
        drawing,sheet,view,task=self.fixture();sheet.GetProperties2.return_value[3]=20
        with self.assertRaisesRegex(RuntimeError,'sheet scale mismatch'):verify_view_layout(drawing,task,{'front':view})

    def test_outside_frame_overlap_and_title_block_rejected(self):
        drawing,sheet,view,task=self.fixture()
        for outline in ([.01,.1,.2,.2],[.45,.01,.5,.05]):
            view.GetOutline=lambda:outline
            with self.assertRaises(RuntimeError):verify_view_layout(drawing,task,{'front':view})
        view.GetOutline=lambda:[.1,.1,.2,.2]
        task['drawing_model']['views'].append({'id':'right','position_mm':[150,150]})
        with self.assertRaisesRegex(RuntimeError,'overlap'):verify_view_layout(drawing,task,{'front':view,'right':view})

    def test_locks_scale_after_view_creation_and_verifies_readback(self):
        drawing,sheet,view,task=self.fixture()
        proof=lock_view_layout(drawing,task,{'front':view})
        sheet.SetScale.assert_called_once_with(1,10,True,True)
        self.assertEqual(view.UseSheetScale,1);self.assertEqual(view.Position,(.15,.15))
        self.assertEqual(proof['sheet_scale'],[1,10])

    def pdf(self,path,content=True):
        writer=PdfWriter();page=writer.add_blank_page(100,100)
        if content:
            stream=DecodedStreamObject();stream.set_data(b'0 0 m 10 10 l S')
            page[NameObject('/Contents')]=writer._add_object(stream)
        writer.write(str(path))

    def test_pdf_requires_real_parseable_pages_and_expected_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.pdf'
            with self.assertRaisesRegex(RuntimeError,'nonempty'):validate_pdf(path,1)
            path.write_bytes(b'%PDF-fake')
            with self.assertRaisesRegex(RuntimeError,'parse'):validate_pdf(path,1)
            self.pdf(path,False)
            with self.assertRaisesRegex(RuntimeError,'empty PDF'):validate_pdf(path,1)
            self.pdf(path)
            self.assertEqual(validate_pdf(path,1)['pages'],1)
            with self.assertRaisesRegex(RuntimeError,'page count'):validate_pdf(path,2)

    def test_save_success_without_file_is_still_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver=MagicMock();driver.owned_path.side_effect=lambda p:Path(p)
            drawing=MagicMock();drawing.Extension.SaveAs.return_value=(True,0,0)
            drawing.GetSheetNames.return_value=['Sheet1']
            drawing.GetCurrentSheet.return_value.GetProperties2.return_value=[9,12,1,10,True,.594,.420,True]
            with self.assertRaisesRegex(RuntimeError,'nonempty'):export_pdf(driver,drawing,Path(tmp)/'missing.pdf')
            driver.activate.assert_called_once_with(drawing)

    def test_oversized_sheet_blocked_before_save(self):
        driver=MagicMock();driver.owned_path.side_effect=lambda p:Path(p)
        drawing=MagicMock();drawing.GetSheetNames.return_value=['oversized']
        drawing.GetCurrentSheet.return_value.GetName.return_value='oversized'
        drawing.GetCurrentSheet.return_value.GetProperties2.return_value=[12,13,1,2,True,5.297,5.210,True]
        with tempfile.TemporaryDirectory() as tmp,self.assertRaisesRegex(RuntimeError,'5080 mm'):
            export_pdf(driver,drawing,Path(tmp)/'oversized.pdf')
        drawing.Extension.SaveAs.assert_not_called()
        drawing.ActivateSheet.assert_called_with('oversized')

if __name__=='__main__':unittest.main()
