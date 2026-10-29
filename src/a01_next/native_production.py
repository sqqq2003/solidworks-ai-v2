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
    def apply_mapped_dimensions_observed(self, edits, copies, contracts):
        """Opt-in I02/I03 three-phase observation path; not live-qualified."""
        from owned_part_transaction import change_owned_part
        from batch_review_manifest import file_hash
        from geometry_evidence import require_check_contract
        prepared = []
        seen = set()
        # Check every file binding before the first edit. Only isolated parts
        # are supported here; legacy assembly/angle editing remains separate.
        for edit in edits:
            source = Path(edit['document']).resolve(strict=True)
            path = copies.get(str(source))
            if not path or edit['unit'] != 'mm' or source.suffix.casefold() != '.sldprt':
                raise ValueError('observed dimension requires an isolated millimetre part mapping')
            copy = self.owned_path(path).resolve(strict=True)
            if source.samefile(copy):
                raise ValueError('source and work copy share the same file identity')
            contract = contracts[edit['parameter']]
            require_check_contract(contract['checks'])
            if contract.get('confirmed') is not True or not contract.get('confirmed_by'):
                raise ValueError('observed change requires a reviewed geometry contract')
            if file_hash(source) != contract.get('source_sha256'):
                raise ValueError('observed edit source changed before batch')
            if contract.get('dimensions_mm', {}).get(edit['parameter']) != edit['dimension']:
                raise ValueError('observed edit dimension binding mismatch')
            key = (str(copy), edit['configuration'], edit['dimension'])
            if key in seen:
                raise ValueError('duplicate native dimension in observed edit batch')
            seen.add(key)
            prepared.append((edit, source, copy, contract))
        evidence = []
        for edit, source, copy, contract in prepared:
            def apply(model, edit=edit):
                self.guard()
                activate_configuration(model, edit['configuration'])
                if find_named_feature(model, edit['feature']) is None:
                    raise RuntimeError('mapped feature missing before observed change')
                dimension = model.Parameter(edit['dimension'])
                if dimension is None:
                    raise RuntimeError('mapped dimension missing before observed change')
                value = edit['value'] / 1000
                # SW2025 can return success for scope 3 without changing this
                # part. Scope 1 follows the configuration proved above.
                if int(dimension.SetSystemValue3(value, 1, None)) != 0:
                    raise RuntimeError('native observed dimension write refused')
                return {'parameter': edit['parameter'], 'target_mm': edit['value'],
                        'native_acceptance': 'pending_geometry_readback'}
            receipt = change_owned_part(self, source_path=source,
                source_sha256=contract['source_sha256'], work_copy=copy,
                document_key=str(source), configuration=edit['configuration'],
                step_id='mapped-' + edit['parameter'] + '-' + uuid.uuid4().hex,
                checks=contract['checks'], dimensions_mm=contract['dimensions_mm'], apply_change=apply)
            evidence.append({'parameter': edit['parameter'], 'transaction': receipt,
                             'geometry_verified': False, 'production_approved': False})
        return evidence

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
                    if int(dimension.SetSystemValue3(value,1,None))!=0:
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
