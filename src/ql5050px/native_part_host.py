"""Actual editable-part host using existing owned machine/session infrastructure."""
from pathlib import Path
from .native_machine import NativeMachineDriver,read_member
from .editable_features import EditableFeaturesMixin
from .feature_operations import validate_operations


class NativePartHost(NativeMachineDriver,EditableFeaturesMixin):
    def __init__(self,lease,root,template):
        NativeMachineDriver.__init__(self,lease,root);self.template=Path(template);self.model=None
    def preflight(self,plan,folder):
        self.guard()
        if not self.template.is_file() or self.template.suffix.lower()!='.prtdot':raise ValueError('explicit existing part template required')
        if plan.get('pending_confirmation'):raise ValueError('unconfirmed plan refused')
        for f in plan['features']:
            if f['kind'] not in self.supported_feature_kinds:raise ValueError('native capability pending: '+f['kind'])
            if not f.get('confirmed') or not f.get('evidence'):raise ValueError('confirmed evidence required')
        validate_operations(plan['features'])
        self.owned_path(folder)
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
    def job():
        root=Path(output_dir).resolve()
        if root.exists():raise FileExistsError(root)
        with owned_solidworks(Path(sw_exe)):
            host=NativePartHost(current_lease(),root,template)
            return execute_part_job(plan,host,root)
    return run_on_task_sta(job,timeout=900,task_name='editable-part-staged')
