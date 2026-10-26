"""Pilot Windows implementation; call only on the owned STA. Not live-qualified."""
from pathlib import Path
import base64
import math
from ..ql5050px.native_drawings import ManufacturingDriver
from ..ql5050px.native_machine import read_member


def feature_error(feature):
    import pythoncom
    from win32com.client import VARIANT
    warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
    result=feature.GetErrorCode2(warning)
    return int(result[0] if isinstance(result,tuple) else result)


class A01ProductionDriver(ManufacturingDriver):
    def _save(self,model):
        self.guard()
        self.verify_references(model)
        if not read_member(model,'EditRebuild3'):
            raise RuntimeError('mapped work-copy rebuild failed')
        result=model.Save3(1,0,0)
        if isinstance(result,tuple):
            if not result[0] or len(result)<2 or result[1]:
                raise RuntimeError('work-copy Save3 error')
        elif result is not True:
            raise RuntimeError('work-copy save unverified')

    def apply_mapped_dimensions(self,edits,copies):
        self.guard()
        # Resolve every physical target before the first dimension write.
        targets=[]
        opened={}
        try:
            for edit in edits:
                path=copies.get(str(Path(edit['document']).resolve()))
                if not path: raise RuntimeError('mapped document absent from isolated dependency set')
                self.owned_path(path)
                if path not in opened: opened[path]=self.open_document(path)
                model=opened[path]
                if not model.ShowConfiguration2(edit['configuration']): raise RuntimeError('mapped configuration missing')
                if model.FeatureByName(edit['feature']) is None: raise RuntimeError('mapped feature missing')
                dimension=model.Parameter(edit['dimension'])
                if dimension is None: raise RuntimeError('mapped dimension missing')
                targets.append((model,dimension,edit,path))
            for model,dimension,edit,path in targets:
                if not model.ShowConfiguration2(edit['configuration']): raise RuntimeError('configuration switch failed')
                value=edit['value']/1000 if edit['unit']=='mm' else math.radians(edit['value']) if edit['unit']=='deg' else edit['value']
                if int(dimension.SetSystemValue3(value,3,[edit['configuration']]))!=0:
                    raise RuntimeError('native dimension write refused')
                if not math.isclose(float(dimension.SystemValue),value,rel_tol=1e-9,abs_tol=1e-9):
                    raise RuntimeError('mapped dimension readback mismatch')
            for model in opened.values(): self._save(model)
        finally:
            for model in opened.values(): self.close_document(model)
        evidence=[]
        for edit in edits:
            model=self.open_document(copies[edit['document']],edit['configuration'])
            try:
                if not model.ShowConfiguration2(edit['configuration']): raise RuntimeError('reopen configuration failed')
                dimension=model.Parameter(edit['dimension'])
                value=edit['value']/1000 if edit['unit']=='mm' else math.radians(edit['value']) if edit['unit']=='deg' else edit['value']
                if dimension is None or not math.isclose(float(dimension.SystemValue),value,rel_tol=1e-9,abs_tol=1e-9):
                    raise RuntimeError('saved mapped dimension readback mismatch')
                evidence.append(dict(parameter=edit['parameter'],value_si=value,reopened=True))
            finally:self.close_document(model)
        return evidence

    def apply_persistent_mates(self,path,configuration,mates,registry):
        self.guard();self.owned_path(path)
        if not mates:return []
        import pythoncom
        from win32com.client import VARIANT
        from solidworks_generator import _as_interface,ensure_solidworks_typelib
        model=self.open_document(path,configuration)
        evidence=[]
        try:
            self.verify_references(model)
            if not model.ShowConfiguration2(configuration):raise RuntimeError('assembly configuration missing')
            assembly=_as_interface(ensure_solidworks_typelib(),model,'IAssemblyDoc')
            refs={r['id']:r for r in registry['references']}
            # Creating new mates only; never delete or replace an existing feature.
            if any(model.FeatureByName(m['id']) is not None for m in mates):
                raise RuntimeError('mate id already exists; explicit edit workflow required')
            objects={}
            for name in {x for m in mates for x in m['references']}:
                token=VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_UI1,tuple(base64.b64decode(refs[name]['persistent_reference_base64'],validate=True)))
                error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
                entity=model.Extension.GetObjectByPersistReference3(token,error)
                if entity is None or int(error.value)!=0:raise RuntimeError('persistent reference unresolved/suppressed/deleted: '+name)
                objects[name]=entity
            for mate in mates:
                model.ClearSelection2(True)
                for name in mate['references']:
                    data=model.SelectionManager.CreateSelectData();data.Mark=1
                    if refs[name]['entity_type'] in ('plane','axis'):
                        selected=objects[name].Select2(True,1)
                    else:
                        entity=_as_interface(ensure_solidworks_typelib(),objects[name],'IEntity')
                        selected=entity.Select4(True,data)
                    if not selected:raise RuntimeError('persistent entity selection failed')
                distance=mate.get('distance_mm',0)/1000
                angle=math.radians(mate.get('angle_deg',0))
                error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
                native=assembly.AddMate5({'coincident':0,'concentric':1,'parallel':3,'distance':5,'angle':6}[mate['type']],
                    mate['alignment'],False,distance,distance,distance,0,0,angle,angle,angle,False,False,0,error)
                if native is None or int(error.value)!=0:raise RuntimeError('native AddMate5 failed')
                # AddMate5 returns IMate2, not IFeature. Do not assume Feature.Name.
                if not read_member(model,'EditRebuild3'):raise RuntimeError('mate solve/rebuild failed')
                feature=_as_interface(ensure_solidworks_typelib(),native,'IFeature')
                feature.Name=mate['id']
                code=feature_error(feature)
                if code!=0:raise RuntimeError('native mate feature has rebuild errors')
                evidence.append(dict(request_id=mate['id'],feature_error=code))
            self._save(model)
        finally:
            model.ClearSelection2(True)
            self.close_document(model)
        return evidence

    def inspect_native(self,document,motion_samples=()):
        if motion_samples:raise ValueError('A01 production entry does not drive motion yet')
        self.guard();self.owned_path(document)
        model=self.open_document(document)
        try:
            self.verify_references(model)
            if not read_member(model,'EditRebuild3'):raise RuntimeError('saved assembly rebuild failed')
            errors=[]
            def walk(feature):
                while feature is not None:
                    kind=str(read_member(feature,'GetTypeName2'))
                    if kind.startswith('Mate'):
                        code=feature_error(feature)
                        if code!=0:errors.append(dict(name=str(feature.Name),error=code))
                    child=read_member(feature,'GetFirstSubFeature')
                    if child is not None:walk(child)
                    feature=read_member(feature,'GetNextSubFeature')
            feature=read_member(model,'FirstFeature')
            while feature is not None:
                if str(read_member(feature,'GetTypeName2'))=='MateGroup':walk(read_member(feature,'GetFirstSubFeature'))
                feature=read_member(feature,'GetNextFeature')
            if errors:raise RuntimeError('native mate feature errors: '+str(errors))
            manager=read_member(model,'InterferenceDetectionManager')
            manager.TreatCoincidenceAsInterference=False
            hits=manager.GetInterferences() or []
            return dict(reopened=True,rebuilt=True,mate_feature_errors=errors,
                interference_count=len(hits),motion='unverified',engineering_acceptance='unverified')
        finally:self.close_document(model)

    def export_manufacturing(self,plan,assembly_receipt,destination):
        result=super().export_manufacturing(plan,assembly_receipt,destination)
        from .production import sha
        for item in result['results']:
            path=Path(item['path']);pdf=path.with_suffix('.pdf')
            if pdf.exists():raise FileExistsError(pdf)
            drawing=self.open_document(path)
            try:
                from ..ql5050px.drawing_verification import export_pdf
                item['pdf_validation']=export_pdf(self,drawing,pdf)
            finally:self.close_document(drawing)
            item.update(pdf=str(pdf),pdf_sha256=sha(pdf),slddrw_sha256=sha(path),pdf_layout_review='pending')
        return result


def run_production(request,sw_exe,output):
    from .production import prepare_request,execute_request
    prepare_request(request)
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    def job():
        root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
        with owned_solidworks(Path(sw_exe)):
            return execute_request(request,A01ProductionDriver(current_lease(),root),root)
    return run_on_task_sta(job,timeout=900,task_name='a01-production-copy')
