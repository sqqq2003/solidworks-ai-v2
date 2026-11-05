import copy
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

from cad_checkpoint import digest_file
from ql5050px.pdf_dimensions import match_dimension_words,correlate_pdf_dimensions,pdf_dimension_correlation_verified


def native(value=.514,x=100,y=200,name='D1',kind=0):
    return {'kind':'model_dimension','name':name,'requested':{'view':'right'},'position_mm':[x,y,0],
        'reopened':True,'model_dimension':{'full_name':name+'@Extrude@tube.Part','parameter':name+'@Extrude',
            'parameter_type':kind,'value_si':value,'unit_si':'m' if kind==0 else 'rad',
            'overridden':False,'uses_document_units':True,'visibility_state':1}}


def word(text='514',box=None):return {'text':text,'bbox_mm':[98,95,102,98] if box is None else box}


class PDFDimensionMatchingTests(unittest.TestCase):
    def test_value_and_pdf_bbox_match_native_sheet_anchor(self):
        result=match_dimension_words([native()],[word()],[420,297])
        self.assertEqual(result['status'],'verified');self.assertEqual(result['associations'][0]['value'],514)
        self.assertEqual(result['associations'][0]['native_anchor_pdf_mm'],[100,97])
        self.assertFalse(result['manufacturing_approved'])
    def test_number_elsewhere_on_page_is_not_proof(self):
        self.assertNotEqual(match_dimension_words([native()],[word(box=[200,95,204,98])],[420,297])['status'],'verified')
    def test_one_pdf_word_cannot_satisfy_two_native_dimensions(self):
        result=match_dimension_words([native(),native(name='D2')],[word()],[420,297])
        self.assertIn('ambiguous_or_non_unique_pdf_dimension_assignment',result['issues'])
    def test_ambiguous_nearby_words_are_rejected(self):
        result=match_dimension_words([native()],[word(),word(box=[101,95,104,98])],[420,297])
        self.assertNotEqual(result['status'],'verified')
    def test_two_equal_dimensions_can_match_separate_locations(self):
        result=match_dimension_words([native(),native(x=150,name='D2')],
            [word(),word(box=[148,95,152,98])],[420,297])
        self.assertEqual(result['status'],'verified');self.assertEqual(len(result['associations']),2)
    def test_colliding_text_is_not_accepted(self):
        result=match_dimension_words([native()],[word(),word('NOTE',[100,95,106,98])],[420,297])
        self.assertTrue(any(isinstance(issue,dict) and issue['issue']=='dimension_text_collision' for issue in result['issues']))
    def test_title_block_intersection_is_rejected(self):
        result=match_dimension_words([native(x=400,y=17)],[word(box=[398,278,402,282])],[420,297],reserved=[[240,0,420,60]])
        self.assertTrue(any(isinstance(issue,dict) and issue['issue']=='dimension_text_in_reserved_area' for issue in result['issues']))
    def test_numeric_override_hidden_or_not_reopened_stays_pending(self):
        for field,value in (('overridden',True),('visibility_state',3),('uses_document_units',False)):
            row=native();row['model_dimension'][field]=value
            self.assertNotEqual(match_dimension_words([row],[word()],[420,297])['status'],'verified')
        row=native();row['reopened']=False
        self.assertNotEqual(match_dimension_words([row],[word()],[420,297])['status'],'verified')
    def test_decimal_comma_and_angular_units(self):
        self.assertEqual(match_dimension_words([native(.0405)],[word('40,500')],[420,297])['status'],'verified')
        result=match_dimension_words([native(math.pi/2,kind=1)],[word('90°')],[420,297])
        self.assertEqual(result['status'],'verified');self.assertEqual(result['associations'][0]['unit'],'deg')
    def test_invalid_geometry_and_unbounded_tolerance_rejected(self):
        with self.assertRaises(ValueError):match_dimension_words([native()],[word()],[420,297],max_distance_mm=100)
        self.assertNotEqual(match_dimension_words([native()],[word(box=[float('nan'),95,102,98])],[420,297])['status'],'verified')


@unittest.skipUnless(importlib.util.find_spec('pdfplumber'),'PDF geometry backend not installed')
class PDFGeometryBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'sample.pdf'
        self.model=self.root/'model.SLDPRT';self.model.write_bytes(b'offline fixture only')
    def create_pdf(self,rotation=0,text_matrix=(1,0,0,1)):
        from pypdf import PdfWriter
        from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject
        scale=72/25.4;writer=PdfWriter();page=writer.add_blank_page(width=420*scale,height=297*scale)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        matrix=' '.join(str(v) for v in text_matrix)
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 10 Tf {matrix} {100*scale} {200*scale} Tm (514) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream)
        if rotation:page.rotate(rotation)
        with self.path.open('wb') as target:writer.write(target)
        row=native()
        return {'source':{'path':str(self.model),'sha256':digest_file(self.model)},
            'artifacts':{'pdf':{'path':str(self.path),'sha256':digest_file(self.path)}},'annotations':[row],
            'layout_readback':{'sheet_size_mm':[420,297],'frame_bounds_mm':[25,10,410,287]},
            'model_dimension_import':{'status':'verified','reopened_verified':True,'display_dimensions':1,
                'source_parameters':[copy.deepcopy(row['model_dimension'])],'missing_parameters':[],'issues':[]}}
    def test_real_pdf_extraction_and_independent_reverification(self):
        data=self.create_pdf();proof=correlate_pdf_dimensions(self.path,data)
        self.assertEqual(proof['status'],'verified',proof)
        data['pdf_dimension_correlation']=proof
        self.assertTrue(pdf_dimension_correlation_verified(data,reextract=True))
        data['pdf_dimension_correlation']['associations'][0]['text']='999'
        self.assertFalse(pdf_dimension_correlation_verified(data,reextract=True))
    def test_native_position_change_invalidates_stored_binding(self):
        data=self.create_pdf();data['pdf_dimension_correlation']=correlate_pdf_dimensions(self.path,data)
        data['annotations'][0]['position_mm'][0]+=20
        self.assertFalse(pdf_dimension_correlation_verified(data))
    def test_rotated_page_requires_review(self):
        data=self.create_pdf(rotation=90)
        self.assertIn('rotated_or_offset_pdf_requires_review',correlate_pdf_dimensions(self.path,data)['issues'])
    def test_text_rotation_uses_glyph_direction_without_reversing_digits(self):
        for matrix in ((0,1,-1,0),(-1,0,0,-1),(0,-1,1,0)):
            with self.subTest(matrix=matrix):
                data=self.create_pdf(text_matrix=matrix)
                result=correlate_pdf_dimensions(self.path,data)
                self.assertEqual(result['status'],'verified',result)
                self.assertEqual(result['associations'][0]['text'],'514')
