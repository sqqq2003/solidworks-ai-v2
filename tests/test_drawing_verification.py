from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject
from ql5050px.drawing_verification import validate_pdf,verify_view_layout,lock_view_layout,export_pdf
from ql5050px.manufacturing_drawings import apply_sheet_case,drawing_sheet_cases,plan_drawings
from ql5050px.native_machine import read_member
from sw_compat.annotation import read_annotation_position,set_annotation_position
from sw_compat.model_document import DualDocument,model_document


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

    def test_model_document_passes_mocks_and_casts_ole_documents(self):
        drawing_mock=MagicMock()
        self.assertIs(model_document(drawing_mock),drawing_mock)
        part=NS(_oleobj_=object(),GetType=lambda:1)
        with patch('solidworks_generator.ensure_solidworks_typelib',return_value='lib'), \
             patch('solidworks_generator._as_interface',side_effect=lambda module,obj,interface:interface):
            self.assertEqual(model_document(part),'IModelDoc2')

    def test_drawing_dual_cast_reads_title_from_model_face(self):
        class DrawingFace:
            def GetCurrentSheet(self):
                return 'sheet'
            def GetTitle(self):
                raise AssertionError('IDrawingDoc GetTitle hangs')
        class ModelFace:
            @property
            def GetType(self):
                return 3
            def GetTitle(self):
                return 'A2-10'
            @property
            def Extension(self):
                return 'extension'
        raw=NS(_oleobj_=object())
        faces={'IDrawingDoc':DrawingFace(),'IModelDoc2':ModelFace()}
        with patch('solidworks_generator.ensure_solidworks_typelib',return_value='lib'), \
             patch('solidworks_generator._as_interface',side_effect=lambda module,obj,interface:faces[interface]) as cast:
            wrapped=model_document(raw)
        self.assertIsInstance(wrapped,DualDocument)
        self.assertEqual([call.args[2] for call in cast.call_args_list],['IModelDoc2','IDrawingDoc'])
        self.assertEqual(read_member(wrapped,'GetTitle'),'A2-10')
        self.assertEqual(read_member(wrapped,'GetCurrentSheet'),'sheet')
        self.assertEqual(wrapped.Extension,'extension')

    def test_annotation_property_is_not_called_and_member_not_found_rebinds(self):
        class CallableAnnotation:
            def __init__(self):
                self.called=False
                self.position=None
            def __call__(self):
                self.called=True
                raise OSError(-2147352573,'DISP_E_MEMBERNOTFOUND')
            def SetPosition2(self,x,y,z):
                self.position=(x,y,z)
                return True
            def GetPosition(self):
                return (0.1,0.2,0)
        ann=CallableAnnotation()
        class Note:
            @property
            def GetAnnotation(self):
                return ann
        set_annotation_position(Note(),0.15,0.22,0)
        self.assertFalse(ann.called)
        self.assertEqual(ann.position,(0.15,0.22,0))
        self.assertEqual(tuple(read_annotation_position(Note())),(0.1,0.2,0))

        class RawAnnotation:
            def __init__(self):
                self._oleobj_=object()
            def SetPosition2(self,x,y,z):
                raise OSError(-2147352573,'DISP_E_MEMBERNOTFOUND')
            def GetPosition(self):
                raise OSError(-2147352573,'DISP_E_MEMBERNOTFOUND')
        class TypedAnnotation:
            def __init__(self):
                self.position=None
            def SetPosition2(self,x,y,z):
                self.position=(x,y,z)
                return True
            @property
            def GetPosition(self):
                return (0.2,0.3,0)
        typed=TypedAnnotation()
        raw=RawAnnotation()
        class MethodNote:
            def GetAnnotation(self):
                raise OSError(-2147352573,'DISP_E_MEMBERNOTFOUND')
            @property
            def IGetAnnotation(self):
                return raw
        with patch('solidworks_generator.ensure_solidworks_typelib',return_value='lib'), \
             patch('solidworks_generator._as_interface',return_value=typed) as cast:
            set_annotation_position(MethodNote(),0.05,0.06,0)
            self.assertEqual(tuple(read_annotation_position(MethodNote())),(0.2,0.3,0))
        self.assertEqual(typed.position,(0.05,0.06,0))
        self.assertEqual(cast.call_args.args[2],'IAnnotation')

    def test_d4_scale_template_matrix_is_settings_data(self):
        templates={'A2':'sheets/a2.drwdot','A3':'sheets/a3.drwdot'}
        cases=drawing_sheet_cases(templates)
        self.assertEqual([(c['sheet'],c['scale_label']) for c in cases],
            [('A2','1:5'),('A2','1:10'),('A2','1:20'),('A3','1:5'),('A3','1:10'),('A3','1:20')])
        a2_tenth=next(c for c in cases if c['sheet']=='A2' and c['scale_label']=='1:10')
        self.assertEqual(a2_tenth,{'sheet':'A2','scale_label':'1:10','width_mm':594,'height_mm':420,
            'scale':[1,10],'template':'sheets/a2.drwdot'})
        settings=apply_sheet_case({'revision':'DEV','scale':[1,1]},a2_tenth)
        self.assertEqual(settings['part_template'],'sheets/a2.drwdot')
        self.assertEqual(settings['scale'],[1,10])
        self.assertEqual(settings['width_mm'],594)
        plan=plan_drawings(
            {'tree':{'root':'frame','catalog':{'frame':{'type':'part','part_number':'QL-FRAME','material':'Q235'}}},
             'dependency_order':['frame']},
            part_parameters={'frame':{'views':[{'kind':'model','orientation':'*Front'}],
                'dimensions':[{'references':[{'name':'e1'}],'status':'confirmed'}],
                'process':'laser','datum_scheme':'A','tolerance_scheme':'GB'}},
            settings=settings)
        task=plan['tasks'][0]
        self.assertEqual(task['scale'],[1,10])
        self.assertEqual(task['width_mm'],594)
        self.assertEqual(task['height_mm'],420)
        self.assertEqual(task['template'],'sheets/a2.drwdot')

if __name__=='__main__':unittest.main()
