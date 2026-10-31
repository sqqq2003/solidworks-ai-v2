"""Pilot Windows implementation; call only on the owned STA. Not live-qualified."""
from pathlib import Path
import base64
import math
import uuid
from ..ql5050px.native_drawings import ManufacturingDriver
from ..ql5050px.native_machine import read_member


def feature_error(feature):
    import pythoncom
    from win32com.client import VARIANT
    warning=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_BOOL,False)
    result=feature.GetErrorCode2(warning)
    return int(result[0] if isinstance(result,tuple) else result)


def activate_configuration(model, expected):
    """Avoid switching when already active; require native readback either way."""
    from solidworks_generator import _com_read
    if not isinstance(expected,str) or not expected:
        raise ValueError('explicit configuration required')
    def current():
        manager=_com_read(model,'ConfigurationManager')
        configuration=_com_read(manager,'ActiveConfiguration')
        return str(_com_read(configuration,'Name'))
    if current()==expected:
        return
    if not model.ShowConfiguration2(expected):
        raise RuntimeError('configuration switch failed: '+expected)
    if current()!=expected:
        raise RuntimeError('active configuration readback mismatch: '+expected)


def find_named_feature(model, name):
    """FeatureByName belongs to IPartDoc/IAssemblyDoc, not IModelDoc2."""
    from solidworks_generator import _as_interface,_com_read,ensure_solidworks_typelib
    kind=int(_com_read(model,'GetType'))
    interface={1:'IPartDoc',2:'IAssemblyDoc'}.get(kind)
    if interface is None:
        raise RuntimeError('feature lookup requires a part or assembly')
    typed=_as_interface(ensure_solidworks_typelib(),model,interface)
    return typed.FeatureByName(name)


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
        from app_logging import get_journal
        journal=get_journal()
        self.guard()
        # Resolve every physical target before the first dimension write.
        targets=[]
        observations=[]
        opened={}
        try:
            for edit in edits:
                path=copies.get(str(Path(edit['document']).resolve()))
                if not path: raise RuntimeError('mapped document absent from isolated dependency set')
                self.owned_path(path)
                if path not in opened: opened[path]=self.open_document(path)
                model=opened[path]
                activate_configuration(model,edit['configuration'])
                if find_named_feature(model,edit['feature']) is None: raise RuntimeError('mapped feature missing')
                dimension=model.Parameter(edit['dimension'])
                if dimension is None: raise RuntimeError('mapped dimension missing')
                before=float(dimension.SystemValue)
                if not math.isfinite(before):raise RuntimeError('mapped dimension before value is not finite')
                targets.append((model,dimension,edit,path,uuid.uuid4().hex,before))
            for model,dimension,edit,path,step_id,before in targets:
                activate_configuration(model,edit['configuration'])
                value=edit['value']/1000 if edit['unit']=='mm' else math.radians(edit['value']) if edit['unit']=='deg' else edit['value']
                unit_si='m' if edit['unit']=='mm' else 'rad' if edit['unit']=='deg' else edit['unit']
                journal.record('dimension_change_started',step_id=step_id,parameter=edit['parameter'],
                    work_copy=str(path),configuration=edit['configuration'],unit_si=unit_si,
                    before_value_si=before,target_value_si=value)
                try:
                    if int(dimension.SetSystemValue3(value,3,[edit['configuration']]))!=0:
                        raise RuntimeError('native dimension write refused')
                    after=float(dimension.SystemValue)
                    if not math.isfinite(after) or not math.isclose(after,value,rel_tol=1e-9,abs_tol=1e-9):
                        raise RuntimeError('mapped dimension readback mismatch')
                except Exception as error:
                    journal.exception('dimension_change_failed',error,step_id=step_id,parameter=edit['parameter'])
                    raise
                journal.record('dimension_change_readback',step_id=step_id,after_value_si=after,
                               geometry_verified=False,production_approved=False)
                observations.append({'step_id':step_id,'before_value_si':before,'after_value_si':after,
                                     'target_value_si':value,'unit_si':unit_si})
            for model in opened.values(): self._save(model)
        except Exception as error:
            journal.exception('dimension_change_batch_failed',error,
                              completed_steps=[item['step_id'] for item in observations])
            raise
        finally:
            for model in opened.values(): self.close_document(model)
        evidence=[]
        for edit,observation in zip(edits,observations):
            model=None
            try:
                model=self.open_document(copies[edit['document']],edit['configuration'])
                activate_configuration(model,edit['configuration'])
                dimension=model.Parameter(edit['dimension'])
                value=edit['value']/1000 if edit['unit']=='mm' else math.radians(edit['value']) if edit['unit']=='deg' else edit['value']
                readback=float(dimension.SystemValue) if dimension is not None else float('nan')
                if not math.isfinite(readback) or not math.isclose(readback,value,rel_tol=1e-9,abs_tol=1e-9):
                    raise RuntimeError('saved mapped dimension readback mismatch')
                journal.record('dimension_change_reopened',step_id=observation['step_id'],
                               parameter=edit['parameter'],reopened_value_si=readback,
                               geometry_verified=False,production_approved=False)
                evidence.append(dict(parameter=edit['parameter'],value_si=value,reopened=True,
                                     reopened_value_si=readback,**observation,
                                     geometry_verified=False,production_approved=False))
            except Exception as error:
                journal.exception('dimension_change_reopen_failed',error,step_id=observation['step_id'],
                                  parameter=edit['parameter'])
                raise
            finally:
                if model is not None:self.close_document(model)
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
            if any(find_named_feature(model,m['id']) is not None for m in mates):
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
