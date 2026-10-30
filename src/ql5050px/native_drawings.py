"""Manufacturing SLDDRW/DXF adapter with explicit, mapped selection references."""
from pathlib import Path
import math
from .native_machine import NativeMachineDriver, read_member
from .native_exports import NativeExportsMixin
from .drawing_layout import DrawingAnnotationsMixin
from .assembly_builder import finite
from .drawing_verification import (lock_view_layout,verify_view_layout,
                                  annotation_evidence,verify_annotation_evidence)
from sw_compat.annotation import read_annotation_position,set_annotation_position


def model_view_name(requested,available):
    if requested in available:return requested
    aliases={'*Front':'*前视','*Back':'*后视','*Left':'*左视','*Right':'*右视',
             '*Top':'*上视','*Bottom':'*下视','*Isometric':'*等轴测'}
    alternate=aliases.get(requested)
    if alternate in available:return alternate
    raise ValueError('requested model view is unavailable: '+str(requested))


def insert_linked_bom(view,configuration,template,kind='parts_only'):
    template=Path(template).resolve()
    if not template.is_file():raise FileNotFoundError(template)
    types={'parts_only':1,'top_level':2,'indented':3}
    if kind not in types:raise ValueError('unsupported BOM type')
    table=view.InsertBomTable4(False,.22,.25,1,types[kind],
        '' if kind=='top_level' else configuration,str(template),False,0,False)
    if table is not None and kind=='top_level':
        configure_top_level_bom(table,configuration)
    return table


def configure_top_level_bom(table,configuration):
    """An empty InsertBomTable4 configuration does not select visible configs."""
    import pythoncom
    import win32com.client
    from solidworks_generator import _as_interface,ensure_solidworks_typelib
    feature=_as_interface(ensure_solidworks_typelib(),read_member(table,'BomFeature'),'IBomFeature')
    visible=win32com.client.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BOOL,[True])
    names=win32com.client.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_BSTR,[configuration])
    if not feature.SetConfigurations(False,visible,names):
        raise RuntimeError('native BOM configuration binding failed')


class ManufacturingDriver(NativeMachineDriver,NativeExportsMixin,DrawingAnnotationsMixin):
    def _remember_drawing_document(self,model):
        if getattr(self,'_drawing_transaction_active',False):
            self.__dict__.setdefault('_drawing_open_documents',{})[id(model)]=model
        return model

    def open_document(self,*args,**kwargs):
        return self._remember_drawing_document(super().open_document(*args,**kwargs))

    def close_document(self,model):
        result=super().close_document(model)
        self.__dict__.get('_drawing_open_documents',{}).pop(id(model),None)
        return result
    def require_isolated_model(self,path):
        self.owned_path(path)
        if not Path(path).is_file(): raise FileNotFoundError(path)

    def resolve_owned_model(self,path):
        self.require_isolated_model(path)
        return self.open_document(path)

    def select_drawing_entity(self,drawing,reference):
        self.guard()
        if not drawing.Extension.SelectByID2(reference['name'],reference['type'],
                *[finite(v)/1000 for v in reference.get('point_mm',[0,0,0])],True,0,None,0):
            raise RuntimeError('drawing selection failed: '+reference['name'])

    def export_manufacturing(self,plan,assembly_receipt,destination):
        from drawing_review import DrawingEvidence,atomic_json
        self.guard()
        if plan['status']!='ready_for_native':raise ValueError('drawing plan has pending engineering data')
        folder=self.owned_path(destination);folder.mkdir(parents=True,exist_ok=False)
        atomic_json(folder/'drawing-index.json',{'schema_version':1,'pages':[
            {'task':task.get('id'),'evidence':f'evidence/drawing-{i+1:04d}.json'}
            for i,task in enumerate(plan['tasks'])]},exclusive=True)
        results=[]
        for index,task in enumerate(plan['tasks']):
            required=['slddrw']
            if getattr(self,'requires_pdf_evidence',False):required.append('pdf')
            if 'flat_DXF' in task.get('exports',[]):required.append('flat_dxf')
            evidence=DrawingEvidence(folder/'evidence'/f'drawing-{index+1:04d}.json',task,
                simulated_only=getattr(self,'simulated',False),
                partial_model_test=getattr(self,'partial_model_test',False),required_artifacts=required,
                model_path=assembly_receipt['documents'][task['node']]['path'])
            attempt=getattr(self.lease,'durable_attempt',None)
            if attempt:
                store,key,_=attempt
                evidence.data['request_receipt']={'database':str(store.path),'key':key}
            try:
                with evidence.observe_com():
                    result=self._export_manufacturing_unreviewed({**plan,'tasks':[task]},assembly_receipt,
                                                                 folder,_evidence=evidence)
                item=result['results'][0]
                evidence.artifact('slddrw',item['path'])
                if item.get('flat_dxf'):evidence.artifact('flat_dxf',item['flat_dxf'])
                evidence.finish()
                item.update(drawing_evidence=str(evidence.path),acceptance_state='reviewing',delivery_accepted=False)
                results.append(item)
            except Exception as error:
                evidence.fail(error)
                raise
        return {'results':results,'native_status':'files_created_reopened',
                'acceptance_state':'reviewing','delivery_accepted':False,'manufacturing_approved':False}

    def _export_manufacturing_unreviewed(self,plan,assembly_receipt,destination,*,_evidence):
        self.guard()
        if plan['status']!='ready_for_native': raise ValueError('drawing plan has pending engineering data')
        folder = self.owned_path(destination)
        results = []
        for task in plan['tasks']:
            model_path = assembly_receipt['documents'][task['node']]['path']
            self.require_isolated_model(model_path)
            source_model=self.open_document(model_path,assembly_receipt['documents'][task['node']]['configuration'],readonly=True)
            available_views=list(read_member(source_model,'GetModelViewNames') or [])
            template=Path(task['template']).resolve()
            if not template.is_file():raise FileNotFoundError(template)
            drawing = self.app.NewDocument(str(template),12,task['width_mm']/1000,task['height_mm']/1000)
            if drawing is None: raise RuntimeError('manufacturing drawing NewDocument failed')
            from sw_compat.model_document import model_document
            drawing=model_document(drawing)
            self.lease.note_owned_document(str(read_member(drawing,'GetTitle')),handle_id=id(drawing))
            self._remember_drawing_document(drawing)
            if task.get('projection')=='first_angle':
                properties=read_member(drawing.GetCurrentSheet(),'GetProperties2')
                if len(properties)<5 or properties[4] not in (True,1):
                    raise RuntimeError('drawing template first-angle projection readback mismatch')
            if task.get('sheet_format'):
                sheet = drawing.GetCurrentSheet()
                sheet.SetTemplateName(task['sheet_format'])
                if not sheet.ReloadTemplate(True): raise RuntimeError('drawing sheet format reload failed')
            scale = task['scale']
            if len(scale)!=2 or min(map(finite,scale))<=0: raise ValueError('positive scale ratio required')
            drawing.GetCurrentSheet().SetScale(scale[0],scale[1],True,True)
            # Set document linear units to mm without inventing precision/tolerance.
            drawing.SetUnits(0,0,0,int(task.get('decimal_places',3)),False)
            views = {}
            for item in task['drawing_model']['views']:
                x,y = [finite(v)/1000 for v in item['position_mm']]
                if item['kind']=='model':
                    orientation=model_view_name(item['orientation'],available_views)
                    view = drawing.CreateDrawViewFromModelView3(model_path,orientation,x,y,0)
                elif item['kind']=='flat':
                    configuration = assembly_receipt['documents'][task['node']]['configuration']
                    view = drawing.CreateFlatPatternViewFromModelView3(model_path,configuration,x,y,0,False,False)
                else:
                    parent = views[item['parent']]
                    if not drawing.Extension.SelectByID2(str(read_member(parent,'GetName2')),'DRAWINGVIEW',0,0,0,False,0,None,0):
                        raise RuntimeError('projected view parent selection failed')
                    view = drawing.CreateUnfoldedViewAt3(x,y,0,False)
                if view is None: raise RuntimeError('native view creation failed')
                if item['kind']=='model':
                    configuration = assembly_receipt['documents'][task['node']]['configuration']
                    if task.get('configuration') and task['configuration'] != configuration:
                        raise ValueError('drawing task configuration conflicts with modified model receipt')
                    view.ReferencedConfiguration = configuration
                    if str(read_member(view,'ReferencedConfiguration')) != configuration:
                        raise RuntimeError('drawing model configuration readback mismatch')
                views[item['id']] = view
                drawing.ClearSelection2(True)
            layout_evidence=lock_view_layout(drawing,task,views)
            for dimension in task['dimensions']:
                drawing.ClearSelection2(True)
                for reference in dimension['references']: self.select_drawing_entity(drawing,reference)
                x,y = [finite(v)/1000 for v in dimension['position_mm']]
                method = {'horizontal':'AddHorizontalDimension2','vertical':'AddVerticalDimension2',
                          'general':'AddDimension2'}[dimension.get('kind','general')]
                display = getattr(drawing,method)(x,y,0)
                if display is None: raise RuntimeError('native drawing dimension failed')
                _evidence.data['annotations'].append(annotation_evidence(display,'dimension',dimension))
                # No cosmetic numeric override; dimension must come from selected model entities.
            for annotation in task['annotations']:
                drawing.ClearSelection2(True)
                if annotation.get('reference'): self.select_drawing_entity(drawing,annotation['reference'])
                note = drawing.InsertNote(annotation['text'])
                if note is None: raise RuntimeError('drawing note failed')
                x,y = [finite(v)/1000 for v in annotation['position_mm']]
                set_annotation_position(note,x,y,0)
                _evidence.data['annotations'].append(annotation_evidence(note,'note',annotation))
            bom = task['drawing_model']['bom']
            bom_evidence=None
            if bom:
                model_views = [views[v['id']] for v in task['drawing_model']['views'] if v['kind']=='model']
                if not model_views: raise ValueError('assembly BOM requires a model view')
                configuration = assembly_receipt['documents'][task['node']]['configuration']
                table=insert_linked_bom(model_views[0],configuration,task['bom_template'],task.get('bom_type','parts_only'))
                if table is None: raise RuntimeError('native linked BOM table failed')
                from solidworks_generator import _as_interface,ensure_solidworks_typelib
                native_table=_as_interface(ensure_solidworks_typelib(),table,'ITableAnnotation')
                if task.get('auto_layout'):
                    width=sum(float(native_table.GetColumnWidth(c))*1000 for c in range(int(read_member(native_table,'ColumnCount'))))
                    task['bom_position_mm']=[task['width_mm']-10-width,task['height_mm']-30]
                if task.get('bom_position_mm'):
                    x,y=[finite(v)/1000 for v in task['bom_position_mm']]
                    set_annotation_position(native_table,x,y,0)
                bom_evidence={'rows':int(read_member(native_table,'RowCount')),
                              'columns':int(read_member(native_table,'ColumnCount')),
                              'configuration':configuration}
                if bom_evidence['rows']<=1:
                    raise RuntimeError('native BOM has no component data rows')
                if task.get('bom_position_mm'):
                    position=read_annotation_position(native_table)
                    bx,by=[float(v)*1000 for v in position[:2]]
                    tw=sum(float(native_table.GetColumnWidth(c))*1000 for c in range(bom_evidence['columns']))
                    th=sum(float(native_table.GetRowHeight(r))*1000 for r in range(bom_evidence['rows']))
                    bounds=[bx,by-th,bx+tw,by]
                    frame=layout_evidence['frame_bounds_mm']
                    if not all(math.isfinite(v) for v in bounds) or tw<=0 or th<=0 or bounds[0]<frame[0] or bounds[1]<frame[1] or bounds[2]>frame[2] or bounds[3]>frame[3]:
                        raise RuntimeError('BOM exceeds drawing frame')
                    verify_view_layout(drawing,{**task,'reserved_rectangles_mm':task.get('reserved_rectangles_mm',[])+[bounds]},views)
                    bom_evidence['bounds_mm']=bounds
                _evidence.data['annotations'].append(annotation_evidence(native_table,'bom',{'linked':True}))
            for balloon in task['balloons']:
                drawing.ClearSelection2(True)
                self.select_drawing_entity(drawing,balloon['reference'])
                options = drawing.Extension.CreateBalloonOptions()
                if options is None: raise RuntimeError('balloon options unavailable')
                options.Style = 1
                options.UpperTextContent = 1  # Item number; follows assembly BOM, no invented text.
                note = drawing.Extension.InsertBOMBalloon2(options)
                if note is None: raise RuntimeError('BOM balloon insertion failed')
                x,y = [finite(v)/1000 for v in balloon['position_mm']]
                set_annotation_position(note,x,y,0)
                _evidence.data['annotations'].append(annotation_evidence(note,'balloon',balloon))
            output = folder/task['filename']
            view_names={name:str(read_member(view,'GetName2')) for name,view in views.items()}
            receipt = self.save_reopen(drawing,output,'')
            reopened=self.open_document(output,readonly=True)
            try:
                actual_views={}
                view=read_member(reopened,'GetFirstView')
                view=read_member(view,'GetNextView')
                by_name={}
                while view is not None:
                    by_name[str(read_member(view,'GetName2'))]=view
                    view=read_member(view,'GetNextView')
                for name,native_name in view_names.items():
                    if native_name not in by_name:raise RuntimeError('saved drawing view missing: '+native_name)
                    actual_views[name]=by_name[native_name]
                receipt['layout_readback']=verify_view_layout(reopened,task,actual_views)
                _evidence.data['layout_readback']=receipt['layout_readback']
                _evidence.data['views']=[{'id':name,'native_name':view_names[name],
                    'scale':float(read_member(view,'ScaleDecimal')),
                    'position_mm':[float(v)*1000 for v in read_member(view,'Position')],
                    'bounds_mm':[float(v)*1000 for v in read_member(view,'GetOutline')]}
                    for name,view in actual_views.items()]
                _evidence.data['annotations']=verify_annotation_evidence(reopened,_evidence.data['annotations'])
                _evidence.data['annotation_reopen_verified']=True
            finally:self.close_document(reopened)
            if bom_evidence:
                receipt['bom_readback']=bom_evidence
                _evidence.data['bom_readback']=bom_evidence
            if 'flat_DXF' in task['exports']:
                part = self.open_document(model_path,assembly_receipt['documents'][task['node']]['configuration'])
                dxf = folder/(Path(task['filename']).stem+'-flat.dxf')
                if not part.ExportToDWG2(str(dxf),model_path,1,True,None,False,False,5,None) or not dxf.is_file():
                    raise RuntimeError('flat manufacturing DXF export failed')
                receipt['flat_dxf'] = str(dxf)
                self.close_document(part)
            self.close_document(source_model)
            results.append({'task':task['id'],**receipt,'manufacturing_approved':False})
        return {'results':results,'native_status':'files_created_reopened','manufacturing_approved':False}

