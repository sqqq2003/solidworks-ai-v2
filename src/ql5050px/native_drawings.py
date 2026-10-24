"""Manufacturing SLDDRW/DXF adapter with explicit, mapped selection references."""
from pathlib import Path
from .native_machine import NativeMachineDriver, read_member
from .native_exports import NativeExportsMixin
from .drawing_layout import DrawingAnnotationsMixin
from .assembly_builder import finite


class ManufacturingDriver(NativeMachineDriver,NativeExportsMixin,DrawingAnnotationsMixin):
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
        self.guard()
        if plan['status']!='ready_for_native': raise ValueError('drawing plan has pending engineering data')
        folder = self.owned_path(destination)
        folder.mkdir(parents=True,exist_ok=False)
        results = []
        for task in plan['tasks']:
            model_path = assembly_receipt['documents'][task['node']]['path']
            self.require_isolated_model(model_path)
            drawing = self.app.NewDocument(task['template'],12,task['width_mm']/1000,task['height_mm']/1000)
            if drawing is None: raise RuntimeError('manufacturing drawing NewDocument failed')
            self.lease.note_owned_document(str(read_member(drawing,'GetTitle')),handle_id=id(drawing))
            if task.get('sheet_format'):
                sheet = drawing.GetCurrentSheet()
                sheet.SetTemplateName(task['sheet_format'])
                if not sheet.ReloadTemplate(True): raise RuntimeError('drawing sheet format reload failed')
            scale = task['scale']
            if len(scale)!=2 or min(map(finite,scale))<=0: raise ValueError('positive scale ratio required')
            drawing.GetCurrentSheet().SetScale(scale[0],scale[1],True,True)
            # Set document linear units to mm without inventing precision/tolerance.
            drawing.SetUnits(0,0,0,False)
            views = {}
            for item in task['drawing_model']['views']:
                x,y = [finite(v)/1000 for v in item['position_mm']]
                if item['kind']=='model':
                    view = drawing.CreateDrawViewFromModelView3(model_path,item['orientation'],x,y,0)
                elif item['kind']=='flat':
                    configuration = assembly_receipt['documents'][task['node']]['configuration']
                    view = drawing.CreateFlatPatternViewFromModelView3(model_path,configuration,x,y,0,False,False)
                else:
                    parent = views[item['parent']]
                    if not drawing.Extension.SelectByID2(str(read_member(parent,'GetName2')),'DRAWINGVIEW',0,0,0,False,0,None,0):
                        raise RuntimeError('projected view parent selection failed')
                    view = drawing.CreateUnfoldedViewAt3(x,y,0,False)
                if view is None: raise RuntimeError('native view creation failed')
                views[item['id']] = view
                drawing.ClearSelection2(True)
            for dimension in task['dimensions']:
                drawing.ClearSelection2(True)
                for reference in dimension['references']: self.select_drawing_entity(drawing,reference)
                x,y = [finite(v)/1000 for v in dimension['position_mm']]
                method = {'horizontal':'AddHorizontalDimension2','vertical':'AddVerticalDimension2',
                          'general':'AddDimension2'}[dimension.get('kind','general')]
                display = getattr(drawing,method)(x,y,0)
                if display is None: raise RuntimeError('native drawing dimension failed')
                # No cosmetic numeric override; dimension must come from selected model entities.
            for annotation in task['annotations']:
                drawing.ClearSelection2(True)
                if annotation.get('reference'): self.select_drawing_entity(drawing,annotation['reference'])
                note = drawing.InsertNote(annotation['text'])
                if note is None: raise RuntimeError('drawing note failed')
                x,y = [finite(v)/1000 for v in annotation['position_mm']]
                if not note.GetAnnotation().SetPosition2(x,y,0): raise RuntimeError('drawing annotation position failed')
            bom = task['drawing_model']['bom']
            if bom:
                model_views = [views[v['id']] for v in task['drawing_model']['views'] if v['kind']=='model']
                if not model_views: raise ValueError('assembly BOM requires a model view')
                configuration = assembly_receipt['documents'][task['node']]['configuration']
                table = model_views[0].InsertBomTable4(False,.22,.25,1,0,configuration,task['bom_template'],False,False)
                if table is None: raise RuntimeError('native linked BOM table failed')
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
                note.GetAnnotation().SetPosition2(x,y,0)
            output = folder/task['filename']
            receipt = self.save_reopen(drawing,output,'')
            if 'flat_DXF' in task['exports']:
                part = self.open_document(model_path,assembly_receipt['documents'][task['node']]['configuration'])
                dxf = folder/(Path(task['filename']).stem+'-flat.dxf')
                if not part.ExportToDWG2(str(dxf),model_path,1,True,None,False,False,5,None) or not dxf.is_file():
                    raise RuntimeError('flat manufacturing DXF export failed')
                receipt['flat_dxf'] = str(dxf)
                self.close_document(part)
            results.append({'task':task['id'],**receipt,'manufacturing_approved':False})
        return {'results':results,'native_status':'files_created_reopened','manufacturing_approved':False}
