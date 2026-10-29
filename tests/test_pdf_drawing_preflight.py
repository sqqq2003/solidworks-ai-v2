import sys
from pathlib import Path
import tempfile
import unittest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pdf_drawing_preflight import inspect_pdf


class PdfPreflightTests(unittest.TestCase):
    def write_pdf(self,folder,text=None):
        writer=PdfWriter();page=writer.add_blank_page(width=300,height=200)
        if text is not None:
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):
                DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 20 100 Td ('+text+') Tj ET').encode('ascii'))
            page[NameObject('/Contents')]=writer._add_object(stream)
        path=Path(folder)/'test.pdf'
        with path.open('wb') as output:writer.write(output)
        return path

    def test_blank_or_glyph_only_text_is_blocked_without_modifying_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.write_pdf(folder);original=path.read_bytes();report=inspect_pdf(path)
            self.assertEqual(report['status'],'blocked');self.assertEqual(report['pages'][0]['text_characters'],0)
            self.assertFalse(report['production_approved']);self.assertEqual(path.read_bytes(),original)

    def test_readable_text_never_implies_title_location_or_dimension_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            report=inspect_pdf(self.write_pdf(folder,'DRW-001 PartA'),required_fields={'code':'DRW-001','name':'PartA'})
            self.assertEqual(report['status'],'text_checks_only_pending_dimension_association')
            self.assertTrue(all(report['required_text_presence'].values()))
            self.assertFalse(report['title_region_verified']);self.assertFalse(report['production_approved'])

    def test_missing_required_text_and_template_placeholder_are_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            report=inspect_pdf(self.write_pdf(folder,'{{DRAWING_CODE}}'),required_fields={'code':'DRW-001'})
            self.assertEqual(report['status'],'blocked')
            self.assertEqual(report['pages'][0]['placeholders'],['{{DRAWING_CODE}}'])
            self.assertFalse(report['required_text_presence']['code'])


if __name__=='__main__':unittest.main()
