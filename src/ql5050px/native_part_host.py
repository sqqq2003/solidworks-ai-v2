"""Actual editable-part host using existing owned machine/session infrastructure."""
from pathlib import Path
from .native_machine import NativeMachineDriver,read_member
from .editable_features import EditableFeaturesMixin
from .feature_operations import validate_operations


from .sheet_feature_data import ExtraFeatureMixin, EXTRA, validate_extra

class NativePartHost(ExtraFeatureMixin,NativeMachineDriver,EditableFeaturesMixin):
    supported_feature_kinds=EditableFeaturesMixin.supported_feature_kinds | EXTRA
    def create_editable_feature(self,feature):
        if feature['kind'] in EXTRA:return self.create_extra_feature(feature)
        return EditableFeaturesMixin.create_editable_feature(self,feature)
    def __init__(self,lease,root,template):
        NativeMachineDriver.__init__(self,lease,root);self.template=Path(template);self.model=None
    def preflight(self,plan,folder):
        from .modeling_validation import validate_part_plan
        validate_part_plan(plan,self.supported_feature_kinds)
        self.guard()
        self.plan=plan
        if plan.get('cad_source'):
            import hashlib
            source=Path(plan['cad_source']['path'])
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=plan['cad_source']['sha256']:
                raise ValueError('CAD source changed after planning')
        seen=set()
        for feature in plan['features']:
            if not set(feature.get('depends_on',[]))<=seen:raise ValueError('invalid feature dependency order')
            seen.add(feature['id'])
        if not self.template.is_file() or self.template.suffix.lower()!='.prtdot':raise ValueError('explicit existing part template required')
        if plan.get('pending_confirmation'):raise ValueError('unconfirmed plan refused')
        for f in plan['features']:
            if f.get('unit')!='mm':raise ValueError('explicit mm feature IR required')
            if f['kind'] not in self.supported_feature_kinds:raise ValueError('native capability pending: '+f['kind'])
            if not f.get('confirmed') or not f.get('evidence'):raise ValueError('confirmed evidence required')
        validate_operations(plan['features'])
        for feature in plan['features']:validate_extra(feature)
        self.owned_path(folder)
    def verify_feature_tree(self,names):
        result=EditableFeaturesMixin.verify_feature_tree(self,names)
        checks=[]
        import math
        for row in self.plan.get('readback_dimensions',[]):
            if row['unit'] not in {'mm','deg'}:raise ValueError('unsupported readback unit')
            dimension=self.model.Parameter(row['name'])
            if dimension is None:raise RuntimeError('readback dimension missing')
            value=float(dimension.SystemValue)
            expected=row['value']/1000 if row['unit']=='mm' else math.radians(row['value'])
            if not math.isclose(value,expected,rel_tol=1e-7,abs_tol=1e-9):raise RuntimeError('persisted dimension mismatch')
            checks.append({'name':row['name'],'value_si':value})
        if self.plan.get('expected_dims_mm') is not None or self.plan.get('expected_body_count') is not None:
            import solidworks_generator as sw
            from part_verification import solid_inventory
            module=sw.ensure_solidworks_typelib()
            part=sw._as_interface(module,self.model,'IPartDoc')
            bounds,bodies=solid_inventory(part,sw,module)
            actual=[bounds[i+3]-bounds[i] for i in range(3)]
            from .modeling_validation import envelope
            actual=envelope(actual)
            expected=envelope(self.plan['expected_dims_mm']) if self.plan.get('expected_dims_mm') is not None else None
            if expected is not None and any(not math.isclose(a,b,rel_tol=1e-4,abs_tol=.05) for a,b in zip(sorted(actual),sorted(expected))):
                raise RuntimeError('recipe envelope differs from independent expected dimensions')
            if len(bodies)!=self.plan.get('expected_body_count',1):raise RuntimeError('recipe solid body count differs')
            result['recipe_envelope_mm']=actual
        result['dimension_evidence']=checks
        return result
    def export_flat(self,output):
        self.guard()
        if not self.plan.get('flat_export'):return {'status':'not_requested'}
        if not any(f['kind']=='base_flange' for f in self.plan['features']):raise ValueError('flat export requires native sheet metal')
        source=str(read_member(self.model,'GetPathName'))
        target=self.owned_path(Path(output).with_suffix('.dxf'))
        if target.exists():raise FileExistsError(target)
        if not self.model.ExportToDWG2(str(target),source,1,True,None,False,False,5,None) or not target.is_file():
            raise RuntimeError('native flat DXF failed')
        return {'path':str(target),'status':'exported_pending_windows_validation'}
    def create(self):
        self.model=self.app.NewDocument(str(self.template),0,0,0)
        if self.model is None:raise RuntimeError('part creation failed')
        self.lease.note_owned_document(str(read_member(self.model,'GetTitle')),handle_id=id(self.model))
    def rebuild(self):
        self.guard()
        if not read_member(self.model,'EditRebuild3'):raise RuntimeError('native part rebuild failed')
    def save(self,path):
        self.guard();path=self.owned_path(path)
        if path.exists():raise FileExistsError(path)
        from part_verification import assert_native_save
        assert_native_save(path,self.model.SaveAs3(str(path),0,1))
        self.lease.note_owned_document(str(read_member(self.model,'GetTitle')),handle_id=id(self.model))
    def close(self):
        self.close_document(self.model);self.model=None
    def reopen(self,path):self.model=self.open_document(path)


def run_native_part(sw_exe,template,plan,output_dir):
    import sys
    if sys.platform!='win32':raise RuntimeError('Windows worker required')
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    from .staged_modeling import execute_part_job
    from .modeling_validation import validate_part_plan
    validate_part_plan(plan,NativePartHost.supported_feature_kinds)
    def job():
        root=Path(output_dir).resolve()
        if root.exists():raise FileExistsError(root)
        with owned_solidworks(Path(sw_exe)):
            host=NativePartHost(current_lease(),root,template)
            return execute_part_job(plan,host,root)
    return run_on_task_sta(job,timeout=900,task_name='editable-part-staged')

