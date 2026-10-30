from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject
from ql5050px.drawing_verification import validate_pdf,verify_view_layout,lock_view_layout,export_pdf,view_exceeds_frame
from ql5050px.manufacturing_drawings import apply_sheet_case,drawing_sheet_cases,plan_drawings
from ql5050px.native_machine import read_member
from sw_compat.annotation import read_annotation_position,set_annotation_position
from sw_compat.com_access import DISPATCH_METHOD,DISPATCH_PROPERTYGET
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

    def test_undeclared_note_getannotation_still_invokes_com(self):
        # 9dd6908 A2 failure: InsertNote's return does not declare GetAnnotation.
        calls=[]
        class Ann:
            def __init__(self):
                self.position=None
            def SetPosition2(self,x,y,z):
                self.position=(x,y,z)
                return True
        ann=Ann()
        class Ole:
            def GetIDsOfNames(self,name):
                if name!='GetAnnotation':
                    raise OSError(-2147352570,'DISP_E_UNKNOWNNAME')
                return 7
            def Invoke(self,dispid,lcid,flags,wanted,*args):
                calls.append(flags)
                if flags==DISPATCH_PROPERTYGET:
                    raise OSError(-2147352573,'DISP_E_MEMBERNOTFOUND')
                if flags==DISPATCH_METHOD:
                    return ann
                raise AssertionError(flags)
        class Note:
            def __init__(self):
                self._oleobj_=Ole()
        set_annotation_position(Note(),0.11,0.22,0)
        self.assertEqual(calls,[DISPATCH_PROPERTYGET,DISPATCH_METHOD])
        self.assertEqual(ann.position,(0.11,0.22,0))

    def test_getnextview_propget_is_not_called_as_method(self):
        # SW2025: GetNextView is a propget. The generated method raises
        # DISP_E_MEMBERNOTFOUND. The post-SaveAs walk must not call it.
        calls=[]
        front=NS(GetName2='Front')
        class Ole:
            def __init__(self,result):
                self.result=result
            def GetIDsOfNames(self,name):
                if name!='GetNextView':
                    raise OSError(-2147352570,'DISP_E_UNKNOWNNAME')
                return 9
            def Invoke(self,dispid,lcid,flags,wanted,*args):
                calls.append(flags)
                if flags!=DISPATCH_PROPERTYGET:
                    raise OSError(-2147352573,'找不到成员。')
                return self.result
        class View:
            def __init__(self,result):
                self._oleobj_=Ole(result)
                self.method_calls=0
            def GetNextView(self):
                self.method_calls+=1
                raise OSError(-2147352573,'DISP_E_MEMBERNOTFOUND')
        sheet=View(front)
        self.assertIs(read_member(sheet,'GetNextView'),front)
        self.assertEqual(sheet.method_calls,0)
        self.assertEqual(calls,[DISPATCH_PROPERTYGET])
        end=View(None)
        self.assertIsNone(read_member(end,'GetNextView'))
        self.assertEqual(end.method_calls,0)
        self.assertEqual(calls,[DISPATCH_PROPERTYGET,DISPATCH_PROPERTYGET])

        class Legacy:
            def __init__(self):
                self.method_calls=0
            def GetNextView(self):
                self.method_calls+=1
                return front
        legacy=Legacy()
        self.assertIs(read_member(legacy,'GetNextView'),front)
        self.assertEqual(legacy.method_calls,1)

        class NameOle:
            def GetIDsOfNames(self,name):
                if name!='GetName2':
                    raise OSError(-2147352570,'DISP_E_UNKNOWNNAME')
                return 4
            def Invoke(self,dispid,lcid,flags,wanted,*args):
                if flags!=DISPATCH_PROPERTYGET:
                    raise OSError(-2147352573,'找不到成员。')
                return 'Front'
        class Named:
            def __init__(self):
                self._oleobj_=NameOle()
            def GetName2(self):
                raise OSError(-2147352573,'DISP_E_MEMBERNOTFOUND')
        self.assertEqual(read_member(Named(),'GetName2'),'Front')

    def test_save_as_retargets_only_the_leased_drawing_title(self):
        from sw_session import SessionLease,SessionOwnershipError
        from ql5050px.native_machine import retarget_saved_title
        lease=SessionLease('drawing-save')
        lease.note_owned_document('绘图1',handle_id=1)
        lease.foreign_titles.add('FX-PX-ZYQDYT-001×1.SLDASM')
        saved=NS(GetTitle='QL-5050PX-A2R-A2_1-10.SLDDRW')
        self.assertEqual(retarget_saved_title(lease,'绘图1',saved),'QL-5050PX-A2R-A2_1-10.SLDDRW')
        self.assertNotIn('绘图1',lease.owned_docs)
        self.assertIn('QL-5050PX-A2R-A2_1-10.SLDDRW',lease.owned_docs)
        self.assertIs(retarget_saved_title(lease,'QL-5050PX-A2R-A2_1-10.SLDDRW',saved),'QL-5050PX-A2R-A2_1-10.SLDDRW')
        with self.assertRaises(SessionOwnershipError):
            retarget_saved_title(lease,'QL-5050PX-A2R-A2_1-10.SLDDRW',NS(GetTitle='FX-PX-ZYQDYT-001×1.SLDASM'))

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


class _AnchoredView:
    """GetOutline center = Position - anchor. Anchor is constant in sheet mm."""
    def __init__(self, size_mm, anchor_mm, scale):
        self.size_mm=[float(v) for v in size_mm]
        self.anchor_mm=[float(v) for v in anchor_mm]
        self.position_mm=[100.0,100.0]
        self.ScaleDecimal=scale
        self.UseSheetScale=0
        self.writes=0
    @property
    def Position(self):
        return (self.position_mm[0]/1000, self.position_mm[1]/1000)
    @Position.setter
    def Position(self, value):
        coords=list(value)
        self.position_mm=[float(coords[0])*1000, float(coords[1])*1000]
        self.writes+=1
    def GetOutline(self):
        cx=self.position_mm[0]-self.anchor_mm[0]
        cy=self.position_mm[1]-self.anchor_mm[1]
        w,h=self.size_mm
        return [(cx-w/2)/1000,(cy-h/2)/1000,(cx+w/2)/1000,(cy+h/2)/1000]


class _BiasedView(_AnchoredView):
    """First outline read is shifted; the shift clears once Position is written."""
    def __init__(self, size_mm, scale, bias_mm):
        super().__init__(size_mm, [0,0], scale)
        self.bias_mm=list(bias_mm)
    def GetOutline(self):
        cx=self.position_mm[0]-self.anchor_mm[0]+self.bias_mm[0]
        cy=self.position_mm[1]-self.anchor_mm[1]+self.bias_mm[1]
        w,h=self.size_mm
        return [(cx-w/2)/1000,(cy-h/2)/1000,(cx+w/2)/1000,(cy+h/2)/1000]
    @property
    def Position(self):
        return (self.position_mm[0]/1000, self.position_mm[1]/1000)
    @Position.setter
    def Position(self, value):
        _AnchoredView.Position.fset(self, value)
        self.bias_mm=[0,0]


class _LaggingView(_AnchoredView):
    """GetOutline follows Position one EditRebuild3 behind."""
    def __init__(self, size_mm, anchor_mm, scale):
        super().__init__(size_mm, anchor_mm, scale)
        self._shown=list(self.position_mm)
        self._pending=None
        self.publishes=0
    def publish(self):
        self.publishes+=1
        if self._pending is not None:self._shown=list(self._pending)
        self._pending=list(self.position_mm)
    def GetOutline(self):
        cx=self._shown[0]-self.anchor_mm[0]
        cy=self._shown[1]-self.anchor_mm[1]
        w,h=self.size_mm
        return [(cx-w/2)/1000,(cy-h/2)/1000,(cx+w/2)/1000,(cy+h/2)/1000]


class _PublishingDrawing:
    def __init__(self, sheet, views):
        self._sheet=sheet
        self._views=list(views)
    def GetCurrentSheet(self):
        return self._sheet
    def EditRebuild3(self):
        for view in self._views:
            publish=getattr(view,'publish',None)
            if publish:publish()
        return True


class _GrowingView(_AnchoredView):
    def __init__(self, stale_mm, real_mm, scale):
        super().__init__(stale_mm, [0,0], scale)
        self.real_mm=[float(v) for v in real_mm]
    @property
    def Position(self):
        return (self.position_mm[0]/1000, self.position_mm[1]/1000)
    @Position.setter
    def Position(self, value):
        _AnchoredView.Position.fset(self, value)
        self.size_mm=self.real_mm


class FrameFitLayoutTests(unittest.TestCase):
    def _sheet(self, numerator, denominator, width_mm, height_mm):
        drawing,sheet,_,_=DrawingVerificationTests().fixture()
        sheet.GetProperties2.return_value=[12,0,numerator,denominator,True,width_mm/1000,height_mm/1000]
        return drawing,sheet

    def _task(self, scale, width_mm, height_mm):
        return {'scale':list(scale),'width_mm':width_mm,'height_mm':height_mm,'auto_layout':True,
                'drawing_model':{'views':[{'id':name,'position_mm':[100,100]} for name in ('front','top','right')]}}

    def _assert_scale_locked(self, sheet, scale):
        sheet.SetScale.assert_called_once_with(scale[0], scale[1], True, True)

    def test_a2_tenth_envelope_still_fits_without_changing_scale(self):
        # Known-good cell. Zero anchor: Position and the outline center match.
        drawing,sheet=self._sheet(1,10,594,420)
        sizes={'front':[110.5,143.0],'top':[110.5,180.32],'right':[180.32,143.0]}
        views={name:_AnchoredView(size,[0,0],0.1) for name,size in sizes.items()}
        task=self._task([1,10],594,420)
        proof=lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,10])
        self.assertEqual(proof['sheet_scale'],[1,10])
        self.assertEqual(task['scale'],[1,10])
        self.assertEqual({item['name'] for item in proof['views']},{'front','top','right'})
        self.assertTrue(all(view.writes==1 for view in views.values()))

    def test_a3_top_anchor_fits_at_one_to_ten(self):
        # Live cell A3_1-10: top outline exceeded the frame. Scale stays 1:10.
        drawing,sheet=self._sheet(1,10,420,297)
        sizes={'front':[90,70],'top':[90,80],'right':[70,70]}
        anchors={'front':[0,0],'top':[0,40],'right':[0,0]}
        views={name:_AnchoredView(sizes[name],anchors[name],0.1) for name in sizes}
        task=self._task([1,10],420,297)
        proof=lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,10])
        self.assertEqual(task['scale'],[1,10])
        self.assertEqual(proof['sheet_size_mm'][0],420)
        top=next(item for item in proof['views'] if item['name']=='top')
        self.assertFalse(view_exceeds_frame(top['bounds_mm'], proof['frame_bounds_mm']))
        self.assertEqual({item['name'] for item in proof['views']},{'front','top','right'})
        self.assertTrue(all(view.writes==1 for view in views.values()))

    def test_a2_front_anchor_fits_at_one_to_five(self):
        # Live cell A2_1-5: front outline exceeded the frame. Scale stays 1:5.
        drawing,sheet=self._sheet(1,5,594,420)
        sizes={'front':[100,180],'top':[100,180],'right':[120,180]}
        anchors={'front':[0,-40],'top':[0,0],'right':[0,0]}
        views={name:_AnchoredView(sizes[name],anchors[name],1/5) for name in sizes}
        task=self._task([1,5],594,420)
        proof=lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,5])
        self.assertEqual(proof['sheet_scale'],[1,5])
        self.assertEqual(task['scale'],[1,5])
        front=next(item for item in proof['views'] if item['name']=='front')
        self.assertFalse(view_exceeds_frame(front['bounds_mm'], proof['frame_bounds_mm']))
        self.assertEqual({item['name'] for item in proof['views']},{'front','top','right'})

    def test_outline_that_misses_the_slot_is_nudged_without_rescaling(self):
        drawing,sheet=self._sheet(1,10,420,297)
        sizes={'front':[90,70],'top':[90,80],'right':[70,70]}
        views={name:_BiasedView(size,0.1,[0,8] if name=='top' else [0,0]) for name,size in sizes.items()}
        task=self._task([1,10],420,297)
        proof=lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,10])
        self.assertGreaterEqual(views['top'].writes,2)
        top=next(item for item in proof['views'] if item['name']=='top')
        self.assertFalse(view_exceeds_frame(top['bounds_mm'], proof['frame_bounds_mm']))
        self.assertEqual(task['scale'],[1,10])

    def test_stale_outline_is_replaced_at_the_same_scale(self):
        drawing,sheet=self._sheet(1,10,420,297)
        real={'front':[90,70],'top':[90,80],'right':[70,70]}
        views={name:_GrowingView([20,20],size,0.1) for name,size in real.items()}
        task=self._task([1,10],420,297)
        proof=lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,10])
        self.assertTrue(all(view.writes==2 for view in views.values()))
        self.assertEqual({item['name'] for item in proof['views']},{'front','top','right'})
        self.assertTrue(all(not view_exceeds_frame(item['bounds_mm'], proof['frame_bounds_mm']) for item in proof['views']))

    def test_oversize_envelope_is_not_autoscaled(self):
        # The 1:10 measurement does not fit A3. Refusal keeps 1:10; no second scale.
        drawing,sheet=self._sheet(1,10,420,297)
        measured={'front':[110.5,143.0],'top':[110.5,180.32],'right':[180.32,143.0]}
        views={name:_AnchoredView(size,[0,0],0.1) for name,size in measured.items()}
        task=self._task([1,10],420,297)
        with self.assertRaisesRegex(ValueError,'does_not_fit') as caught:
            lock_view_layout(drawing,task,views)
        self.assertIn('outlines_mm=',str(caught.exception))
        self.assertIn('sizes_mm=',str(caught.exception))
        self._assert_scale_locked(sheet,[1,10])
        self.assertEqual(task['scale'],[1,10])
        self.assertTrue(all(view.writes==0 for view in views.values()))

    def test_grown_outline_that_cannot_fit_is_not_autoscaled(self):
        drawing,sheet=self._sheet(1,5,594,420)
        real={'front':[221,286],'top':[221,360.64],'right':[360.64,286]}
        views={name:_GrowingView([20,20],size,0.2) for name,size in real.items()}
        task=self._task([1,5],594,420)
        with self.assertRaisesRegex(ValueError,'does_not_fit'):
            lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,5])
        self.assertEqual(task['scale'],[1,5])
        self.assertTrue(all(view.writes==1 for view in views.values()))

    def test_lagged_outline_settles_before_the_frame_check(self):
        # 18a718db nudged once against a stale GetOutline. A later rebuild then
        # left the real outline outside the frame. Wait until the outline follows.
        _,sheet=self._sheet(1,10,420,297)
        sizes={'front':[90,70],'top':[90,80],'right':[70,70]}
        anchors={'front':[0,0],'top':[0,40],'right':[0,0]}
        views={name:_LaggingView(sizes[name],anchors[name],0.1) for name in sizes}
        drawing=_PublishingDrawing(sheet,views.values())
        task=self._task([1,10],420,297)
        proof=lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,10])
        self.assertEqual(task['scale'],[1,10])
        self.assertTrue(all(view.writes==1 for view in views.values()))
        self.assertGreaterEqual(views['top'].publishes,3)
        for view in views.values():view.publish()
        for view in views.values():
            box=[float(v)*1000 for v in view.GetOutline()]
            self.assertFalse(view_exceeds_frame(box, proof['frame_bounds_mm']))

    def test_wide_a3_top_view_clears_title_block_without_rescaling(self):
        # Live A3_1-20: top overlapped the reserved title block.
        drawing,sheet=self._sheet(1,20,420,297)
        sizes={'front':[80,40],'top':[200,40],'right':[40,40]}
        views={name:_AnchoredView(size,[0,30] if name=='top' else [0,0],0.05) for name,size in sizes.items()}
        task=self._task([1,20],420,297)
        proof=lock_view_layout(drawing,task,views)
        self._assert_scale_locked(sheet,[1,20])
        self.assertEqual(proof['sheet_scale'],[1,20])
        self.assertEqual({item['name'] for item in proof['views']},{'front','top','right'})
        title=[420-180,0,420,60]
        for item in proof['views']:
            box=item['bounds_mm']
            self.assertFalse(view_exceeds_frame(box, proof['frame_bounds_mm']))
            self.assertFalse(min(box[2],title[2])-max(box[0],title[0])>0.1 and min(box[3],title[3])-max(box[1],title[1])>0.1)

if __name__=='__main__':unittest.main()
